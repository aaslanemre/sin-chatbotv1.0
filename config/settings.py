import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env.v3 if it exists, otherwise fall back to .env
env_file = ".env.v3" if Path(".env.v3").exists() else ".env"
load_dotenv(env_file)

OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL  = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

QDRANT_HOST        = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT        = int(os.getenv("QDRANT_PORT", 6335))
QDRANT_COLLECTION  = os.getenv("QDRANT_COLLECTION", "sin_docs_v3")

CHUNK_SIZE         = int(os.getenv("CHUNK_SIZE", 800))
CHUNK_OVERLAP      = int(os.getenv("CHUNK_OVERLAP", 100))
TOP_K              = int(os.getenv("TOP_K", 3))
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", 0.6))

INCOMING_DOCS_DIR  = os.getenv("INCOMING_DOCS_DIR", "docs/incoming")
PROCESSED_DOCS_DIR = os.getenv("PROCESSED_DOCS_DIR", "docs/processed")
MODIFIED_PWF_DIR   = os.getenv("MODIFIED_PWF_DIR", "modified_pwf")
RESULTS_DIR        = os.getenv("RESULTS_DIR", "results")
MEMORY_STORE_PATH  = os.getenv("MEMORY_STORE_PATH", "memory_store/last_study_v3.json")

N8N_PORT        = int(os.getenv("N8N_PORT", 5680))
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://localhost:5680/webhook/ingest-pdf")
INGEST_API_PORT = int(os.getenv("INGEST_API_PORT", 8002))
