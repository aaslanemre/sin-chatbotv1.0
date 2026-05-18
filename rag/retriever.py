from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from config.settings import (
    OLLAMA_BASE_URL, OLLAMA_EMBED_MODEL,
    QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION, TOP_K
)


def get_retriever():
    embeddings = OllamaEmbeddings(
        base_url=OLLAMA_BASE_URL,
        model=OLLAMA_EMBED_MODEL
    )
    vectorstore = QdrantVectorStore.from_existing_collection(
        embedding=embeddings,
        url=f"http://{QDRANT_HOST}:{QDRANT_PORT}",
        collection_name=QDRANT_COLLECTION,
    )
    return vectorstore.as_retriever(search_kwargs={"k": TOP_K})
