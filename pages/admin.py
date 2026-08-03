import io
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Admin - SIN Chatbot", page_icon="🔧", layout="wide")

# ── Access gate ──────────────────────────────────────────────────────────────
if st.session_state.get("user", {}).get("role") != "admin":
    st.error("Acesso restrito a administradores.")
    st.stop()

from auth.auth_service import (
    list_all_users,
    promote_to_admin,
    delete_user,
    get_chat_logs,
    get_all_documents,
    insert_document,
    update_document_status,
    delete_document_record,
)

st.markdown("## Painel de Administracao")
st.divider()

tab_users, tab_logs, tab_docs = st.tabs(["Usuarios", "Logs de Conversas", "Documentos (Qdrant)"])

# ── TAB 1: Users ─────────────────────────────────────────────────────────────
with tab_users:
    users = list_all_users()
    if users:
        df = pd.DataFrame(users)
        display_cols = ["email", "full_name", "role", "verified", "created_at", "last_login"]
        st.dataframe(df[display_cols], use_container_width=True)

        user_options = {f"{u['email']} ({u['full_name'] or ''})": u["id"] for u in users}
        selected_label = st.selectbox("Selecionar usuario", list(user_options.keys()))
        selected_id = user_options[selected_label]

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Promover a admin"):
                promote_to_admin(selected_id)
                st.success("Usuario promovido a admin.")
                st.rerun()
        with col2:
            if st.button("Remover usuario"):
                if selected_id == st.session_state["user"]["id"]:
                    st.error("Voce nao pode remover a si mesmo.")
                else:
                    delete_user(selected_id)
                    st.success("Usuario removido.")
                    st.rerun()
    else:
        st.info("Nenhum usuario cadastrado.")

# ── TAB 2: Chat Logs ─────────────────────────────────────────────────────────
with tab_logs:
    col_d1, col_d2, col_user = st.columns(3)
    with col_d1:
        start_date = st.date_input("Data inicio", value=datetime.now().date() - timedelta(days=7))
    with col_d2:
        end_date = st.date_input("Data fim", value=datetime.now().date() + timedelta(days=1))
    with col_user:
        users_for_filter = list_all_users()
        user_filter_opts = {"Todos": None}
        user_filter_opts.update({u["email"]: u["id"] for u in users_for_filter})
        selected_user_filter = st.selectbox("Filtrar por usuario", list(user_filter_opts.keys()))
        filter_user_id = user_filter_opts[selected_user_filter]

    logs = get_chat_logs(
        start_date=datetime.combine(start_date, datetime.min.time()),
        end_date=datetime.combine(end_date, datetime.min.time()),
        user_id=filter_user_id,
    )

    if logs:
        # Group by session
        sessions = {}
        for log in logs:
            sid = log["session_id"]
            sessions.setdefault(sid, []).append(log)

        for sid, entries in sessions.items():
            with st.expander(
                f"Sessao {sid[:8]}... - {entries[0]['email']} - "
                f"{entries[0]['created_at'].strftime('%Y-%m-%d %H:%M') if isinstance(entries[0]['created_at'], datetime) else entries[0]['created_at']}"
            ):
                for entry in entries:
                    role_icon = "👤" if entry["role"] == "user" else "🤖"
                    st.markdown(f"**{role_icon} {entry['role']}** ({entry.get('sim_step', '')})")
                    st.markdown(entry["message"][:500])
                    st.caption(str(entry["created_at"]))
                    st.divider()

        # CSV export
        df_logs = pd.DataFrame(logs)
        csv_buf = io.StringIO()
        df_logs.to_csv(csv_buf, index=False)
        st.download_button(
            "Exportar CSV",
            data=csv_buf.getvalue(),
            file_name="chat_logs.csv",
            mime="text/csv",
        )
    else:
        st.info("Nenhum log encontrado para o periodo selecionado.")

# ── TAB 3: Documents ─────────────────────────────────────────────────────────
with tab_docs:
    documents = get_all_documents()
    if documents:
        df_docs = pd.DataFrame(documents)
        st.dataframe(
            df_docs[["filename", "chunk_count", "qdrant_status", "uploaded_at", "uploaded_by_email"]],
            use_container_width=True,
        )

        # Delete document
        doc_options = {d["filename"]: d["id"] for d in documents}
        selected_doc = st.selectbox("Selecionar documento para remover", list(doc_options.keys()))
        if st.button("Remover documento"):
            doc_id = doc_options[selected_doc]
            # Try to delete Qdrant chunks by source metadata
            try:
                from qdrant_client import QdrantClient
                from qdrant_client.models import Filter, FieldCondition, MatchValue
                from config.settings import QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION

                client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
                client.delete(
                    collection_name=QDRANT_COLLECTION,
                    points_selector=Filter(
                        must=[
                            FieldCondition(
                                key="metadata.source",
                                match=MatchValue(value=selected_doc),
                            )
                        ]
                    ),
                )
                st.info(f"Chunks do Qdrant com source='{selected_doc}' removidos.")
            except Exception as e:
                st.warning(
                    f"Nao foi possivel remover chunks do Qdrant: {e}\n\n"
                    "O registro do banco sera removido, mas os chunks podem permanecer no Qdrant."
                )
            delete_document_record(doc_id)
            st.success("Registro removido do banco de dados.")
            st.rerun()
    else:
        st.info("Nenhum documento registrado.")

    st.divider()
    st.markdown("### Upload de documento")
    uploaded_file = st.file_uploader("Selecione um PDF", type=["pdf"])
    if uploaded_file and st.button("Enviar e indexar"):
        with st.spinner("Processando documento..."):
            # Save to temp file
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = tmp.name

            # Insert document record
            doc_id = insert_document(uploaded_file.name, st.session_state["user"]["id"])

            try:
                # Reuse existing ingestor logic
                import fitz
                from langchain_text_splitters import RecursiveCharacterTextSplitter
                from langchain_qdrant import QdrantVectorStore
                from qdrant_client import QdrantClient
                from qdrant_client.models import Distance, VectorParams
                from rag.retriever import get_embeddings
                from config.settings import (
                    QDRANT_HOST, QDRANT_PORT, QDRANT_COLLECTION,
                    CHUNK_SIZE, CHUNK_OVERLAP,
                )

                # Extract text
                doc = fitz.open(tmp_path)
                text = "\n".join(page.get_text() for page in doc)
                doc.close()

                # Chunk
                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=CHUNK_SIZE,
                    chunk_overlap=CHUNK_OVERLAP,
                    separators=["\n\n", "\n", ".", " "],
                )
                chunks = splitter.create_documents(
                    [text],
                    metadatas=[{"source": uploaded_file.name}],
                )

                # Ensure collection exists
                embeddings = get_embeddings()
                client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
                existing = [c.name for c in client.get_collections().collections]
                if QDRANT_COLLECTION not in existing:
                    sample = embeddings.embed_query("test")
                    client.create_collection(
                        collection_name=QDRANT_COLLECTION,
                        vectors_config=VectorParams(size=len(sample), distance=Distance.COSINE),
                    )

                # Index
                QdrantVectorStore.from_documents(
                    documents=chunks,
                    embedding=embeddings,
                    url=f"http://{QDRANT_HOST}:{QDRANT_PORT}",
                    collection_name=QDRANT_COLLECTION,
                )

                update_document_status(doc_id, "indexed", len(chunks))
                st.success(f"Documento indexado: {len(chunks)} chunks.")
            except Exception as e:
                update_document_status(doc_id, f"error: {str(e)[:100]}")
                st.error(f"Erro ao indexar: {e}")
            finally:
                os.unlink(tmp_path)

            st.rerun()
