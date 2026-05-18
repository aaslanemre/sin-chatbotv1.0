import streamlit as st
from pathlib import Path

st.set_page_config(page_title="Assistente SIN", page_icon="⚡", layout="centered")

# ── Session state ─────────────────────────────────────────────────────────────
if "chain" not in st.session_state:
    st.session_state.chain = None
    st.session_state.chain_error = None

if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "Olá! Sou seu assistente especialista no Sistema Interligado Nacional.\n\n"
                "Posso ajudá-lo a conduzir estudos de localização de BESS, STATCOM, HVDC, "
                "fluxo de potência e estabilidade com o Anarede, Anatem e Plexos.\n\n"
                "Como posso ajudá-lo hoje?"
            ),
        }
    ]

if "study" not in st.session_state:
    from memory.persistent_memory import load_study
    st.session_state.study = load_study()

if "pwf_files" not in st.session_state:
    st.session_state.pwf_files = []

if "modified_pwf_path" not in st.session_state:
    st.session_state.modified_pwf_path = None


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
    if st.button("🗑️ Limpar", help="Limpar conversa e memória"):
        from memory.session_memory import StudyState
        from memory.persistent_memory import clear_study
        st.session_state.messages = [st.session_state.messages[0]]
        st.session_state.pwf_files = []
        st.session_state.modified_pwf_path = None
        st.session_state.study = StudyState()
        st.session_state.chain = None
        st.session_state.chain_error = None
        clear_study()
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

# ── Modified PWF download ─────────────────────────────────────────────────────
if st.session_state.modified_pwf_path:
    p = Path(st.session_state.modified_pwf_path)
    if p.exists():
        st.success(f"Arquivo PWF modificado gerado: `{p.name}`")
        st.download_button(
            label="⬇️ Baixar PWF modificado",
            data=p.read_bytes(),
            file_name=p.name,
            mime="application/octet-stream",
        )

# ── PWF chips (above input) ───────────────────────────────────────────────────
if st.session_state.pwf_files:
    cols = st.columns(min(len(st.session_state.pwf_files), 3))
    for i, pwf in enumerate(st.session_state.pwf_files):
        with cols[i % 3]:
            with st.expander(f"📎 {pwf['name']}"):
                from agents.pwf_agent import preview_pwf
                st.code(preview_pwf(Path(pwf["path"])), language="text")
                if st.button("Remover", key=f"rm_{i}"):
                    st.session_state.pwf_files.pop(i)
                    st.rerun()

# ── Bottom padding so messages aren't hidden behind fixed input bar ───────────
st.markdown("""
<style>
.stChatMessage {
    padding-bottom: 120px;
}
</style>
""", unsafe_allow_html=True)

# ── Fixed bottom bar (CSS) ────────────────────────────────────────────────────
st.markdown("""
<style>
.stChatInput {
    position: fixed;
    bottom: 1rem;
    width: calc(100% - 4rem);
    max-width: 736px;
    left: 50%;
    transform: translateX(-50%);
    z-index: 999;
    background: var(--background-color);
}
section[data-testid="stBottom"] {
    position: fixed;
    bottom: 0;
    width: 100%;
    background: var(--background-color);
    padding: 0.5rem 0;
    z-index: 998;
}
</style>
""", unsafe_allow_html=True)

# ── Upload popovers + chat input ──────────────────────────────────────────────
with st.container():
    col1, col2, col3 = st.columns([1, 1, 10])

    with col1:
        with st.popover("📎", help="Anexar arquivo .pwf"):
            st.caption("Upload de arquivo de cenário (.pwf)")
            uploaded_pwf = st.file_uploader(
                "Selecionar arquivo",
                type=["pwf"],
                accept_multiple_files=True,
                label_visibility="collapsed",
            )
            if uploaded_pwf:
                from utils.pwf_handler import save_pwf
                from memory.persistent_memory import save_study
                for f in uploaded_pwf:
                    if f.name not in [p["name"] for p in st.session_state.pwf_files]:
                        path = save_pwf(f)
                        st.session_state.pwf_files.append({"name": f.name, "path": str(path)})
                        st.session_state.study.pwf_files.append(f.name)
                        save_study(st.session_state.study)
                        st.success(f"✅ {f.name}")
                        st.rerun()

    with col2:
        with st.popover("📊", help="Upload resultado Anarede"):
            st.caption("Upload do arquivo de saída do Anarede")
            results_file = st.file_uploader(
                "Arquivo de resultados",
                type=["txt", "res", "lst", "out"],
                label_visibility="collapsed",
            )
            if results_file:
                from agents.results_analyzer import save_results_file, check_convergence, format_results_report
                from memory.persistent_memory import save_study
                rpath = save_results_file(results_file, results_file.name)
                analysis = check_convergence(rpath)
                report = format_results_report(analysis)
                st.session_state.study.last_convergence = analysis["converged"]
                save_study(st.session_state.study)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": f"**Análise do arquivo de resultados:**\n\n{report}",
                    "sources": [],
                })
                st.rerun()

prompt = st.chat_input("Digite sua pergunta sobre o SIN...")

# ── Handle chat input ─────────────────────────────────────────────────────────
if prompt:
    pwf_context = ""
    if st.session_state.pwf_files:
        names = ", ".join(p["name"] for p in st.session_state.pwf_files)
        pwf_context = f"\n\n[Arquivos PWF carregados: {names}]"

    study_context = st.session_state.study.summary()
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
                    result = st.session_state.chain.invoke({
                        "question": full_prompt,
                        "study_context": study_context,
                    })
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

    # Auto-save study state
    from memory.persistent_memory import save_study
    save_study(st.session_state.study)
