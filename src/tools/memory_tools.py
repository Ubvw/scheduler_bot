from langmem import create_manage_memory_tool, create_search_memory_tool
from langchain_ollama import OllamaEmbeddings
from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.memory import InMemorySaver
store = InMemoryStore(
    index={
        "dims":768,
        "embed":OllamaEmbeddings(model="embeddinggemma:latest")
    }
)

checkpointer = InMemorySaver()



def get_create_manage_memory_tool(namespace):
    """
    Create a tool for managing persistent memories in conversations.
    """
    tool_or_tools = create_manage_memory_tool(namespace)
    if isinstance(tool_or_tools, (list, tuple)):
        return list(tool_or_tools)
    return [tool_or_tools]



def get_create_search_memory_tool(namespace):
    """
    Create a tool for searching memories stored in a LangGraph BaseStore.
    """

    tool_or_tools = create_search_memory_tool(namespace)
    if isinstance(tool_or_tools, (list, tuple)):
        return list(tool_or_tools)
    return [tool_or_tools]


def get_checkpointer():
    return checkpointer

def get_store():
    return store