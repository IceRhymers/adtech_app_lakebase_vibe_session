import os
import uuid
from typing import Dict, Any, List, Optional

import mlflow
from mlflow.models import ModelConfig

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


def _extract_user_query_string(chat_messages_array: List[Dict[str, str]]) -> str:
    return chat_messages_array[-1]["content"]


def _extract_context_string(chat_messages_array: List[Dict[str, str]]) -> str:
    return "\n".join(
        [f"Role: {m['role']} - Content: {m['content']}" for m in chat_messages_array[:-1]]
    )


# --- Tool wiring ---
def _pg_vector_search_with_filters(query: str, input_data: Optional[Dict[str, Any]] = None) -> str:
    input_data = input_data or {}
    filters = input_data.get("custom_inputs", {}).get("filters", {})
    # Default to k=3 unless provided via config
    k = 3
    try:
        k = model_config.get("retriever_config.parameters.k")
    except Exception:
        pass
    return pg_vector_similarity_search(query_text=query, k=k, filters=filters)


vector_search_tool = Tool(
    name="search_chat_history",
    description=(
        "Retrieve chat history from Postgres (pgvector) for the current user; "
        "use only if the immediate conversation context is insufficient."
    ),
    func=lambda q: _pg_vector_search_with_filters(q, {}),
)


# --- LLM & Prompt ---
prompt = ChatPromptTemplate.from_messages(
    [
        ("system", model_config.get("llm_prompt_template")),
        ("user", "{question}"),
        ("placeholder", "{agent_scratchpad}"),
    ]
)

model = ChatDatabricks(
    endpoint=model_config.get("llm_model_serving_endpoint_name"),
    extra_params={"temperature": 0.01, "max_tokens": 500},
)


def rag_chain_with_tool(input_data: Any) -> str:
    # Normalize inputs: accept either a dict with "messages" or a bare messages list
    if isinstance(input_data, dict) and "messages" in input_data:
        messages: List[Dict[str, str]] = input_data["messages"]  # type: ignore[assignment]
        custom_inputs: Dict[str, Any] = input_data.get("custom_inputs", {})
    elif isinstance(input_data, list):
        messages = input_data  # type: ignore[assignment]
        custom_inputs = {}
    else:
        raise TypeError(
            "Input must be either a dict containing 'messages' or a list of message dicts"
        )

    user_query = _extract_user_query_string(messages)

    def filtered_vector_search(q: str) -> str:
        return _pg_vector_search_with_filters(q, {"custom_inputs": custom_inputs})

    filtered_tool = Tool(
        name="search_chat_history",
        description=(
            "Retreive chat history from this vector database for the current user, use this tool to answer questions that may refer to previous conversations"
        ),
        func=filtered_vector_search,
    )

    filtered_agent = create_tool_calling_agent(model, [filtered_tool], prompt)
    filtered_agent_executor = AgentExecutor(
        agent=filtered_agent, tools=[filtered_tool], verbose=True
    )

    context = _extract_context_string(messages)
    result = filtered_agent_executor.invoke({"question": user_query, "context": context})
    return result["output"]


# Expose a runnable version of the chain and register with MLflow
chain = RunnableLambda(rag_chain_with_tool)
mlflow.models.set_model(model=chain)


