import hashlib
import importlib
import re
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

# Reload prompt module to pick up any edits without full server restart
import prompts.system_prompt as _spm
importlib.reload(_spm)
from prompts.system_prompt import SYSTEM_PROMPT as _CURRENT_PROMPT
_prompt_hash = hashlib.md5(_CURRENT_PROMPT.encode()).hexdigest()

# ── Session state ──────────────────────────────────────────────────────────────
if "chain" not in st.session_state:
    st.session_state.chain = None
    st.session_state.chain_error = None
    st.session_state._prompt_hash = None

# Rebuild chain if system prompt has changed since chain was last built
if st.session_state.get("_prompt_hash") != _prompt_hash:
    st.session_state.chain = None
    st.session_state.chain_error = None
    st.session_state._prompt_hash = _prompt_hash

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

# Simulation state machine state
if "sim_step" not in st.session_state:
    st.session_state.sim_step = "IDLE"   # IDLE → STEP1 → STEP2A → STEP2B → STEP2C → STEP3 → STEP5

if "sim_data" not in st.session_state:
    st.session_state.sim_data = {}   # period, db, scenario, year


# ── Simulation state machine helpers ──────────────────────────────────────────

_SIMULATION_INTENT_TRIGGERS = [
    "quero simular", "gostaria de simular", "preciso simular", "vou simular",
    "quero fazer um estudo", "gostaria de fazer um estudo",
    "preciso fazer um estudo", "vou fazer um estudo",
    "quero rodar o anarede", "vou rodar o anarede",
    "quero inserir um bess", "quero alocar um bess", "quero localizar um bess",
    "preciso inserir um bess", "preciso de uma simulacao", "preciso de uma simulação",
    "quero inserir um statcom", "quero inserir um hvdc",
    "iniciar simulação", "começar simulação", "iniciar estudo", "começar estudo",
    "simulacao de insercao", "simulação de inserção",
    "gostaria de fazer uma simulac",   # handles typos like "simulacao"
]

_ANAREDE_EXEC_TRIGGERS = [
    "como executo", "como rodo", "como rodar", "executar o anarede",
    "rodar o anarede", "já tenho o arquivo carregado", "ja tenho o arquivo",
    "como usar o anarede", "iniciar o anarede", "abrir o anarede",
    "próximo passo", "proximo passo", "e agora", "o que faço agora",
]

_PARPEL_SCENARIOS = (
    "Qual cenário de carga deseja utilizar?\n\n"
    "1. Verão Máxima Diurna (6h–18h, novembro–abril)\n"
    "2. Verão Máxima Noturna (0h–6h e 18h–0h, novembro–abril)\n"
    "3. Verão Mínima Noturna (0h–6h e 18h–0h, novembro–abril)\n"
    "4. Inverno Máxima Diurna (6h–18h, maio–outubro)\n"
    "5. Inverno Máxima Noturna (0h–6h e 18h–0h, maio–outubro)\n"
    "6. Inverno Mínima Noturna (0h–6h e 18h–0h, maio–outubro)"
)

_PDE_SCENARIOS = (
    "Qual cenário de carga deseja utilizar?\n\n"
    "1. Máxima Diurna Seco (6h–18h, maio–novembro)\n"
    "2. Máxima Diurna Úmido (6h–18h, dezembro–abril)\n"
    "3. Máxima Noturna Seco (0h–6h e 18h–0h, maio–novembro)\n"
    "4. Máxima Noturna Úmido (0h–6h e 18h–0h, dezembro–abril)\n"
    "5. Mínima Noturna Seco (0h–6h e 18h–0h, maio–novembro)\n"
    "6. Mínima Noturna Úmido (0h–6h e 18h–0h, dezembro–abril)\n"
    "7. Máxima Coincidente SIN Úmido (14h–16h, março)\n"
    "8. Mínima Líquida Diurna Coincidente SIN Seco (12h–14h, agosto)"
)

_ANAREDE_COMING_SOON = (
    "O guia passo a passo de execução do Anarede está em desenvolvimento "
    "e será disponibilizado em breve.\n\n"
    "Por enquanto, execute o Anarede com o arquivo PWF carregado seguindo "
    "a documentação do CEPEL.\n\n"
    "Quando tiver o arquivo de resultados pronto, faça o upload usando "
    "o botão 📊 na barra lateral e eu analiso a convergência para você."
)

_PARPEL_SCENARIO_NAMES = {
    "1": "Verão Máxima Diurna",    "verão máxima diurna": "Verão Máxima Diurna",
    "2": "Verão Máxima Noturna",   "verão máxima noturna": "Verão Máxima Noturna",
    "3": "Verão Mínima Noturna",   "verão mínima noturna": "Verão Mínima Noturna",
    "4": "Inverno Máxima Diurna",  "inverno máxima diurna": "Inverno Máxima Diurna",
    "5": "Inverno Máxima Noturna", "inverno máxima noturna": "Inverno Máxima Noturna",
    "6": "Inverno Mínima Noturna", "inverno mínima noturna": "Inverno Mínima Noturna",
}

_PDE_SCENARIO_NAMES = {
    "1": "Máxima Diurna Seco",     "máxima diurna seco": "Máxima Diurna Seco",
    "2": "Máxima Diurna Úmido",    "máxima diurna úmido": "Máxima Diurna Úmido",
    "3": "Máxima Noturna Seco",    "máxima noturna seco": "Máxima Noturna Seco",
    "4": "Máxima Noturna Úmido",   "máxima noturna úmido": "Máxima Noturna Úmido",
    "5": "Mínima Noturna Seco",    "mínima noturna seco": "Mínima Noturna Seco",
    "6": "Mínima Noturna Úmido",   "mínima noturna úmido": "Mínima Noturna Úmido",
    "7": "Máxima Coincidente SIN", "máxima coincidente sin": "Máxima Coincidente SIN",
    "8": "Mínima Líquida Diurna",  "mínima líquida diurna": "Mínima Líquida Diurna",
}


def _is_simulation_intent(text: str) -> bool:
    t = text.lower()
    return any(trigger in t for trigger in _SIMULATION_INTENT_TRIGGERS)


def _is_anarede_exec(text: str) -> bool:
    t = text.lower()
    return any(trigger in t for trigger in _ANAREDE_EXEC_TRIGGERS)


def _parse_period(text: str):
    """Return (start_year, end_year) or (year, year) for single year."""
    # Match "2027-2030" or "2027 a 2030"
    m = re.search(r"(20\d\d)\s*[-–a]\s*(20\d\d)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    # Match single year
    m = re.search(r"\b(20\d\d)\b", text)
    if m:
        y = int(m.group(1))
        return y, y
    return None, None


def _recommend_db(start: int, end: int) -> str:
    if start < 2029:
        return "PARPEL"
    if end > 2030:
        return "PDE"
    return "BOTH"


def _db_recommendation_msg(db: str, start: int, end: int) -> str:
    if db == "PARPEL":
        return (
            f"Para o período {start}–{end}, recomendo o **PAR/PEL 2025** do ONS — "
            f"os anos anteriores a 2029 estão disponíveis apenas nessa base.\n\n"
            f"🔗 Download: https://www.ons.org.br/topo/acesso-restrito\n"
            f"_(Requer cadastro gratuito no Portal SINTEGRE)_\n\n"
            + _PARPEL_SCENARIOS
        )
    if db == "PDE":
        return (
            f"Para o período {start}–{end}, utilize o **PDE 2035** da EPE, "
            f"que cobre até 2040.\n\n"
            f"🔗 Download: https://www.epe.gov.br/pt/areas-de-atuacao/energia-eletrica/"
            f"planejamento-da-transmissao/bases-de-dados-de-simulacao\n"
            f"_(Download público direto, sem cadastro)_\n\n"
            + _PDE_SCENARIOS
        )
    # BOTH
    return (
        f"O período {start}–{end} está coberto por ambas as bases:\n\n"
        "- **PAR/PEL 2025 (ONS)**: foco em planejamento operacional (até 2030)\n"
        "  🔗 https://www.ons.org.br/topo/acesso-restrito\n"
        "- **PDE 2035 (EPE)**: foco em expansão de longo prazo (até 2040)\n"
        "  🔗 https://www.epe.gov.br/pt/areas-de-atuacao/energia-eletrica/"
        "planejamento-da-transmissao/bases-de-dados-de-simulacao\n\n"
        "Qual prefere utilizar — planejamento operacional (PAR/PEL) ou expansão (PDE)?"
    )


def _parse_scenario(text: str, db: str):
    t = text.strip().lower()
    lookup = _PARPEL_SCENARIO_NAMES if db == "PARPEL" else _PDE_SCENARIO_NAMES
    # Try exact number
    m = re.match(r"^(\d)$", t)
    if m and m.group(1) in lookup:
        return lookup[m.group(1)]
    # Try name match
    for key, name in lookup.items():
        if key in t or key.replace("ú", "u").replace("ã", "a") in t:
            return name
    return None


def _pwf_filename_hint(db: str, scenario: str, year: int) -> str:
    if db == "PARPEL":
        mapping = {
            "Verão Máxima Diurna":    f"01 VERAO {year} MAX DIURNO.PWF",
            "Verão Máxima Noturna":   f"02 VERAO {year} MAX NOTURNO.PWF",
            "Verão Mínima Noturna":   f"03 VERAO {year} MIN NOTURNO.PWF",
            "Inverno Máxima Diurna":  f"04 INVERNO {year} MAX DIURNO.PWF",
            "Inverno Máxima Noturna": f"05 INVERNO {year} MAX NOTURNO.PWF",
            "Inverno Mínima Noturna": f"06 INVERNO {year} MIN NOTURNO.PWF",
        }
    else:
        mapping = {
            "Máxima Diurna Seco":      f"{year}_1. PD 2035 - MAXIMA DIURNA SECO.PWF",
            "Máxima Diurna Úmido":     f"{year}_2. PD 2035 - MAXIMA DIURNA UMIDO.PWF",
            "Máxima Noturna Seco":     f"{year}_3. PD 2035 - MAXIMA NOTURNA SECO.PWF",
            "Máxima Noturna Úmido":    f"{year}_4. PD 2035 - MAXIMA NOTURNA UMIDO.PWF",
            "Mínima Noturna Seco":     f"{year}_5. PD 2035 - MINIMA NOTURNA SECO.PWF",
            "Mínima Noturna Úmido":    f"{year}_6. PD 2035 - MINIMA NOTURNA UMIDO.PWF",
            "Máxima Coincidente SIN":  f"{year}_7. PD 2035 - MAXIMA COINCIDENTE SIN.PWF",
            "Mínima Líquida Diurna":   f"{year}_8. PD 2035 - MINIMA LIQUIDA DIURNA.PWF",
        }
    fname = mapping.get(scenario, f"{scenario} {year}.PWF")
    return (
        f"Procure pelo arquivo:\n\n"
        f"```\n{fname}\n```\n\n"
        "Após baixar, faça o upload usando o botão 📎 na barra lateral."
    )


def _handle_sim_state(user_text: str) -> str | None:
    """
    Drive the simulation state machine.
    Returns a template response string, or None if the LLM should answer.
    """
    step = st.session_state.sim_step
    data = st.session_state.sim_data

    # ── Anarede execution shortcut (any step) ─────────────────────────────────
    if _is_anarede_exec(user_text) and step not in ("IDLE",):
        return _ANAREDE_COMING_SOON

    # ── IDLE: check for simulation intent ─────────────────────────────────────
    if step == "IDLE":
        if _is_simulation_intent(user_text):
            st.session_state.simulation_mode = True
            st.session_state.sim_step = "STEP1"
            return (
                "Ótimo! Vou te guiar pelo processo de simulação passo a passo.\n\n"
                "Antes de começarmos, você vai precisar baixar os arquivos PWF base. "
                "Existem duas fontes principais:\n\n"
                "📥 **PAR/PEL 2025 (ONS)** — horizonte 2026–2030, planejamento operacional:\n"
                "https://www.ons.org.br/topo/acesso-restrito\n"
                "_(Requer cadastro gratuito no Portal SINTEGRE)_\n\n"
                "📥 **PDE 2035 (EPE)** — horizonte 2029–2040, planejamento de expansão:\n"
                "https://www.epe.gov.br/pt/areas-de-atuacao/energia-eletrica/planejamento-da-transmissao/bases-de-dados-de-simulacao\n"
                "_(Download público direto, sem cadastro)_\n\n"
                "Você pode ir baixando enquanto respondemos as próximas perguntas.\n\n"
                "**[STEP 1]** Qual o período do estudo? (ex: 2027–2030 ou um ano específico como 2028)"
            )
        return None  # Let LLM answer

    # ── STEP 1: waiting for period ─────────────────────────────────────────────
    if step == "STEP1":
        start, end = _parse_period(user_text)
        if start is None:
            return (
                "Não consegui identificar o período. "
                "Por favor, informe o período do estudo. Exemplos: **2027–2030** ou **2028**."
            )
        data["start"] = start
        data["end"] = end
        db = _recommend_db(start, end)
        data["db"] = db
        if db == "BOTH":
            st.session_state.sim_step = "STEP2A_BOTH"
        else:
            st.session_state.sim_step = "STEP2B"
        return _db_recommendation_msg(db, start, end)

    # ── STEP 2A (BOTH): waiting for db choice ─────────────────────────────────
    if step == "STEP2A_BOTH":
        t = user_text.lower()
        if "pde" in t or "expansão" in t or "expansao" in t or "longo prazo" in t:
            data["db"] = "PDE"
        else:
            data["db"] = "PARPEL"
        db = data["db"]
        st.session_state.sim_step = "STEP2B"
        label = "PAR/PEL 2025" if db == "PARPEL" else "PDE 2035"
        scenarios = _PARPEL_SCENARIOS if db == "PARPEL" else _PDE_SCENARIOS
        return f"Ótimo, usaremos o **{label}**.\n\n{scenarios}"

    # ── STEP 2B: waiting for scenario selection ────────────────────────────────
    if step == "STEP2B":
        db = data.get("db", "PARPEL")
        scenario = _parse_scenario(user_text, db)
        if scenario is None:
            scenarios = _PARPEL_SCENARIOS if db == "PARPEL" else _PDE_SCENARIOS
            return (
                "Não identifiquei o cenário. Por favor, selecione pelo número ou nome:\n\n"
                + scenarios
            )
        data["scenario"] = scenario
        start, end = data["start"], data["end"]
        if start == end:
            # Single year already known
            data["year"] = start
            st.session_state.sim_step = "STEP3"
            return f"Cenário selecionado: **{scenario}**.\n\n" + _pwf_filename_hint(db, scenario, start)
        # Interval: ask for specific year
        st.session_state.sim_step = "STEP2C"
        years = "\n".join(f"- {y}" for y in range(start, end + 1))
        return (
            f"Cenário selecionado: **{scenario}**.\n\n"
            f"Para qual ano dentro do período?\n\n{years}"
        )

    # ── STEP 2C: waiting for specific year ────────────────────────────────────
    if step == "STEP2C":
        m = re.search(r"\b(20\d\d)\b", user_text)
        if not m:
            start, end = data["start"], data["end"]
            years = "\n".join(f"- {y}" for y in range(start, end + 1))
            return f"Não identifiquei o ano. Escolha um dos anos:\n\n{years}"
        year = int(m.group(1))
        data["year"] = year
        db = data.get("db", "PARPEL")
        scenario = data.get("scenario", "")
        st.session_state.sim_step = "STEP3"
        return _pwf_filename_hint(db, scenario, year)

    # ── STEP 3: waiting for PWF upload confirmation ────────────────────────────
    if step == "STEP3":
        t = user_text.lower()
        if st.session_state.pwf_files or any(
            kw in t for kw in ["carregado", "fiz upload", "já carreguei", "sim", "ok", "pronto", "feito"]
        ):
            st.session_state.sim_step = "STEP5"
            return (
                "Arquivo PWF recebido. Vamos prosseguir.\n\n"
                + _ANAREDE_COMING_SOON
            )
        return (
            "Por favor, faça o upload do arquivo PWF usando o botão 📎 na barra lateral "
            "e confirme aqui quando estiver carregado."
        )

    return None  # fallback to LLM


def _load_chain():
    try:
        import rag.chain as _chain_mod
        importlib.reload(_chain_mod)
        st.session_state.chain = _chain_mod.build_chain()
        st.session_state.chain_error = None
    except Exception as e:
        st.session_state.chain = None
        st.session_state.chain_error = str(e)


if st.session_state.chain is None and st.session_state.chain_error is None:
    with st.spinner("Carregando modelos e base de conhecimento..."):
        _load_chain()

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    if st.session_state.simulation_mode:
        step_label = {
            "IDLE": "", "STEP1": "STEP 1: Período",
            "STEP2A_BOTH": "STEP 2: Base de dados",
            "STEP2B": "STEP 2: Cenário",
            "STEP2C": "STEP 2: Ano",
            "STEP3": "STEP 3: Upload PWF",
            "STEP5": "STEP 5: Execução",
        }.get(st.session_state.sim_step, "")
        st.success(f"🔬 Modo: Guia de Simulação\n{step_label}")
    else:
        st.info("💬 Modo: Conversa Livre")

    st.divider()

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
        st.session_state.sim_step = "IDLE"
        st.session_state.sim_data = {}
        st.session_state.study = StudyState()
        st.session_state.chain = None
        st.session_state.chain_error = None
        clear_study()
        st.rerun()

    st.divider()
    st.caption("v3.0 experimental")
    st.caption("Documentos: ONS PAR/PEL 2025, EPE PDE 2035, Manuais ANAREDE/ANATEM")

# ── Main area ──────────────────────────────────────────────────────────────────
st.markdown("### ⚡ Assistente SIN")
st.caption("Planejamento e operação do Sistema Interligado Nacional")
st.divider()

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

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sources" in msg and msg["sources"]:
            with st.expander("📄 Fontes consultadas"):
                for src in msg["sources"]:
                    st.caption(f"• {src}")

prompt = st.chat_input("Digite sua pergunta sobre o SIN...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Try state machine first
    sim_response = _handle_sim_state(prompt)

    with st.chat_message("assistant"):
        if sim_response is not None:
            # Deterministic simulation guide response
            answer = sim_response
            sources = []
            st.markdown(answer)
        elif st.session_state.chain is None:
            answer = (
                "O sistema ainda não está conectado ao Qdrant/Ollama. "
                "Verifique a mensagem de erro acima e clique em **Tentar reconectar**."
            )
            sources = []
            st.markdown(answer)
        else:
            # MODE 1: free technical Q&A via LLM
            pwf_context = ""
            if st.session_state.pwf_files:
                names = ", ".join(p["name"] for p in st.session_state.pwf_files)
                pwf_context = f"\n\n[Arquivos PWF carregados: {names}]"

            study_context = st.session_state.study.summary()
            full_prompt = prompt + pwf_context

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
