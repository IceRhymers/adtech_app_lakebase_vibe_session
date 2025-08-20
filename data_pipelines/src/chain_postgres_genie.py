import functools
import os
import uuid
from typing import Any, Generator, Literal, Optional, Dict, List, Optional

import mlflow
from mlflow.models import ModelConfig
from databricks.sdk import WorkspaceClient
from databricks_langchain import (
    ChatDatabricks,
    UCFunctionToolkit,
    DatabricksFunctionClient,
    set_uc_function_client
)
client = DatabricksFunctionClient()
set_uc_function_client(client) 
from databricks_langchain.genie import GenieAgent
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent
from mlflow.langchain.chat_agent_langgraph import ChatAgentState
from mlflow.pyfunc import ChatAgent
from mlflow.types.agent import (
    ChatAgentChunk,
    ChatAgentMessage,
    ChatAgentResponse,
    ChatContext,
)
from pydantic import BaseModel
from sqlalchemy import create_engine, text, event
from pgvector.psycopg2 import register_vector
from databricks.sdk import WorkspaceClient
from databricks_langchain import DatabricksEmbeddings
from databricks_langchain.chat_models import ChatDatabricks
from langchain.tools import Tool
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.prompts import ChatPromptTemplate
from langchain.schema.runnable import RunnableLambda

# Enable MLflow Tracing for LangChain
mlflow.langchain.autolog()

# Load chain configuration provided at logging/deployment time.
# The config should include at least:
# - "llm_model_serving_endpoint_name": str
# - "embedding_model": str
# - "llm_prompt_template": str (expects {context} and {question})
model_config: ModelConfig = mlflow.models.ModelConfig()


def _get_required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def get_postgres_connection(
    client: WorkspaceClient,
    db_instance_name: str,
    database_name: Optional[str] = "databricks_postgres",
) -> str:
    """
    Build a PostgreSQL SQLAlchemy URL (psycopg2) using Databricks Database credentials.

    Uses POSTGRES_GROUP env var as username if set; otherwise current user.
    Always enforces sslmode=require.
    """
    database = client.database.get_database_instance(db_instance_name)
    credentials = client.database.generate_database_credential(
        instance_names=[db_instance_name], request_id=str(uuid.uuid4())
    )

    postgres_group = os.getenv("POSTGRES_GROUP")
    username = (
        postgres_group if postgres_group else client.current_user.me().user_name
    )

    host = database.read_write_dns
    port = "5432"
    password = credentials.token
    db_name = database_name or "databricks_postgres"

    # SQLAlchemy URL with psycopg2 driver
    sqlalchemy_url = (
        f"postgresql+psycopg2://{username}:{password}@{host}:{port}/{db_name}?sslmode=require"
    )
    return sqlalchemy_url


# --- Databricks Auth (required for both embeddings and DB credentials) ---
_DATABRICKS_HOST = _get_required_env("DATABRICKS_HOST")
_DATABRICKS_TOKEN = _get_required_env("DATABRICKS_TOKEN")

workspace_client = WorkspaceClient(host=_DATABRICKS_HOST, token=_DATABRICKS_TOKEN)


# --- Postgres Engine (pgvector) ---
def _build_engine() -> Any:
    # Allow configuration via model_config or environment variables
    db_instance_name = (
        os.environ.get("DATABASE_INSTANCE_NAME")
        or model_config.get("database_instance_name")
    )
    if not db_instance_name:
        raise RuntimeError(
            "A Postgres database instance name is required. Set env 'DATABASE_INSTANCE_NAME' "
            "or include 'database_instance_name' in the model_config."
        )

    postgres_database_name = (
        os.environ.get("POSTGRES_DATABASE_NAME")
        or model_config.get("postgres_database_name")
        or "databricks_postgres"
    )

    database_url = get_postgres_connection(
        workspace_client, db_instance_name, postgres_database_name
    )

    engine = create_engine(database_url, pool_pre_ping=True)

    @event.listens_for(engine, "connect")
    def _register_vector(dbapi_connection, connection_record):  # noqa: ANN001
        # Map Python lists to pgvector type for psycopg2
        register_vector(dbapi_connection)

    return engine


engine = _build_engine()


# --- Embeddings ---
embeddings = DatabricksEmbeddings(
    endpoint=model_config.get("embedding_model"),
    token=_DATABRICKS_TOKEN,
)

# --- Vector similarity search over Postgres (pgvector) ---
def pg_vector_similarity_search(
    query_text: str,
    k: int = 3,
    filters: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Perform similarity search against message embeddings in Postgres (pgvector).

    Schema expectations:
    - message_embeddings(me: id, message_id, user_name, chat_id, embedding vector)
    - chat_history(ch: id, message_content, message_type, created_at, message_order)
    """
    filters = filters or {}

    # 1) Embed the query
    query_embedding = embeddings.embed_query(query_text)

    # 2) WHERE clause from filters
    where_conditions: List[str] = []
    params: Dict[str, Any] = {}

    if "user_name" in filters:
        where_conditions.append("me.user_name = :user_name")
        params["user_name"] = filters["user_name"]

    if "chat_id" in filters:
        where_conditions.append("me.chat_id = :chat_id")
        params["chat_id"] = filters["chat_id"]

    where_clause = ""
    if where_conditions:
        where_clause = "WHERE " + " AND ".join(where_conditions)

    # 3) Query using cosine distance operator (<=>) provided by pgvector
    sql = text(
        f"""
        SELECT
            ch.message_content,
            me.user_name,
            me.chat_id,
            ch.message_type,
            ch.created_at,
            ch.message_order,
            (me.embedding <=> CAST(:query_embedding AS vector)) AS distance
        FROM message_embeddings me
        JOIN chat_history ch ON me.message_id = ch.id
        {where_clause}
        ORDER BY me.embedding <=> CAST(:query_embedding AS vector)
        LIMIT :k
        """
    )

    with engine.connect() as conn:
        rows = conn.execute(
            sql, {"query_embedding": query_embedding, "k": k, **params}
        ).fetchall()

    passages = [f"Passage: {r.message_content}" for r in rows]
    return "\n".join(passages)
  

def create_context_aware_vector_search_tool(state):
  """Create a vector search tool that has access to user context from state"""
  
  def filtered_vector_search(query: str) -> str:
      # Extract user context from state
      user_context = state.get("user_context", {})
      filters = user_context.get("filters", {})
      
      # Use your existing pg_vector_similarity_search with filters
      return pg_vector_similarity_search(
          embeddings=embeddings, 
          query=query, 
          k=retriever_config["parameters"]["k"], 
          filters=filters
      )
  
  return Tool(
      name="search_chat_history",
      description="Retrieve chat history from Postgres (pgvector) for the current user; use only if the immediate conversation context is insufficient. THe input to this function should be the user message.",
      func=filtered_vector_search,
  )


genie_agent_description = model_config.get('genie_agent_description')
general_assistant_description = model_config.get('general_assistant_description')
code_agent_description = model_config.get('code_agent_description')

genie_agent = GenieAgent(
    genie_space_id=model_config.get('genie_space_id'),
    genie_agent_name="Genie",
    description=genie_agent_description,
    client=workspace_client,
    include_context=True,
)

# Max number of interactions between agents
MAX_ITERATIONS = 3

worker_descriptions = {
    "Genie": genie_agent_description,
    "General": general_assistant_description,
    "Coder": code_agent_description,
}

formatted_descriptions = "\n".join(
    f"- {name}: {desc}" for name, desc in worker_descriptions.items()
)

system_prompt = f"Decide between routing between the following workers or ending the conversation if an answer is provided. \n{formatted_descriptions}"
options = ["FINISH"] + list(worker_descriptions.keys())
FINISH = {"next_node": "FINISH"}

# Our foundation model answering the final prompt
model = ChatDatabricks(
    endpoint=model_config.get("llm_model_serving_endpoint_name"),
    extra_params={"temperature": 0.01, "max_tokens": 500}
)

# Custom Static Tools
tools = []
uc_tool_names = ["system.ai.*"]
uc_toolkit = UCFunctionToolkit(function_names=uc_tool_names)
tools.extend(uc_toolkit.tools)

def supervisor_agent(state):
    count = state.get("iteration_count", 0) + 1
    if count > MAX_ITERATIONS:
        return FINISH
    
    class nextNode(BaseModel):
        next_node: Literal[tuple(options)]

    preprocessor = RunnableLambda(
        lambda state: [{"role": "system", "content": system_prompt}] + state["messages"]
    )
    supervisor_chain = preprocessor | model.with_structured_output(nextNode)
    next_node = supervisor_chain.invoke(state).next_node
    
    # if routed back to the same node, exit the loop
    if state.get("next_node") == next_node:
        return FINISH
    return {
        "iteration_count": count,
        "next_node": next_node
    }

#######################################
# Define our multiagent graph structure
#######################################


def agent_node(state, agent, name):
    result = agent.invoke(state)
    return {
        "messages": [
            {
                "role": "assistant",
                "content": result["messages"][-1].content,
                "name": name,
            }
        ]
    }


def final_answer(state):
    prompt = "Using only the content in the messages, respond to the previous user question using the answer given by the other assistant messages."
    preprocessor = RunnableLambda(
        lambda state: state["messages"] + [{"role": "user", "content": prompt}]
    )
    final_answer_chain = preprocessor | model
    return {"messages": [final_answer_chain.invoke(state)]}


def agent_node_with_context(state, agent, name):
    """Enhanced agent node that injects context-aware tools"""
    
    # Create the shared vector search tool with current state context
    vector_search_tool = create_context_aware_vector_search_tool(state)
    
    if name == "Genie":
        # Genie already has its tools, just add vector search
        enhanced_agent = agent  # Genie agent already configured
        # Note: GenieAgent might need special handling - see option below
        
    elif name == "Coder" or name == "General":
        # Add vector search tool to Coder's existing UC tools
        enhanced_tools = tools + [vector_search_tool]  # tools is your UC toolkit
        enhanced_agent = create_react_agent(model, tools=[vector_search_tool])
        
    # Execute with enhanced agent
    result = enhanced_agent.invoke(state)
    return {
        "messages": [{
            "role": "assistant",
            "content": result["messages"][-1].content,
            "name": name,
        }]
    }

# Create enhanced agent nodes
def enhanced_genie_node(state):
    enhanced_agent = genie_agent
    return agent_node_with_context(state, enhanced_agent, "Genie")

def enhanced_coder_node(state):
    return agent_node_with_context(state, None, "Coder")

def enhanced_general_node(state):
    return agent_node_with_context(state, None, "General")

class AgentState(ChatAgentState):
    next_node: str
    iteration_count: int
    user_context: Optional[Dict[str, Any]] = None

workflow = StateGraph(AgentState)
# Agent States
workflow.add_node("Genie", enhanced_genie_node)
workflow.add_node("Coder", enhanced_coder_node)
workflow.add_node("General", enhanced_general_node)
# Supervisor States
workflow.add_node("supervisor", supervisor_agent)
workflow.add_node("final_answer", final_answer)

workflow.set_entry_point("supervisor")
# We want our workers to ALWAYS "report back" to the supervisor when done
for worker in worker_descriptions.keys():
    workflow.add_edge(worker, "supervisor")

# Let the supervisor decide which next node to go
workflow.add_conditional_edges(
    "supervisor",
    lambda x: x["next_node"],
    {**{k: k for k in worker_descriptions.keys()}, "FINISH": "final_answer"},
)
workflow.add_edge("final_answer", END)
multi_agent = workflow.compile()

###################################
# Wrap our multi-agent in ChatAgent
###################################


class LangGraphChatAgent(ChatAgent):
    def __init__(self, agent: CompiledStateGraph):
        self.agent = agent

    def predict(
    self,
    messages: list[ChatAgentMessage],
    context: Optional[ChatContext] = None,
    custom_inputs: Optional[dict[str, Any]] = None,
    ) -> ChatAgentResponse:
        # Extract user context from custom_inputs
        user_context = {}
        if custom_inputs and "filters" in custom_inputs:
            user_context["filters"] = custom_inputs["filters"]
        
        request = {
            "messages": [m.model_dump_compat(exclude_none=True) for m in messages],
            "user_context": user_context  # Inject user context into state
        }

        messages = []
        for event in self.agent.stream(request, stream_mode="updates"):
            for node_data in event.values():
                messages.extend(
                    ChatAgentMessage(**msg) for msg in node_data.get("messages", [])
                )
        return ChatAgentResponse(messages=messages)

    def predict_stream(
        self,
        messages: list[ChatAgentMessage],
        context: Optional[ChatContext] = None,
        custom_inputs: Optional[dict[str, Any]] = None,
    ) -> Generator[ChatAgentChunk, None, None]:
        request = {
            "messages": [m.model_dump_compat(exclude_none=True) for m in messages]
        }
        for event in self.agent.stream(request, stream_mode="updates"):
            for node_data in event.values():
                yield from (
                    ChatAgentChunk(**{"delta": msg})
                    for msg in node_data.get("messages", [])
                )


# Create the agent object, and specify it as the agent object to use when
# loading the agent back for inference via mlflow.models.set_model()
AGENT = LangGraphChatAgent(multi_agent)
chain = RunnableLambda(lambda x: AGENT.predict(x))
mlflow.models.set_model(model=chain)