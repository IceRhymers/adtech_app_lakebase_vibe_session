import functools
import os
import uuid
from typing import Any, Generator, Literal, Optional, Dict, List

import mlflow
import pydantic
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
from mlflow.entities import SpanType, Document

# Enable MLflow Tracing for LangChain
mlflow.autolog()
mlflow.langchain.autolog()

# Load chain configuration provided at logging/deployment time.
model_config: ModelConfig = mlflow.models.ModelConfig()

# Pydantic models for input validation
class Message(pydantic.BaseModel):
    role: str
    content: str
    name: Optional[str] = None

class Filters(pydantic.BaseModel):
    user_name: str  # Required
    chat_id: Optional[str] = None

class CustomInputs(pydantic.BaseModel):
    filters: Filters
    k: Optional[int] = None  # Optional, will default to model_config value

class ChatRequest(pydantic.BaseModel):
    messages: List[Message]
    custom_inputs: Optional[CustomInputs] = None

class ChatResponse(pydantic.BaseModel):
    messages: List[Message]
    finish_reason: Optional[str] = None


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
@mlflow.trace
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

    span = mlflow.get_current_active_span()
    span.set_outputs([Document(page_content=sql)])

    with engine.connect() as conn:
        rows = conn.execute(
            sql, {"query_embedding": query_embedding, "k": k, **params}
        ).fetchall()

    passages = [f"Passage: {r.message_content}" for r in rows]
    return "\n".join(passages)


def create_context_aware_vector_search_tool(state, custom_k: Optional[int] = None):
    """Create a vector search tool that has access to user context from state"""

    def filtered_vector_search(query: str) -> str:
        # Extract user context from state
        user_context = state.get("user_context", {})
        filters = user_context.get("filters", {})

        # Use custom k if provided, otherwise fall back to model_config default
        k = custom_k if custom_k is not None else model_config.get('k')

        # Use your existing pg_vector_similarity_search with filters and custom k
        return pg_vector_similarity_search(
            query_text=query, 
            k=k, 
            filters=filters
        )

    return Tool(
        name="search_chat_history",
        description="Retrieve chat history from Postgres (pgvector) for the current user; use only if the immediate conversation context is insufficient. The input to this function should be the user message.",
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


def agent_node_with_context(state, agent, name, custom_k: Optional[int] = None):
    """Enhanced agent node that injects context-aware tools"""

    # Create the shared vector search tool with current state context and custom k
    vector_search_tool = create_context_aware_vector_search_tool(state, custom_k)

    if name == "Genie":
        # Genie already has its tools, just add vector search
        enhanced_agent = agent  # Genie agent already configured

    elif name == "Coder" or name == "General":
        # Add vector search tool to other agents' tools
        enhanced_tools = tools + [vector_search_tool]
        enhanced_agent = create_react_agent(model, tools=enhanced_tools)

    # Execute with enhanced agent
    result = enhanced_agent.invoke(state)
    return {
        "messages": [{
            "role": "assistant",
            "content": result["messages"][-1].content,
            "name": name,
        }]
    }

class AgentState(ChatAgentState):
    next_node: str
    iteration_count: int
    user_context: Optional[Dict[str, Any]] = None
    custom_k: Optional[int] = None

# Create enhanced agent nodes
def enhanced_genie_node(state):
    custom_k = state.get("custom_k")
    return agent_node_with_context(state, genie_agent, "Genie", custom_k)

def enhanced_coder_node(state):
    custom_k = state.get("custom_k")
    return agent_node_with_context(state, None, "Coder", custom_k)

def enhanced_general_node(state):
    custom_k = state.get("custom_k")
    return agent_node_with_context(state, None, "General", custom_k)

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
# Streaming LangGraph ChatAgent
###################################

class PostgresGenieChatAgent(ChatAgent):
    def __init__(self, agent: CompiledStateGraph):
        self.agent = agent

    def predict(
        self,
        messages: list[ChatAgentMessage],
        context: Optional[ChatContext] = None,
        custom_inputs: Optional[dict[str, Any]] = None,
    ) -> ChatAgentResponse:
        """Non-streaming predict method for backward compatibility"""
        # Extract user context and custom_k from custom_inputs
        user_context = {}
        custom_k = None

        if custom_inputs:
            if "filters" in custom_inputs:
                user_context["filters"] = custom_inputs["filters"]
            custom_k = custom_inputs.get("k")

        agent_request = {
            "messages": [m.model_dump_compat(exclude_none=True) for m in messages],
            "user_context": user_context,
            "custom_k": custom_k
        }

        response_messages = []
        for event in self.agent.stream(agent_request, stream_mode="updates"):
            for node_data in event.values():
                response_messages.extend(
                    ChatAgentMessage(**msg) for msg in node_data.get("messages", [])
                )

        return ChatAgentResponse(messages=response_messages)

    def predict_stream(
        self,
        messages: list[ChatAgentMessage],
        context: Optional[ChatContext] = None,
        custom_inputs: Optional[dict[str, Any]] = None,
    ) -> Generator[ChatAgentChunk, None, None]:
        """Streaming predict method - yields incremental responses as they're generated"""
        # Extract user context and custom_k from custom_inputs
        user_context = {}
        custom_k = None

        if custom_inputs:
            if "filters" in custom_inputs:
                user_context["filters"] = custom_inputs["filters"]
            custom_k = custom_inputs.get("k")

        agent_request = {
            "messages": [m.model_dump_compat(exclude_none=True) for m in messages],
            "user_context": user_context,
            "custom_k": custom_k
        }

        for event in self.agent.stream(agent_request, stream_mode="updates"):
            for node_data in event.values():
                yield from (
                    ChatAgentChunk(**{"delta": msg})
                    for msg in node_data.get("messages", [])
                )


###################################
# Pydantic-based PythonModel (Legacy Support)
###################################

class ChatAgentPythonModel(mlflow.pyfunc.PythonModel):
    def __init__(self):
        self.agent = multi_agent

    def predict(self, context, model_input: List[ChatRequest]) -> List[ChatResponse]:
        """
        Legacy predict method with pydantic type hints for automatic schema generation.
        Note: MLflow expects List[InputType] -> List[OutputType] for pyfunc models.
        """
        responses = []

        for request in model_input:
            # Extract user context from request
            user_context = {}
            custom_k = None

            if request.custom_inputs:
                user_context["filters"] = request.custom_inputs.filters.model_dump()
                custom_k = request.custom_inputs.k

            # Convert pydantic messages to dict format for langgraph
            messages_dict = [msg.model_dump(exclude_none=True) for msg in request.messages]

            agent_request = {
                "messages": messages_dict,
                "user_context": user_context,
                "custom_k": custom_k
            }

            response_messages = []
            for event in self.agent.stream(agent_request, stream_mode="updates"):
                for node_data in event.values():
                    for msg in node_data.get("messages", []):
                        response_messages.append(Message(**msg))

            responses.append(ChatResponse(messages=response_messages))

        return responses

# Create the streaming model instance and set it for MLflow
streaming_model_instance = PostgresGenieChatAgent(multi_agent)
mlflow.models.set_model(model=streaming_model_instance)