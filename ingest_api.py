"""
Lightweight FastAPI server that n8n calls to ingest a PDF.
Run separately: uvicorn ingest_api:app --port 8001
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
import fitz
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from config.settings import (
    OLLAMA_BASE_URL, OLLAMA_EMBED_MODEL,
    QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION,
    CHUNK_SIZE, CHUNK_OVERLAP,
    PROCESSED_DOCS_DIR,
)

app = FastAPI(title="SIN Ingestion API", version="2.1.0")


class IngestRequest(BaseModel):
    file_path: str


@app.post("/ingest")
async def ingest_pdf(req: IngestRequest):
    pdf_path = Path(req.file_path)
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {pdf_path}")

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Deduplication check — skip if already indexed
    try:
        existing, _ = client.scroll(
            collection_name=QDRANT_COLLECTION,
            scroll_filter=Filter(
                must=[FieldCondition(key="metadata.source", match=MatchValue(value=pdf_path.name))]
            ),
            limit=1,
        )
        if existing:
            return {"status": "skipped", "reason": "already indexed", "file": pdf_path.name}
    except Exception:
        # Collection may not exist yet — proceed with ingestion
        pass

    # Extract text
    doc = fitz.open(pdf_path)
    text = "\n".join(page.get_text() for page in doc)

    if not text.strip():
        return {"status": "skipped", "reason": "no extractable text", "file": pdf_path.name}

    # Chunk
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " "],
    )
    chunks = splitter.create_documents(
        [text],
        metadatas=[{"source": pdf_path.name}],
    )

    # Embed and store
    embeddings = OllamaEmbeddings(base_url=OLLAMA_BASE_URL, model=OLLAMA_EMBED_MODEL)
    QdrantVectorStore.from_documents(
        documents=chunks,
        embedding=embeddings,
        url=f"http://{QDRANT_HOST}:{QDRANT_PORT}",
        collection_name=QDRANT_COLLECTION,
    )

    # Move to processed
    processed_dir = Path(PROCESSED_DOCS_DIR)
    processed_dir.mkdir(parents=True, exist_ok=True)
    pdf_path.rename(processed_dir / pdf_path.name)

    return {"status": "indexed", "file": pdf_path.name, "chunks": len(chunks)}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "SIN Ingestion API v2.1"}
