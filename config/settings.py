import os
from dotenv import load_dotenv
from pathlib import Path

# Load env file - try .env.v3 first
for env_file in ['.env.v3', '.env']:
    if Path(env_file).exists():
        load_dotenv(env_file, override=True)
        break

# Provider selection
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")  # "ollama" or "gemini"

# Ollama settings
OLLAMA_BASE_URL    = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL  = os.getenv("OLLAMA_CHAT_MODEL", "llama3")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Gemini settings
GOOGLE_API_KEY     = os.getenv("GOOGLE_API_KEY", "")
GEMINI_CHAT_MODEL  = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "models/gemini-embedding-001")

# Qdrant - hardcoded correct values
QDRANT_HOST        = "localhost"
QDRANT_PORT        = 6333
QDRANT_COLLECTION  = "sin_docs"

# RAG
CHUNK_SIZE         = 800
CHUNK_OVERLAP      = 100
TOP_K              = 5
SIMILARITY_THRESHOLD = 0.45

# Paths
INCOMING_DOCS_DIR  = os.getenv("INCOMING_DOCS_DIR", "docs/incoming")
PROCESSED_DOCS_DIR = os.getenv("PROCESSED_DOCS_DIR", "docs/processed")
MODIFIED_PWF_DIR   = os.getenv("MODIFIED_PWF_DIR", "modified_pwf")
RESULTS_DIR        = os.getenv("RESULTS_DIR", "results")
MEMORY_STORE_PATH  = os.getenv("MEMORY_STORE_PATH", "memory_store/last_study_v3.json")

# Safety check
if LLM_PROVIDER == "gemini" and not GOOGLE_API_KEY:
    raise ValueError(
        "LLM_PROVIDER=gemini but GOOGLE_API_KEY is not set. "
        "Please add GOOGLE_API_KEY to .env.v3"
    )

print(f"[CONFIG] Provider: {LLM_PROVIDER}")
print(f"[CONFIG] Qdrant: {QDRANT_HOST}:{QDRANT_PORT}/{QDRANT_COLLECTION}")
# Never print the API key
