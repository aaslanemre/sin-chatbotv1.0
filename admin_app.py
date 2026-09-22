# Admin panel — standalone Streamlit app
# Run separately from the user app:
#
#   streamlit run app.py       --server.port 8501   # user app
#   streamlit run admin_app.py --server.port 8503   # admin app

import streamlit as st
from auth.db import init_db
from auth.auth_service import signup_admin, login

st.set_page_config(
    page_title="Admin — Assistente SIN",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Initialize database ──────────────────────────────────────────────────────
if "db_initialized" not in st.session_state:
    try:
        init_db()
        st.session_state.db_initialized = True
    except Exception as e:
        st.session_state.db_initialized = False
        st.session_state.db_init_error = str(e)

# ── Admin authentication gate ────────────────────────────────────────────────
if "user" not in st.session_state:
    st.markdown("### Painel Admin — Assistente SIN")
    if not st.session_state.get("db_initialized"):
        st.error(
            f"Banco de dados indisponivel: `{st.session_state.get('db_init_error', 'desconhecido')}`\n\n"
            "Verifique se o PostgreSQL esta rodando: `docker-compose up -d`"
        )
        st.stop()

    tab_login, tab_signup = st.tabs(["Entrar", "Criar conta admin"])
    with tab_login:
        with st.form("admin_login_form"):
            email = st.text_input("Email")
            password = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar")
            if submitted:
                user = login(email, password)
                if user and user.get("role") == "admin":
                    st.session_state["user"] = user
                    st.rerun()
                elif user:
                    st.error("Esta conta nao tem permissao de administrador.")
                else:
                    st.error("Email ou senha incorretos.")

    with tab_signup:
        with st.form("admin_signup_form"):
            s_email = st.text_input("Email", key="s_email")
            s_name = st.text_input("Nome completo", key="s_name")
            s_pass = st.text_input("Senha", type="password", key="s_pass")
            s_pass2 = st.text_input("Confirmar senha", type="password", key="s_pass2")
            s_code = st.text_input("Codigo de acesso admin", type="password", key="s_code")
            s_submitted = st.form_submit_button("Criar conta admin")
            if s_submitted:
                if s_pass != s_pass2:
                    st.error("As senhas nao coincidem.")
                elif len(s_pass) < 6:
                    st.error("A senha deve ter pelo menos 6 caracteres.")
                else:
                    result = signup_admin(s_email, s_pass, s_name, s_code)
                    if result["ok"]:
                        st.session_state["user"] = result["user"]
                        st.rerun()
                    else:
                        st.error(result["error"])
    st.stop()

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    _user = st.session_state["user"]
    st.markdown(f"**{_user.get('full_name', '')}** ({_user.get('email', '')})")
    if st.button("Sair", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.divider()
    st.caption("v6.1")

# ── Render admin panel ───────────────────────────────────────────────────────
from admin.panel import render_admin_panel
render_admin_panel()
