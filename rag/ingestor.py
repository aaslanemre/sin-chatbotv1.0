"""
Ingests PDFs from the docs/ folder into Qdrant.
Run once (or when new docs are added): python -m rag.ingestor
"""
import os
import fitz  # PyMuPDF
from pathlib import Path
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from config.settings import (
    LLM_PROVIDER,
    OLLAMA_BASE_URL, OLLAMA_EMBED_MODEL,
    GOOGLE_API_KEY, GEMINI_EMBED_MODEL,
    QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION,
    CHUNK_SIZE, CHUNK_OVERLAP
)

DOCS_DIR = Path(os.getenv("DOCS_DIR", "docs"))


def extract_text_from_pdf(pdf_path: Path) -> str:
    doc = fitz.open(pdf_path)
    return "\n".join(page.get_text() for page in doc)


def ingest_docs():
    pdf_files = list(DOCS_DIR.glob("*.pdf")) + list(DOCS_DIR.glob("*.PDF"))
    if not pdf_files:
        print("Nenhum PDF encontrado em docs/")
        return

    print(f"Encontrados {len(pdf_files)} PDFs. Iniciando ingestão...")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ".", " "]
    )

    if LLM_PROVIDER == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        embeddings = GoogleGenerativeAIEmbeddings(
            model=GEMINI_EMBED_MODEL,
            google_api_key=GOOGLE_API_KEY,
        )
    else:
        from langchain_ollama import OllamaEmbeddings
        embeddings = OllamaEmbeddings(
            base_url=OLLAMA_BASE_URL,
            model=OLLAMA_EMBED_MODEL,
        )

    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    # Create collection if it doesn't exist
    existing = [c.name for c in client.get_collections().collections]
    if QDRANT_COLLECTION not in existing:
        # Get embedding dimension by embedding a test string
        sample = embeddings.embed_query("test")
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=len(sample), distance=Distance.COSINE)
        )
        print(f"Coleção '{QDRANT_COLLECTION}' criada.")

    all_docs = []
    for pdf_path in pdf_files:
        print(f"  Processando: {pdf_path.name}")
        text = extract_text_from_pdf(pdf_path)
        chunks = splitter.create_documents(
            [text],
            metadatas=[{"source": pdf_path.name}]
        )
        all_docs.extend(chunks)

    print(f"Total de chunks: {len(all_docs)}. Indexando no Qdrant...")

    QdrantVectorStore.from_documents(
        documents=all_docs,
        embedding=embeddings,
        url=f"http://{QDRANT_HOST}:{QDRANT_PORT}",
        collection_name=QDRANT_COLLECTION,
    )

    print("Ingestão concluída.")


if __name__ == "__main__":
    ingest_docs()
