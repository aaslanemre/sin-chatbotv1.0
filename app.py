import streamlit as st
from utils.pwf_handler import save_pwf, preview_pwf

st.set_page_config(
    page_title="Assistente SIN",
    page_icon="⚡",
    layout="centered",
)

# ── Session state ─────────────────────────────────────────────────────────────
if "chain" not in st.session_state:
    st.session_state.chain = None
    st.session_state.chain_error = None

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "Olá! Sou seu assistente especialista no Sistema Interligado Nacional. "
                "Posso ajudá-lo a conduzir estudos de localização de BESS, STATCOM, "
                "HVDC, fluxo de potência, estabilidade e muito mais.\n\n"
                "Como posso ajudá-lo hoje?"
            ),
        }
    ]

if "pwf_files" not in st.session_state:
    st.session_state.pwf_files = []


def _load_chain():
    try:
        from rag.chain import build_chain
        st.session_state.chain = build_chain()
        st.session_state.chain_error = None
    except Exception as e:
        st.session_state.chain = None
        st.session_state.chain_error = str(e)


if st.session_state.chain is None and st.session_state.chain_error is None:
    with st.spinner("Carregando modelos e base de conhecimento..."):
        _load_chain()

# ── Top bar ───────────────────────────────────────────────────────────────────
col1, col2 = st.columns([6, 1])
with col1:
    st.markdown("### ⚡ Assistente SIN")
    st.caption("Planejamento e operação do Sistema Interligado Nacional")
with col2:
    if st.button("🗑️ Limpar", help="Limpar conversa"):
        st.session_state.messages = [st.session_state.messages[0]]
        st.session_state.pwf_files = []
        st.session_state.chain = None
        st.session_state.chain_error = None
        st.rerun()

st.divider()

# ── Connection error banner ───────────────────────────────────────────────────
if st.session_state.chain_error:
    st.error(
        "**Não foi possível conectar ao Qdrant ou Ollama.**\n\n"
        f"Detalhes: `{st.session_state.chain_error}`\n\n"
        "Verifique se:\n"
        "- Qdrant está rodando: `docker-compose up -d`\n"
        "- Ollama está rodando: `ollama serve`\n"
        "- Modelos baixados: `ollama pull llama3.2 && ollama pull nomic-embed-text`"
    )
    if st.button("🔄 Tentar reconectar"):
        st.session_state.chain_error = None
        st.rerun()

# ── Chat messages ─────────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sources" in msg and msg["sources"]:
            with st.expander("📄 Fontes consultadas"):
                for src in msg["sources"]:
                    st.caption(f"• {src}")

# ── PWF chips (above input) ───────────────────────────────────────────────────
if st.session_state.pwf_files:
    chip_cols = st.columns(len(st.session_state.pwf_files) + 1)
    for i, pwf in enumerate(st.session_state.pwf_files):
        with chip_cols[i]:
            with st.expander(f"📎 {pwf['name']}"):
                st.code(preview_pwf(pwf["path"]), language="text")
                if st.button("Remover", key=f"remove_{i}"):
                    st.session_state.pwf_files.pop(i)
                    st.rerun()

# ── Input bar with paperclip popover ─────────────────────────────────────────
clip_col, input_col = st.columns([1, 10])

with clip_col:
    with st.popover("📎", help="Anexar arquivo .pwf"):
        st.caption("Upload de arquivo de cenário (.pwf)")
        uploaded_pwf = st.file_uploader(
            "Selecionar arquivo",
            type=["pwf"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if uploaded_pwf:
            for f in uploaded_pwf:
                if f.name not in [p["name"] for p in st.session_state.pwf_files]:
                    path = save_pwf(f)
                    st.session_state.pwf_files.append({"name": f.name, "path": path})
                    st.success(f"✅ {f.name} carregado")
                    st.rerun()

with input_col:
    prompt = st.chat_input("Digite sua pergunta sobre o SIN...")

# ── Handle chat input ─────────────────────────────────────────────────────────
if prompt:
    pwf_context = ""
    if st.session_state.pwf_files:
        names = ", ".join(p["name"] for p in st.session_state.pwf_files)
        pwf_context = f"\n\n[Arquivos PWF carregados pelo usuário: {names}]"

    full_prompt = prompt + pwf_context

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        if st.session_state.chain is None:
            answer = (
                "O sistema ainda não está conectado ao Qdrant/Ollama. "
                "Verifique a mensagem de erro acima e clique em **Tentar reconectar**."
            )
            sources = []
            st.markdown(answer)
        else:
            with st.spinner("Consultando base de conhecimento..."):
                try:
                    result = st.session_state.chain.invoke({"question": full_prompt})
                    answer = result["answer"]
                    sources = list({
                        doc.metadata.get("source", "desconhecido")
                        for doc in result.get("source_documents", [])
                    })
                except Exception as e:
                    answer = (
                        f"Ocorreu um erro ao processar sua pergunta: `{e}`\n\n"
                        "Verifique se o Qdrant e o Ollama estão acessíveis."
                    )
                    sources = []

            st.markdown(answer)
            if sources:
                with st.expander("📄 Fontes consultadas"):
                    for src in sources:
                        st.caption(f"• {src}")

    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "sources": sources,
    })
