import html
import io
import json
import os
import tempfile
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from agents.session_analysis import (
    FEEDBACK_CATEGORIES,
    FEEDBACK_STATUSES,
    OUTCOME_LABELS,
    aggregate_by_step,
    build_markdown_report,
    filter_session_summaries,
    match_feedback_to_messages,
    summarize_session,
    timeline_text,
)


SECTIONS = ["Visão Geral", "Usuários", "Sessões", "Feedback", "Documentos", "Exportar"]
STATUS_LABELS = {"novo": "🆕 novo", "em_analise": "🔎 em análise",
                 "resolvido": "✅ resolvido", "descartado": "🗑️ descartado"}
_CATEGORY_KEYS = list(FEEDBACK_CATEGORIES)


def _cat_label(key):
    return FEEDBACK_CATEGORIES.get(key, "—") if key else "—"


def _duration_min(s):
    if s.get("started_at") and s.get("last_message_at"):
        try:
            return int((s["last_message_at"] - s["started_at"]).total_seconds() / 60)
        except Exception:
            pass
    return ""


def _group(rows, key):
    out = {}
    for r in rows:
        out.setdefault(r.get(key), []).append(r)
    return out


def _load_session_summaries(sessions, all_feedback=None):
    """Summaries (with analysis) for the given sessions, plus per-session logs/feedback."""
    from auth.auth_service import get_chat_logs_for_sessions, list_feedback
    logs_by = _group(get_chat_logs_for_sessions([s["id"] for s in sessions]), "session_id")
    fb_by = _group(all_feedback if all_feedback is not None else list_feedback(), "session_id")
    summaries = [summarize_session(s, logs_by.get(s["id"], []), fb_by.get(s["id"], []))
                 for s in sessions]
    return summaries, logs_by, fb_by


def _session_table_row(s, summ):
    return {
        "Usuario": s.get("email", ""),
        "Inicio": s["started_at"],
        "Duracao": _duration_min(s),
        "Mensagens": s.get("message_count", 0),
        "Tipo": s.get("sim_type") or "Livre",
        "Ultimo passo": summ["last_step"],
        "Desfecho": OUTCOME_LABELS.get(summ["outcome"], "-"),
        "Feedback": summ["feedback_count"],
        "👎": ("🚩 " if summ["thumbs_down_count"] else "") + str(summ["thumbs_down_count"]),
        "Sinais": " · ".join(summ["badges"]),
        "Marcada": "🚩" if s.get("flagged") else "",
    }


def _bubble(role, name, step, text):
    color, border = ("#1a1a2e", "#F97316") if role == "user" else ("#16213e", "#4CAF50")
    icon = "👤" if role == "user" else "🤖"
    step_html = f' <span style="color:#888;">({html.escape(step)})</span>' if step else ""
    body = html.escape(text[:1000]).replace("\n", "<br>")
    st.markdown(
        f'<div style="background:{color};padding:10px 14px;border-radius:12px;'
        f'margin:4px 0;border-left:3px solid {border};">'
        f'<b>{icon} {html.escape(name)}</b>{step_html}<br>{body}</div>',
        unsafe_allow_html=True,
    )


def _feedback_card(fb, key_prefix, update_fn):
    """Compact card under an assistant bubble: details + status change."""
    icon = "👍" if fb.get("rating") == "up" else "👎"
    with st.container(border=True):
        st.markdown(
            f"{icon} **{_cat_label(fb.get('category'))}** · "
            f"{STATUS_LABELS.get(fb.get('status'), fb.get('status'))} · "
            f"{fb.get('created_at')}"
        )
        if fb.get("comment"):
            st.markdown(f"> {fb['comment']}")
        if fb.get("admin_note"):
            st.caption(f"Nota do admin: {fb['admin_note']}")
        c1, c2 = st.columns([3, 1])
        cur = fb.get("status") if fb.get("status") in FEEDBACK_STATUSES else "novo"
        new_status = c1.selectbox("Status", FEEDBACK_STATUSES,
                                  index=FEEDBACK_STATUSES.index(cur),
                                  format_func=lambda x: STATUS_LABELS[x],
                                  key=f"{key_prefix}_st_{fb['id']}",
                                  label_visibility="collapsed")
        if c2.button("Salvar", key=f"{key_prefix}_sv_{fb['id']}"):
            update_fn(fb["id"], new_status, fb.get("admin_note"))
            st.success("Status atualizado.")
            st.rerun()


def _go_to_session(session_id):
    """on_click callback: open a session in the Sessões section."""
    st.session_state["admin_section"] = "Sessões"
    st.session_state["sess_focus"] = session_id


def _render_transcript(sess, messages, feedback, update_fn):
    """Step timeline + chat bubbles with feedback cards under assistant messages."""
    if not messages:
        st.info("Nenhuma mensagem encontrada para esta sessão.")
        return
    summ = summarize_session(sess, messages, feedback)
    st.markdown(f"**Linha do tempo:** {timeline_text(summ['analysis'])}")
    matched = match_feedback_to_messages(messages, feedback)
    for entry, fbs in zip(messages, matched):
        who = (entry.get("full_name") or sess.get("full_name") or "Usuario") \
            if entry["role"] == "user" else "Assistente"
        _bubble(entry["role"], who, entry.get("sim_step"), entry["message"])
        st.caption(f"{entry.get('created_at')} · passo: {entry.get('sim_step') or '-'}")
        for fb in fbs:
            _feedback_card(fb, "tr", update_fn)


def _filters_summary(start, end, user_label, sim_type):
    f = {"Período": f"{start} a {end}"}
    f["Usuário"] = user_label
    f["Tipo"] = sim_type
    return f


def render_admin_panel():
    """Render the admin panel UI. Caller must ensure admin auth is already done."""
    from auth.auth_service import (
        list_all_users,
        promote_to_admin,
        demote_from_admin,
        delete_user,
        manually_verify_user,
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
        get_chat_logs_for_sessions,
        list_feedback,
        update_feedback_status,
        feedback_stats,
    )

    st.markdown("### Painel Admin — Assistente SIN")
    st.divider()

    section = st.sidebar.radio(
        "Navegacao",
        SECTIONS,
        key="admin_section",
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 1: Overview
    # ═══════════════════════════════════════════════════════════════════════════
    if section == "Visão Geral":
        stats = get_dashboard_stats()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total de usuarios", stats["total_users"], delta=f"+{stats['new_users_week']} esta semana")
        c2.metric("Verificados", stats["verified"], delta=f"{stats['pending']} pendentes")
        c3.metric("Mensagens hoje", stats["msgs_today"])
        c4.metric("Mensagens esta semana", stats["msgs_week"])

        st.divider()

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

        st.subheader("Usuarios mais ativos")
        top = get_top_users(5)
        if top:
            df_top = pd.DataFrame(top)
            df_top.columns = ["Email", "Nome", "Mensagens"]
            st.dataframe(df_top, use_container_width=True, hide_index=True)
        else:
            st.info("Sem dados ainda.")

        st.divider()

        st.subheader("Tipo de sessao")
        breakdown = get_session_type_breakdown()
        bc1, bc2 = st.columns(2)
        bc1.metric("Simulacao (BESS/STATCOM)", breakdown["simulation"])
        bc2.metric("Conversa livre", breakdown["free"])

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 2: Users
    # ═══════════════════════════════════════════════════════════════════════════
    elif section == "Usuários":
        search = st.text_input("Buscar por email ou nome", key="user_search")
        users = list_all_users(search=search if search else None)

        if users:
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
                    pass

                with col4:
                    if selected_user["id"] != st.session_state["user"]["id"]:
                        confirm = st.checkbox("Confirmo exclusao", key="del_confirm")
                        if confirm and st.button("Excluir usuario", key="del_user"):
                            delete_user(selected_user["id"])
                            st.success("Usuario excluido.")
                            st.rerun()

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

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 3: Sessions
    # ═══════════════════════════════════════════════════════════════════════════
    elif section == "Sessões":
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
            sim_type_opt = st.selectbox("Tipo", ["Todos", "BESS", "STATCOM", "NETWORK", "Conversa livre"], key="sess_type")
        with col_flag:
            flagged_only = st.checkbox("Apenas marcadas", key="sess_flagged")

        cf1, cf2, cf3, cf4 = st.columns(4)
        only_feedback = cf1.checkbox("Só com feedback", key="sess_only_fb")
        only_down = cf2.checkbox("Só com 👎", key="sess_only_down")
        only_stuck = cf3.checkbox("Só com sinais de travamento", key="sess_only_stuck")
        only_abandoned = cf4.checkbox("Só abandonadas", key="sess_only_aband")

        sessions = list_sessions(
            user_id=user_opts[sel_user],
            start_date=datetime.combine(s_start, datetime.min.time()),
            end_date=datetime.combine(s_end, datetime.min.time()),
            sim_type=sim_type_opt if sim_type_opt != "Todos" else None,
            flagged_only=flagged_only,
        )

        tab_list, tab_stuck = st.tabs(["Sessões", "Onde os testers travam"])

        if not sessions:
            with tab_list:
                st.info("Nenhuma sessao encontrada para o periodo selecionado.")
            with tab_stuck:
                st.info("Sem dados para o período selecionado.")
        else:
            summaries, logs_by, fb_by = _load_session_summaries(sessions)
            sess_by_id = {s["id"]: s for s in sessions}

            # ── D) Where testers get stuck (aggregated over date/user/type filters) ──
            with tab_stuck:
                all_fb = [f for fl in fb_by.values() for f in fl]
                agg = aggregate_by_step(summaries, all_fb)
                if agg:
                    df_agg = pd.DataFrame(agg)
                    df_agg["Passo"] = df_agg["sim_type"] + " " + df_agg["sim_step"]
                    df_agg = df_agg.rename(columns={
                        "down": "👎", "sessions_not_advancing": "Sessões sem avançar",
                        "help_back": "Ajuda/voltar", "abandoned": "Abandonos",
                        "score": "Pontuação",
                    })
                    cols = ["👎", "Sessões sem avançar", "Ajuda/voltar", "Abandonos"]
                    st.caption("Ordenado pelo passo mais problemático (soma dos sinais).")
                    st.bar_chart(df_agg.set_index("Passo")[cols])
                    st.dataframe(df_agg[["Passo"] + cols + ["Pontuação"]],
                                 use_container_width=True, hide_index=True)
                else:
                    st.info("Nenhum sinal de travamento no período.")

            # ── B) Session list ──
            with tab_list:
                shown = filter_session_summaries(
                    summaries, only_feedback, only_down, only_stuck, only_abandoned)
                if not shown:
                    st.info("Nenhuma sessão atende aos filtros selecionados.")
                else:
                    st.dataframe(
                        pd.DataFrame([_session_table_row(sess_by_id[x["session_id"]], x) for x in shown]),
                        use_container_width=True, hide_index=True,
                    )

                    sess_options = {
                        f"{sess_by_id[x['session_id']]['started_at']} - "
                        f"{sess_by_id[x['session_id']].get('email', '')} "
                        f"({sess_by_id[x['session_id']].get('message_count', 0)} msgs)": x["session_id"]
                        for x in shown
                    }
                    labels = list(sess_options)
                    focus = st.session_state.get("sess_focus")
                    focus_label = next((l for l, sid in sess_options.items() if sid == focus), None)
                    default_idx = labels.index(focus_label) if focus_label else 0
                    if focus and not focus_label:
                        st.info("A sessão solicitada não está no período/filtros atuais — ajuste os filtros.")
                    sel_label = st.selectbox(
                        "Selecionar sessao para detalhes", labels, index=default_idx,
                        key=f"sess_select_{focus or 'none'}")
                    sel_sess = sess_by_id[sess_options[sel_label]]

                    # ── C) Detail ──
                    with st.expander("Transcricao da sessao", expanded=True):
                        sess_logs = logs_by.get(sel_sess["id"], [])
                        for l in sess_logs:
                            l.setdefault("full_name", sel_sess.get("full_name"))
                        _render_transcript(sel_sess, sess_logs, fb_by.get(sel_sess["id"], []),
                                           update_feedback_status)

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

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 3b: Feedback
    # ═══════════════════════════════════════════════════════════════════════════
    elif section == "Feedback":
        stats = feedback_stats()
        every = list_feedback()

        by_status, by_rating = stats["by_status"], stats["by_rating"]
        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Total", len(every))
        m2.metric("Novos", by_status.get("novo", 0))
        m3.metric("Em análise", by_status.get("em_analise", 0))
        m4.metric("Resolvidos", by_status.get("resolvido", 0))
        m5.metric("👍 vs 👎", f"{by_rating.get('up', 0)} vs {by_rating.get('down', 0)}")

        st.divider()
        fa, fb_, fc, fd = st.columns(4)
        f_status = fa.selectbox("Status", ["Todos"] + FEEDBACK_STATUSES, key="fb_f_status")
        f_cat = fb_.selectbox("Categoria", ["Todas"] + _CATEGORY_KEYS,
                              format_func=lambda k: k if k == "Todas" else _cat_label(k), key="fb_f_cat")
        f_type = fc.selectbox("Tipo", ["Todos", "BESS", "STATCOM", "NETWORK", "Conversa livre"], key="fb_f_type")
        f_rating = fd.selectbox("Avaliação", ["Todas", "up", "down"],
                                format_func=lambda k: {"up": "👍", "down": "👎"}.get(k, k), key="fb_f_rating")
        fe, ff, fg, fh = st.columns(4)
        steps_avail = sorted({f.get("sim_step_after") for f in every if f.get("sim_step_after")})
        f_step = fe.selectbox("Passo", ["Todos"] + steps_avail, key="fb_f_step")
        versions = sorted(stats["by_version"])
        f_ver = ff.selectbox("Versão", ["Todas"] + versions, key="fb_f_ver")
        fb_users = {"Todos": None}
        fb_users.update({u["email"]: u["id"] for u in list_all_users()})
        f_user = fg.selectbox("Usuário", list(fb_users), key="fb_f_user")
        with fh:
            f_start = st.date_input("De", value=datetime.now().date() - timedelta(days=30), key="fb_f_start")
            f_end = st.date_input("Até", value=datetime.now().date() + timedelta(days=1), key="fb_f_end")

        items = list_feedback(
            status=None if f_status == "Todos" else f_status,
            category=None if f_cat == "Todas" else f_cat,
            sim_type=None if f_type == "Todos" else f_type,
            sim_step=None if f_step == "Todos" else f_step,
            app_version=None if f_ver == "Todas" else f_ver,
            rating=None if f_rating == "Todas" else f_rating,
            user=fb_users[f_user],
            start_date=datetime.combine(f_start, datetime.min.time()),
            end_date=datetime.combine(f_end, datetime.min.time()),
        )

        if not items:
            st.info("Nenhum feedback para os filtros selecionados.")
        else:
            st.dataframe(pd.DataFrame([{
                "Quando": f["created_at"],
                "Usuário": f.get("email", ""),
                "Avaliação": "👍" if f["rating"] == "up" else "👎",
                "Categoria": _cat_label(f.get("category")),
                "Tipo": f.get("sim_type") or "Livre",
                "Passo": f.get("sim_step_after") or "-",
                "Versão": f.get("app_version") or "-",
                "Status": STATUS_LABELS.get(f["status"], f["status"]),
                "Comentário": (f.get("comment") or "")[:80],
            } for f in items]), use_container_width=True, hide_index=True)

            opts = {
                f"{f['created_at']} · {'👍' if f['rating'] == 'up' else '👎'} · "
                f"{f.get('email', '')} · {f.get('sim_step_after') or '-'}": f
                for f in items
            }
            sel = opts[st.selectbox("Selecionar feedback", list(opts), key="fb_select")]
            with st.container(border=True):
                st.markdown(f"**Comentário do tester:** {sel.get('comment') or '(sem comentário)'}")
                st.markdown(f"**Mensagem do usuário:** {sel.get('user_message') or '-'}")
                st.markdown("**Mensagem do assistente:**")
                st.markdown(sel.get("assistant_message") or "-")
                st.caption(
                    f"Passo antes: {sel.get('sim_step_before') or '-'} · "
                    f"depois: {sel.get('sim_step_after') or '-'} · versão {sel.get('app_version') or '-'} · "
                    f"{sel.get('full_name') or ''} ({sel.get('email', '')}) · {sel['created_at']}"
                )
                st.button("Ver sessão completa", key=f"fb_open_{sel['id']}",
                          on_click=_go_to_session, args=(sel["session_id"],))
                cur = sel["status"] if sel["status"] in FEEDBACK_STATUSES else "novo"
                new_status = st.selectbox("Status", FEEDBACK_STATUSES,
                                          index=FEEDBACK_STATUSES.index(cur),
                                          format_func=lambda x: STATUS_LABELS[x],
                                          key=f"fb_status_{sel['id']}")
                note = st.text_area("Nota do admin", value=sel.get("admin_note") or "",
                                    key=f"fb_note_{sel['id']}")
                if st.button("Salvar", key=f"fb_save_{sel['id']}"):
                    update_feedback_status(sel["id"], new_status, note)
                    st.success("Feedback atualizado.")
                    st.rerun()

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 4: Documents
    # ═══════════════════════════════════════════════════════════════════════════
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

    # ═══════════════════════════════════════════════════════════════════════════
    # SECTION 5: Export
    # ═══════════════════════════════════════════════════════════════════════════
    elif section == "Exportar":
        st.subheader("Exportar dados")

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
            sim_type_exp = st.selectbox("Tipo", ["Todos", "BESS", "STATCOM", "NETWORK", "Conversa livre"], key="exp_type")

        start_dt = datetime.combine(e_start, datetime.min.time())
        end_dt = datetime.combine(e_end, datetime.min.time())
        filter_user_id = user_opts_exp[sel_user_exp]
        filter_type = sim_type_exp if sim_type_exp != "Todos" else None

        def _scoped_feedback():
            return list_feedback(user=filter_user_id, sim_type=filter_type,
                                 start_date=start_dt, end_date=end_dt)

        def _scoped_sessions():
            return list_sessions(user_id=filter_user_id, start_date=start_dt,
                                 end_date=end_dt, sim_type=filter_type)

        st.divider()

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
                sessions_exp = _scoped_sessions()
                if sessions_exp:
                    summaries_exp, _, _ = _load_session_summaries(sessions_exp)
                    summ_by_id = {x["session_id"]: x for x in summaries_exp}
                    rows = []
                    for s in sessions_exp:
                        sm = summ_by_id[s["id"]]
                        rows.append({
                            "session_id": s["id"],
                            "user_email": s.get("email", ""),
                            "started_at": s["started_at"],
                            "last_message_at": s.get("last_message_at"),
                            "duration_min": _duration_min(s),
                            "message_count": s.get("message_count", 0),
                            "sim_type": s.get("sim_type") or "Livre",
                            "final_step": s.get("final_sim_step") or "",
                            "flagged": s.get("flagged", False),
                            "flag_note": s.get("flag_note") or "",
                            "feedback_count": sm["feedback_count"],
                            "thumbs_down_count": sm["thumbs_down_count"],
                            "last_step": sm["last_step"],
                            "outcome": sm["outcome"] or "",
                            "stuck_steps": ";".join(sm["stuck_steps"]),
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
                sessions_exp = _scoped_sessions()
                all_logs = get_chat_logs(start_date=start_dt, end_date=end_dt, user_id=filter_user_id)

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
                                "message_id": m.get("message_id"),
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

        st.divider()
        st.markdown("**Feedback e travamentos**")
        col_f1, col_f2 = st.columns(2)

        with col_f1:
            if st.button("Gerar CSV de feedback"):
                fb_rows = _scoped_feedback()
                if fb_rows:
                    df = pd.DataFrame([{
                        "feedback_id": f["id"], "created_at": f["created_at"],
                        "user_email": f.get("email", ""), "session_id": f["session_id"],
                        "message_id": f.get("message_id"), "rating": f["rating"],
                        "category": f.get("category") or "", "comment": f.get("comment") or "",
                        "sim_type": f.get("sim_type") or "",
                        "sim_step_before": f.get("sim_step_before") or "",
                        "sim_step_after": f.get("sim_step_after") or "",
                        "app_version": f.get("app_version") or "", "status": f["status"],
                        "admin_note": f.get("admin_note") or "",
                        "user_message": f.get("user_message") or "",
                        "assistant_message": f.get("assistant_message") or "",
                    } for f in fb_rows])
                    st.download_button("Baixar feedback (CSV)", data=df.to_csv(index=False),
                                       file_name="feedback.csv", mime="text/csv")
                else:
                    st.info("Sem feedback para exportar.")

        with col_f2:
            if st.button("Gerar relatório Markdown por passo"):
                sessions_exp = _scoped_sessions()
                fb_rows = _scoped_feedback()
                summaries_exp, _, _ = _load_session_summaries(sessions_exp, all_feedback=fb_rows)
                report = build_markdown_report(
                    summaries_exp, fb_rows,
                    filters=_filters_summary(
                        e_start, e_end,
                        "todos" if filter_user_id is None else "um usuário específico",
                        sim_type_exp),
                )
                st.download_button("Baixar relatório (.md)", data=report,
                                   file_name="relatorio_travamentos.md", mime="text/markdown")
                with st.expander("Pré-visualizar relatório"):
                    st.code(report, language="markdown")
