from databricks.vector_search.client import VectorSearchClient
from databricks_langchain import DatabricksVectorSearch
from langchain.schema.runnable import RunnableLambda, RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables.utils import ConfigurableField
from typing import Dict
from langchain_core.prompts import ChatPromptTemplate
from databricks_langchain.chat_models import ChatDatabricks
from operator import itemgetter
import mlflow
from langchain.tools import Tool
from langchain.agents import create_tool_calling_agent, AgentExecutor

## Enable MLflow Tracing
mlflow.langchain.autolog()

model_config = mlflow.models.ModelConfig(development_config="rag_chain_config.yaml")

retriever_config = {
    "parameters": {
        "k": 5,
        "query_type": "hybrid"
    }
}

# combine dynamic and static filters for vector search
def create_configurable_with_filters(input: Dict, retriever_config: Dict) -> Dict:
   """
   create configurable object with filters.
   Args:
       input: The input data containing filters.
   Returns:
       A configurable object with filters added to the search_kwargs.
   """
   if "custom_inputs" in input:
       filters = input["custom_inputs"]["filters"]
   else:
       filters = {}
   print(filters)
   configurable = {
       "configurable": {
           "search_kwargs": {
               "k": retriever_config.get("parameters")["k"],
               "query_type": retriever_config.get("parameters").get("query_type"),
               "filter": filters
           }
       }
   }
   return configurable

## Turn the Vector Search index into a LangChain retriever
vector_search_as_retriever = DatabricksVectorSearch(
    endpoint=model_config.get("vector_search_endpoint_name"),
    index_name=model_config.get("vector_search_index"),
    columns=["id", "message_content", "user_name"],
).as_retriever(search_kwargs=retriever_config.get("parameters"))

configurable_vs_retriever = vector_search_as_retriever.configurable_fields(
   search_kwargs=ConfigurableField(
       id="search_kwargs",
       name="Search Kwargs",
       description="The search kwargs to use",
   )
)

# Method to format the docs returned by the retriever into the prompt (keep only the text from chunks)
def format_context(docs):
    chunk_contents = [f"Passage: {d.page_content}\n" for d in docs]
    return "".join(chunk_contents)

def vector_search_with_filters(query: str, input_data: Dict = None) -> str:
    """
    Search the vector database for relevant documents.
    
    Args:
        query: The search query string
        input_data: Optional input data containing filters
    
    Returns:
        Formatted context from retrieved documents
    """
    if input_data is None:
        input_data = {}
    
    # Apply filters securely
    config = create_configurable_with_filters(input_data, retriever_config)
    
    # Retrieve documents
    docs = configurable_vs_retriever.invoke(query, config=config)
    
    # Format and return context
    return format_context(docs)

vector_search_tool = Tool(
    name="search_chat_history",
    description="Retreive chat history from this vector search index for the current user, use this tool to answer questions that may refer to previous conversations.",
    func=lambda query: vector_search_with_filters(query, {}),  # Default case without filters
)

# Updated prompt template for tool-calling agent
prompt = ChatPromptTemplate.from_messages([
    ("system", model_config.get('llm_prompt_template')),
    ("user", "{question}"),
    ("placeholder", "{agent_scratchpad}"),
])

# Our foundation model answering the final prompt
model = ChatDatabricks(
    endpoint=model_config.get("llm_model_serving_endpoint_name"),
    extra_params={"temperature": 0.01, "max_tokens": 500}
)

agent = create_tool_calling_agent(model, [vector_search_tool], prompt)
agent_executor = AgentExecutor(agent=agent, tools=[vector_search_tool], verbose=True)

def extract_user_query_string(chat_messages_array):
    return chat_messages_array[-1]["content"]

def extract_context_string(chat_messages_array):
    return '\n'.join([f"Role: {message['role']} - Content: {message['content']}" for message in chat_messages_array[:-1]])

###########
# RAG Chain with Tool
############
def rag_chain_with_tool(input_data: Dict) -> str:
    """
    RAG chain that uses vector search as a tool with proper filtering.
    
    Args:
        input_data: Input containing messages and optional custom_inputs with filters
    
    Returns:
        Generated response
    """
    # Extract user query
    user_query = extract_user_query_string(input_data["messages"])
    
    # Create a modified vector search tool that includes the filters from input_data
    def filtered_vector_search(query: str) -> str:
        return vector_search_with_filters(query, input_data)
    
    # Update the tool with the filtered version
    filtered_tool = Tool(
        name="search_chat_history",
        description="Retreive chat history from this vector search index for the current user, use this tool to answer questions that may refer to previous conversations",
        func=filtered_vector_search,
    )
    
    # Create new agent executor with the filtered tool
    filtered_agent = create_tool_calling_agent(model, [filtered_tool], prompt)
    filtered_agent_executor = AgentExecutor(agent=filtered_agent, tools=[filtered_tool], verbose=True)

    context = extract_context_string(input_data["messages"])
    # Execute the agent
    result = filtered_agent_executor.invoke({"question": user_query, "context": context})
    return result["output"]

# Create a runnable version of the chain
chain = RunnableLambda(rag_chain_with_tool)

# Tell MLflow logging where to find your chain.
mlflow.models.set_model(model=chain)