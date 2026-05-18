import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL   = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3")
OLLAMA_EMBED_MODEL= os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

QDRANT_HOST       = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT       = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "sin_docs")

CHUNK_SIZE        = int(os.getenv("CHUNK_SIZE", 800))
CHUNK_OVERLAP     = int(os.getenv("CHUNK_OVERLAP", 100))
TOP_K             = int(os.getenv("TOP_K", 5))
