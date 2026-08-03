import io
import json
import os
import tempfile
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Admin - Assistente SIN", page_icon="🔧", layout="wide")

# ── Access gate ──────────────────────────────────────────────────────────────
if st.session_state.get("user", {}).get("role") != "admin":
    st.error("Acesso restrito a administradores.")
    st.stop()

from auth.auth_service import (
    list_all_users,
    promote_to_admin,
    demote_from_admin,
    delete_user,
    manually_verify_user,
    resend_verification,
    get_chat_logs,
    get_all_documents,
    insert_document,
    update_document_status,
    delete_document_record,
    get_dashboard_stats,
    get_daily_message_counts,
    get_top_users,
    get_session_type_breakdown,
    list_sessions,
    flag_session,
    unflag_session,
)

st.markdown("### Painel Admin — Assistente SIN")
st.divider()

section = st.sidebar.radio(
    "Navegacao",
    ["Visao Geral", "Usuarios", "Sessoes", "Documentos", "Exportar"],
)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: Overview
# ═══════════════════════════════════════════════════════════════════════════════
if section == "Visao Geral":
    stats = get_dashboard_stats()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total de usuarios", stats["total_users"], delta=f"+{stats['new_users_week']} esta semana")
    c2.metric("Verificados", stats["verified"], delta=f"{stats['pending']} pendentes")
    c3.metric("Mensagens hoje", stats["msgs_today"])
    c4.metric("Mensagens esta semana", stats["msgs_week"])

    st.divider()

    # Message volume chart
    st.subheader("Volume de mensagens (14 dias)")
    daily = get_daily_message_counts(14)
    if daily:
        df_daily = pd.DataFrame(daily)
        df_daily["day"] = pd.to_datetime(df_daily["day"])
        df_daily = df_daily.set_index("day")
        st.line_chart(df_daily["count"])
    else:
        st.info("Sem dados de mensagens ainda.")

    st.divider()

    # Top users
    st.subheader("Usuarios mais ativos")
    top = get_top_users(5)
    if top:
        df_top = pd.DataFrame(top)
        df_top.columns = ["Email", "Nome", "Mensagens"]
        st.dataframe(df_top, use_container_width=True, hide_index=True)
    else:
        st.info("Sem dados ainda.")

    st.divider()

    # Session type breakdown
    st.subheader("Tipo de sessao")
    breakdown = get_session_type_breakdown()
    bc1, bc2 = st.columns(2)
    bc1.metric("Simulacao (BESS/STATCOM)", breakdown["simulation"])
    bc2.metric("Conversa livre", breakdown["free"])


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: Users
# ═══════════════════════════════════════════════════════════════════════════════
elif section == "Usuarios":
    search = st.text_input("Buscar por email ou nome", key="user_search")
    users = list_all_users(search=search if search else None)

    if users:
        # Build display dataframe with status badges
        display_rows = []
        for u in users:
            status = "Verificado" if u["verified"] else "Pendente"
            display_rows.append({
                "Nome": u["full_name"] or "",
                "Email": u["email"],
                "Status": status,
                "Role": u["role"],
                "Criado em": u["created_at"],
                "Ultimo login": u["last_login"],
            })
        st.dataframe(pd.DataFrame(display_rows), use_container_width=True, hide_index=True)

        # User actions
        user_options = {f"{u['email']} ({u['full_name'] or ''})": u for u in users}
        selected_label = st.selectbox("Selecionar usuario", list(user_options.keys()))
        selected_user = user_options[selected_label]

        with st.expander(f"Detalhes: {selected_user['email']}", expanded=True):
            st.markdown(f"**Nome:** {selected_user.get('full_name', '-')}")
            st.markdown(f"**Email:** {selected_user['email']}")
            st.markdown(f"**Role:** {selected_user['role']}")
            st.markdown(f"**Verificado:** {'Sim' if selected_user['verified'] else 'Nao'}")
            st.markdown(f"**Criado em:** {selected_user['created_at']}")
            st.markdown(f"**Ultimo login:** {selected_user.get('last_login', '-')}")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if selected_user["role"] != "admin":
                    if st.button("Promover a admin", key="promote"):
                        promote_to_admin(selected_user["id"])
                        st.success("Promovido a admin.")
                        st.rerun()
                else:
                    if selected_user["id"] != st.session_state["user"]["id"]:
                        if st.button("Remover admin", key="demote"):
                            demote_from_admin(selected_user["id"])
                            st.success("Role alterado para user.")
                            st.rerun()

            with col2:
                if not selected_user["verified"]:
                    if st.button("Verificar manualmente", key="manual_verify"):
                        manually_verify_user(selected_user["id"])
                        st.success("Usuario verificado.")
                        st.rerun()

            with col3:
                if not selected_user["verified"]:
                    if st.button("Reenviar email", key="resend_email"):
                        r = resend_verification(selected_user["email"])
                        if r["ok"]:
                            st.success("Email reenviado.")
                        else:
                            st.error(r.get("error", "Erro ao reenviar."))

            with col4:
                if selected_user["id"] != st.session_state["user"]["id"]:
                    confirm = st.checkbox("Confirmo exclusao", key="del_confirm")
                    if confirm and st.button("Excluir usuario", key="del_user"):
                        delete_user(selected_user["id"])
                        st.success("Usuario excluido.")
                        st.rerun()

            # User's sessions
            st.divider()
            st.markdown("**Sessoes deste usuario:**")
            user_sessions = list_sessions(user_id=selected_user["id"])
            if user_sessions:
                for sess in user_sessions[:10]:
                    duration = ""
                    if sess.get("started_at") and sess.get("last_message_at"):
                        try:
                            d = sess["last_message_at"] - sess["started_at"]
                            mins = int(d.total_seconds() / 60)
                            duration = f"{mins} min"
                        except Exception:
                            pass
                    flag_icon = " 🚩" if sess.get("flagged") else ""
                    st.caption(
                        f"{sess['started_at']} | {sess.get('message_count', 0)} msgs | "
                        f"{sess.get('sim_type') or 'Livre'} | {duration}{flag_icon}"
                    )
            else:
                st.caption("Nenhuma sessao registrada.")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: Sessions
# ═══════════════════════════════════════════════════════════════════════════════
elif section == "Sessoes":
    col_d1, col_d2, col_user, col_type, col_flag = st.columns(5)
    with col_d1:
        s_start = st.date_input("Data inicio", value=datetime.now().date() - timedelta(days=7), key="sess_start")
    with col_d2:
        s_end = st.date_input("Data fim", value=datetime.now().date() + timedelta(days=1), key="sess_end")
    with col_user:
        all_users = list_all_users()
        user_opts = {"Todos": None}
        user_opts.update({u["email"]: u["id"] for u in all_users})
        sel_user = st.selectbox("Usuario", list(user_opts.keys()), key="sess_user")
    with col_type:
        sim_type_opt = st.selectbox("Tipo", ["Todos", "BESS", "STATCOM", "Conversa livre"], key="sess_type")
    with col_flag:
        flagged_only = st.checkbox("Apenas marcadas", key="sess_flagged")

    sessions = list_sessions(
        user_id=user_opts[sel_user],
        start_date=datetime.combine(s_start, datetime.min.time()),
        end_date=datetime.combine(s_end, datetime.min.time()),
        sim_type=sim_type_opt if sim_type_opt != "Todos" else None,
        flagged_only=flagged_only,
    )

    if sessions:
        # Summary table
        table_rows = []
        for s in sessions:
            duration = ""
            if s.get("started_at") and s.get("last_message_at"):
                try:
                    d = s["last_message_at"] - s["started_at"]
                    mins = int(d.total_seconds() / 60)
                    duration = f"{mins} min"
                except Exception:
                    pass
            table_rows.append({
                "Usuario": s.get("email", ""),
                "Inicio": s["started_at"],
                "Duracao": duration,
                "Mensagens": s.get("message_count", 0),
                "Tipo": s.get("sim_type") or "Livre",
                "Passo final": s.get("final_sim_step") or "-",
                "Marcada": "🚩" if s.get("flagged") else "",
            })
        st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

        # Session detail expanders
        sess_options = {
            f"{s['started_at']} - {s.get('email', '')} ({s.get('message_count', 0)} msgs)": s
            for s in sessions
        }
        sel_sess_label = st.selectbox("Selecionar sessao para detalhes", list(sess_options.keys()))
        sel_sess = sess_options[sel_sess_label]

        with st.expander("Transcricao da sessao", expanded=True):
            # Fetch messages for this session
            logs = get_chat_logs(user_id=sel_sess["user_id"])
            sess_logs = [l for l in logs if l["session_id"] == sel_sess["id"]]

            if sess_logs:
                for entry in sess_logs:
                    if entry["role"] == "user":
                        st.markdown(
                            f'<div style="background:#1a1a2e;padding:10px 14px;border-radius:12px;'
                            f'margin:4px 0;border-left:3px solid #F97316;">'
                            f'<b>👤 {entry.get("full_name", "Usuario")}</b><br>{entry["message"][:1000]}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f'<div style="background:#16213e;padding:10px 14px;border-radius:12px;'
                            f'margin:4px 0;border-left:3px solid #4CAF50;">'
                            f'<b>🤖 Assistente</b> <span style="color:#888;">({entry.get("sim_step", "")})</span>'
                            f'<br>{entry["message"][:1000]}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    st.caption(str(entry["created_at"]))
            else:
                st.info("Nenhuma mensagem encontrada para esta sessao.")

        # Flag/unflag
        if sel_sess.get("flagged"):
            st.info(f"🚩 Marcada: {sel_sess.get('flag_note', '')}")
            if st.button("Remover marcacao"):
                unflag_session(sel_sess["id"])
                st.success("Marcacao removida.")
                st.rerun()
        else:
            flag_note = st.text_input("Nota para marcacao", key="flag_note")
            if st.button("🚩 Marcar sessao"):
                flag_session(sel_sess["id"], flag_note)
                st.success("Sessao marcada.")
                st.rerun()
    else:
        st.info("Nenhuma sessao encontrada para o periodo selecionado.")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: Documents
# ═══════════════════════════════════════════════════════════════════════════════
elif section == "Documentos":
    documents = get_all_documents()
    if documents:
        df_docs = pd.DataFrame(documents)
        st.dataframe(
            df_docs[["filename", "chunk_count", "qdrant_status", "uploaded_at", "uploaded_by_email"]],
            use_container_width=True,
            hide_index=True,
        )

        doc_options = {d["filename"]: d["id"] for d in documents}
        selected_doc = st.selectbox("Selecionar documento para remover", list(doc_options.keys()))
        if st.button("Remover documento"):
            doc_id = doc_options[selected_doc]
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
    st.subheader("Upload de documento")
    uploaded_file = st.file_uploader("Selecione um PDF", type=["pdf"])
    if uploaded_file and st.button("Enviar e indexar"):
        with st.spinner("Processando documento..."):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = tmp.name

            doc_id = insert_document(uploaded_file.name, st.session_state["user"]["id"])

            try:
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

                doc = fitz.open(tmp_path)
                text = "\n".join(page.get_text() for page in doc)
                doc.close()

                splitter = RecursiveCharacterTextSplitter(
                    chunk_size=CHUNK_SIZE,
                    chunk_overlap=CHUNK_OVERLAP,
                    separators=["\n\n", "\n", ".", " "],
                )
                chunks = splitter.create_documents(
                    [text],
                    metadatas=[{"source": uploaded_file.name}],
                )

                embeddings = get_embeddings()
                client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
                existing = [c.name for c in client.get_collections().collections]
                if QDRANT_COLLECTION not in existing:
                    sample = embeddings.embed_query("test")
                    client.create_collection(
                        collection_name=QDRANT_COLLECTION,
                        vectors_config=VectorParams(size=len(sample), distance=Distance.COSINE),
                    )

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


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: Export
# ═══════════════════════════════════════════════════════════════════════════════
elif section == "Exportar":
    st.subheader("Exportar dados")

    # Reuse session filters
    col_d1, col_d2, col_user, col_type = st.columns(4)
    with col_d1:
        e_start = st.date_input("Data inicio", value=datetime.now().date() - timedelta(days=30), key="exp_start")
    with col_d2:
        e_end = st.date_input("Data fim", value=datetime.now().date() + timedelta(days=1), key="exp_end")
    with col_user:
        all_users_exp = list_all_users()
        user_opts_exp = {"Todos": None}
        user_opts_exp.update({u["email"]: u["id"] for u in all_users_exp})
        sel_user_exp = st.selectbox("Usuario", list(user_opts_exp.keys()), key="exp_user")
    with col_type:
        sim_type_exp = st.selectbox("Tipo", ["Todos", "BESS", "STATCOM", "Conversa livre"], key="exp_type")

    start_dt = datetime.combine(e_start, datetime.min.time())
    end_dt = datetime.combine(e_end, datetime.min.time())
    filter_user_id = user_opts_exp[sel_user_exp]

    st.divider()

    # Export 1: All messages CSV
    col_e1, col_e2, col_e3 = st.columns(3)

    with col_e1:
        if st.button("Gerar CSV de mensagens"):
            logs = get_chat_logs(start_date=start_dt, end_date=end_dt, user_id=filter_user_id)
            if logs:
                df = pd.DataFrame(logs)
                csv = df.to_csv(index=False)
                st.download_button(
                    "Baixar mensagens (CSV)",
                    data=csv,
                    file_name="chat_logs.csv",
                    mime="text/csv",
                )
            else:
                st.info("Sem dados para exportar.")

    with col_e2:
        if st.button("Gerar CSV de sessoes"):
            sessions_exp = list_sessions(
                user_id=filter_user_id,
                start_date=start_dt,
                end_date=end_dt,
                sim_type=sim_type_exp if sim_type_exp != "Todos" else None,
            )
            if sessions_exp:
                rows = []
                for s in sessions_exp:
                    duration_min = ""
                    if s.get("started_at") and s.get("last_message_at"):
                        try:
                            d = s["last_message_at"] - s["started_at"]
                            duration_min = int(d.total_seconds() / 60)
                        except Exception:
                            pass
                    rows.append({
                        "session_id": s["id"],
                        "user_email": s.get("email", ""),
                        "started_at": s["started_at"],
                        "last_message_at": s.get("last_message_at"),
                        "duration_min": duration_min,
                        "message_count": s.get("message_count", 0),
                        "sim_type": s.get("sim_type") or "Livre",
                        "final_step": s.get("final_sim_step") or "",
                        "flagged": s.get("flagged", False),
                        "flag_note": s.get("flag_note") or "",
                    })
                df = pd.DataFrame(rows)
                csv = df.to_csv(index=False)
                st.download_button(
                    "Baixar sessoes (CSV)",
                    data=csv,
                    file_name="sessions.csv",
                    mime="text/csv",
                )
            else:
                st.info("Sem dados para exportar.")

    with col_e3:
        if st.button("Gerar JSON completo"):
            sessions_exp = list_sessions(
                user_id=filter_user_id,
                start_date=start_dt,
                end_date=end_dt,
                sim_type=sim_type_exp if sim_type_exp != "Todos" else None,
            )
            all_logs = get_chat_logs(start_date=start_dt, end_date=end_dt, user_id=filter_user_id)

            # Group logs by session_id
            logs_by_session = {}
            for l in all_logs:
                logs_by_session.setdefault(l["session_id"], []).append(l)

            export_data = []
            for s in sessions_exp:
                sess_msgs = logs_by_session.get(s["id"], [])
                export_data.append({
                    "session": {
                        "id": s["id"],
                        "user_email": s.get("email", ""),
                        "user_name": s.get("full_name", ""),
                        "started_at": str(s["started_at"]),
                        "last_message_at": str(s.get("last_message_at")),
                        "message_count": s.get("message_count", 0),
                        "sim_type": s.get("sim_type"),
                        "final_sim_step": s.get("final_sim_step"),
                        "flagged": s.get("flagged", False),
                        "flag_note": s.get("flag_note"),
                    },
                    "messages": [
                        {
                            "role": m["role"],
                            "message": m["message"],
                            "sim_step": m.get("sim_step"),
                            "created_at": str(m["created_at"]),
                        }
                        for m in sess_msgs
                    ],
                })

            if export_data:
                json_str = json.dumps(export_data, ensure_ascii=False, indent=2)
                st.download_button(
                    "Baixar dados completos (JSON)",
                    data=json_str,
                    file_name="export_completo.json",
                    mime="application/json",
                )
            else:
                st.info("Sem dados para exportar.")
