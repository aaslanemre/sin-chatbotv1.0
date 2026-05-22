from langchain_qdrant import QdrantVectorStore
from config.settings import (
    LLM_PROVIDER,
    OLLAMA_BASE_URL, OLLAMA_EMBED_MODEL,
    GOOGLE_API_KEY, GEMINI_EMBED_MODEL,
    QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION,
    TOP_K,
)


def get_embeddings():
    if LLM_PROVIDER == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        return GoogleGenerativeAIEmbeddings(
            model=GEMINI_EMBED_MODEL,
            google_api_key=GOOGLE_API_KEY,
        )
    else:
        from langchain_ollama import OllamaEmbeddings
        return OllamaEmbeddings(
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_EMBED_MODEL,
        )


def get_retriever():
    embeddings = get_embeddings()
    vectorstore = QdrantVectorStore.from_existing_collection(
        embedding=embeddings,
        url=f"http://{QDRANT_HOST}:{QDRANT_PORT}",
        collection_name=QDRANT_COLLECTION,
    )
    return vectorstore.as_retriever(
        search_kwargs={"k": TOP_K},
    )
