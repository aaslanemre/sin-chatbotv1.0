import streamlit as st
from pathlib import Path
from utils.pwf_handler import save_pwf
from agents.results_analyzer import save_results_file, check_convergence, format_results_report
from memory.session_memory import StudyState
from memory.persistent_memory import load_study, save_study, clear_study

st.set_page_config(
    page_title="Assistente SIN v3.0",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="expanded",
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
                "Olá! Sou seu assistente especialista no Sistema Interligado Nacional.\n\n"
                "Você pode me fazer perguntas técnicas sobre o SIN, BESS, STATCOM, "
                "HVDC, cenários de operação, fluxo de potência e muito mais.\n\n"
                "Se quiser realizar um estudo de simulação com o Anarede, é só me dizer "
                "e eu te guio pelo processo completo.\n\n"
                "Como posso ajudá-lo hoje?"
            ),
        }
    ]

if "study" not in st.session_state:
    st.session_state.study = load_study()

if "pwf_files" not in st.session_state:
    st.session_state.pwf_files = []

if "simulation_mode" not in st.session_state:
    st.session_state.simulation_mode = False

if "modified_pwf_path" not in st.session_state:
    st.session_state.modified_pwf_path = None

if "last_uploaded_results" not in st.session_state:
    st.session_state.last_uploaded_results = None


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

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    # Mode indicator
    if st.session_state.simulation_mode:
        st.success("🔬 Modo: Guia de Simulação")
    else:
        st.info("💬 Modo: Conversa Livre")

    st.divider()

    # PWF upload
    st.caption("**Cenários PWF**")
    uploaded_pwf = st.file_uploader(
        "Selecionar arquivo .pwf",
        type=["pwf"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )
    if uploaded_pwf:
        if st.button("📤 Confirmar upload PWF", use_container_width=True, type="primary"):
            newly_added = []
            for f in uploaded_pwf:
                if f.name not in [p["name"] for p in st.session_state.pwf_files]:
                    path = save_pwf(f)
                    st.session_state.pwf_files.append({"name": f.name, "path": str(path)})
                    st.session_state.study.pwf_files.append(f.name)
                    newly_added.append(f.name)
            if newly_added:
                save_study(st.session_state.study)
                for name in newly_added:
                    st.toast(f"✅ {name} carregado!", icon="✅")
                st.rerun()
            else:
                st.toast("Arquivo já estava carregado.", icon="ℹ️")

    if st.session_state.pwf_files:
        st.caption("**Arquivos carregados:**")
        for i, pwf in enumerate(st.session_state.pwf_files):
            col1, col2 = st.columns([5, 1])
            with col1:
                st.success(f"✓ {pwf['name']}")
            with col2:
                if st.button("✕", key=f"rm_{i}", help="Remover"):
                    st.session_state.pwf_files.pop(i)
                    st.session_state.study.pwf_files = [
                        p["name"] for p in st.session_state.pwf_files
                    ]
                    save_study(st.session_state.study)
                    st.rerun()

    st.divider()

    # Results upload
    st.caption("**Resultados Anarede**")
    results_file = st.file_uploader(
        "Arquivo de saída do Anarede",
        type=["txt", "res", "lst", "out"],
        label_visibility="collapsed",
    )
    if results_file and results_file.name != st.session_state.last_uploaded_results:
        if st.button("📤 Analisar resultados", use_container_width=True, type="primary"):
            with st.spinner("Analisando arquivo..."):
                rpath = save_results_file(results_file, results_file.name)
                analysis = check_convergence(rpath)
                report = format_results_report(analysis)
                st.session_state.study.last_convergence = analysis["converged"]
                save_study(st.session_state.study)
                st.session_state.last_uploaded_results = results_file.name
            if analysis["converged"]:
                st.toast("✅ Simulação convergiu!", icon="✅")
            else:
                st.toast("❌ Simulação não convergiu.", icon="❌")
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"**Análise do arquivo de resultados:**\n\n{report}",
                "sources": [],
            })
            st.rerun()

    # Modified PWF download
    if st.session_state.modified_pwf_path:
        p = Path(st.session_state.modified_pwf_path)
        if p.exists():
            st.divider()
            st.caption("**PWF Modificado**")
            st.download_button(
                label="⬇️ Baixar PWF modificado",
                data=p.read_bytes(),
                file_name=p.name,
                mime="application/octet-stream",
            )

    st.divider()
    if st.button("🗑️ Limpar conversa", use_container_width=True):
        st.session_state.messages = [st.session_state.messages[0]]
        st.session_state.pwf_files = []
        st.session_state.modified_pwf_path = None
        st.session_state.simulation_mode = False
        st.session_state.study = StudyState()
        st.session_state.chain = None
        st.session_state.chain_error = None
        clear_study()
        st.rerun()

    st.divider()
    st.caption("v3.0 experimental")
    st.caption("Documentos: ONS PAR/PEL 2025, EPE PDE 2035, Manuais ANAREDE/ANATEM")

# ── Main area ─────────────────────────────────────────────────────────────────
st.markdown("### ⚡ Assistente SIN")
st.caption("Planejamento e operação do Sistema Interligado Nacional")
st.divider()

# Connection error banner
if st.session_state.chain_error:
    st.error(
        "**Não foi possível conectar ao Qdrant ou Ollama.**\n\n"
        f"Detalhes: `{st.session_state.chain_error}`\n\n"
        "Verifique se:\n"
        "- Qdrant v3 está rodando: `docker-compose -f docker-compose.v3.yml up -d`\n"
        "- Ollama está rodando: `ollama serve`\n"
        "- Modelos baixados: `ollama pull llama3.2 && ollama pull nomic-embed-text`"
    )
    if st.button("🔄 Tentar reconectar"):
        st.session_state.chain_error = None
        st.rerun()

# Chat messages
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sources" in msg and msg["sources"]:
            with st.expander("📄 Fontes consultadas"):
                for src in msg["sources"]:
                    st.caption(f"• {src}")

# Chat input
prompt = st.chat_input("Digite sua pergunta sobre o SIN...")

# ── Handle input ──────────────────────────────────────────────────────────────
if prompt:
    # Detect simulation intent to update mode indicator
    simulation_keywords = [
        "sim", "quero", "vamos", "pode me guiar", "guia", "iniciar",
        "rodar", "executar", "simular", "anarede", "pwf", "sav",
        "fluxo de potência", "estudo", "contingência",
    ]
    if any(kw in prompt.lower() for kw in simulation_keywords):
        st.session_state.simulation_mode = True

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

    save_study(st.session_state.study)
