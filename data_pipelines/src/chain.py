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

prompt = ChatPromptTemplate.from_messages(
    [  
        ("system", model_config.get("llm_prompt_template")), # Contains the instructions from the configuration
        ("user", "{question}") #user's questions
    ]
)

# Our foundation model answering the final prompt
model = ChatDatabricks(
    endpoint=model_config.get("llm_model_serving_endpoint_name"),
    extra_params={"temperature": 0.01, "max_tokens": 500}
)

def extract_user_query_string(chat_messages_array):
    return chat_messages_array[-1]["content"]

############
# RAG Chain
############
chain = (
   {
       "question": itemgetter("messages") | RunnableLambda(extract_user_query_string),
       "context": RunnablePassthrough()
       | RunnableLambda(
           lambda input: configurable_vs_retriever.invoke(
               extract_user_query_string(input["messages"]),
               config=create_configurable_with_filters(input, retriever_config),
           )
       )
       | RunnableLambda(format_context),
   }
   | prompt
   | model
   | StrOutputParser()
)

# Tell MLflow logging where to find your chain.
mlflow.models.set_model(model=chain)