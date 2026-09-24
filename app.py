import hashlib
import importlib
import re
import uuid
import unicodedata
import streamlit as st
from agents.pwf_agent import generate_dbar_block, generate_statcom_block, generate_contingency_block
from agents.results_analyzer import save_results_file, check_convergence, format_results_report
from agents.network_builder import (
    convert_line_params,
    validate_network,
    build_full_pwf,
    diagnose_nonconvergence,
    format_network_summary,
)
from memory.session_memory import StudyState
from memory.persistent_memory import load_study, save_study, clear_study
from auth.db import init_db
from auth.auth_service import (
    signup, login,
    log_chat_message, create_session, update_session,
    save_paused_state, load_paused_state, clear_paused_state,
)

st.set_page_config(
    page_title="Assistente SIN v6.3.0",
    page_icon="⚡",
    layout="centered",
    initial_sidebar_state="expanded",
)

# ── Initialize database tables ────────────────────────────────────────────────
if "db_initialized" not in st.session_state:
    try:
        init_db()
        st.session_state.db_initialized = True
    except Exception as e:
        st.session_state.db_initialized = False
        st.session_state.db_init_error = str(e)

# ── Authentication gate ──────────────────────────────────────────────────────
if "user" not in st.session_state:
    st.markdown("### Assistente SIN")
    if not st.session_state.get("db_initialized"):
        st.error(
            f"Banco de dados indisponivel: `{st.session_state.get('db_init_error', 'desconhecido')}`\n\n"
            "Verifique se o PostgreSQL esta rodando: `docker-compose up -d`"
        )
        st.stop()

    tab_login, tab_signup = st.tabs(["Entrar", "Criar conta"])
    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar")
            if submitted:
                user = login(email, password)
                if user:
                    st.session_state["user"] = user
                    _sid = str(uuid.uuid4())
                    st.session_state["session_id"] = _sid
                    create_session(_sid, user["id"])
                    # Check for paused simulation to offer resume
                    paused = load_paused_state(user["id"])
                    if paused:
                        st.session_state["_pending_resume"] = paused
                    st.rerun()
                else:
                    st.error("Email ou senha incorretos.")

    with tab_signup:
        with st.form("signup_form"):
            s_email = st.text_input("Email", key="s_email")
            s_name = st.text_input("Nome completo", key="s_name")
            s_pass = st.text_input("Senha", type="password", key="s_pass")
            s_pass2 = st.text_input("Confirmar senha", type="password", key="s_pass2")
            s_code = st.text_input("Codigo de acesso", type="password", key="s_code")
            s_submitted = st.form_submit_button("Criar conta")
            if s_submitted:
                if s_pass != s_pass2:
                    st.error("As senhas nao coincidem.")
                elif len(s_pass) < 6:
                    st.error("A senha deve ter pelo menos 6 caracteres.")
                else:
                    result = signup(s_email, s_pass, s_name, s_code)
                    if result["ok"]:
                        st.session_state["user"] = result["user"]
                        _sid = str(uuid.uuid4())
                        st.session_state["session_id"] = _sid
                        create_session(_sid, result["user"]["id"])
                        st.rerun()
                    else:
                        st.error(result["error"])
    st.stop()

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

if "simulation_mode" not in st.session_state:
    st.session_state.simulation_mode = False


# Simulation state machine state
if "sim_step" not in st.session_state:
    st.session_state.sim_step = "IDLE"   # IDLE → STEP1 → STEP2A → STEP2B → STEP2C → STEP3 → STEP5

if "sim_data" not in st.session_state:
    st.session_state.sim_data = {}   # period, db, scenario, year

if "sim_status" not in st.session_state:
    st.session_state.sim_status = None   # None | "active" | "paused"

# ── Auto-resume paused simulation on login ────────────────────────────────────
if "_pending_resume" in st.session_state:
    _pr = st.session_state.pop("_pending_resume")
    st.session_state.sim_step = _pr["sim_step"]
    st.session_state.sim_data = _pr["sim_data"]
    st.session_state.simulation_mode = True
    st.session_state.sim_status = "active"
    clear_paused_state(_pr["session_id"])
    _step_label = _pr["sim_step"]
    _sim_type = _pr["sim_data"].get("sim_type", "BESS")
    st.session_state.messages.append({
        "role": "assistant",
        "content": (
            f"Bem-vindo de volta! Encontrei uma simulação pausada ({_sim_type}, etapa {_step_label}).\n\n"
            "A simulação foi retomada automaticamente. Continue de onde parou, "
            "ou digite **encerrar** para finalizar."
        ),
    })


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

_PARPEL_SCENARIOS = (
    "Qual cenário de carga deseja utilizar?\n\n"
    "1. Verão Máxima Diurna (6h–18h, novembro–abril)\n"
    "2. Verão Máxima Noturna (0h–6h e 18h–0h, novembro–abril)\n"
    "3. Verão Mínima Noturna (0h–6h e 18h–0h, novembro–abril)\n"
    "4. Inverno Máxima Diurna (6h–18h, maio–outubro)\n"
    "5. Inverno Máxima Noturna (0h–6h e 18h–0h, maio–outubro)\n"
    "6. Inverno Mínima Noturna (0h–6h e 18h–0h, maio–outubro)\n\n"
    "Nota: dentro do arquivo SAV, ao carregá-lo no ANAREDE, você poderá "
    "selecionar o cenário desejado. O SAV contém todos os patamares."
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


_NETWORK_INTENT_TRIGGERS = [
    "rede do zero", "montar uma rede", "montar rede", "criar um caso novo",
    "criar caso novo", "rede própria", "rede propria", "novo caso",
    "criar rede", "construir rede", "caso do zero", "criar um caso",
    "montar caso", "rede nova", "criar uma rede",
]


def _is_network_intent(text: str) -> bool:
    t = text.lower()
    return any(trigger in t for trigger in _NETWORK_INTENT_TRIGGERS)


# ── NET state helpers ─────────────────────────────────────────────────────────

def _parse_net_int(text: str, min_val: int = 1, max_val: int = 99999):
    """Return first integer found in text within [min_val, max_val], or None."""
    m = re.search(r'\b(\d+)\b', text.strip())
    if m:
        n = int(m.group(1))
        if min_val <= n <= max_val:
            return n
    return None


def _parse_net_float(text: str, min_val=None, max_val=None):
    """Return first float found in text (accepts comma decimal), or None."""
    m = re.search(r'[-+]?\d*[.,]?\d+', text.strip())
    if m:
        try:
            v = float(m.group(0).replace(",", "."))
            if min_val is not None and v < min_val:
                return None
            if max_val is not None and v > max_val:
                return None
            return v
        except ValueError:
            pass
    return None


def _parse_bus_tipo(text: str):
    """Parse bus type (0, 1, 2) from user text."""
    t = text.strip().lower()
    if re.search(r'\b0\b', t) or any(w in t for w in ["pq", "carga"]):
        return 0
    if re.search(r'\b1\b', t) or any(w in t for w in ["pv", "geração", "geracao", "geração controlada"]):
        return 1
    if re.search(r'\b2\b', t) or any(w in t for w in ["ref", "referência", "referencia", "slack", "swing"]):
        return 2
    return None


def _parse_line_mode(text: str):
    """Return 'per_km', 'pu', or 'pct' from user text, or None."""
    t = text.strip().lower()
    if t in ("1",) or any(w in t for w in ["por km", "per_km", "km", "/km", "ohm"]):
        return "per_km"
    if t in ("2",) or any(w in t for w in ["pu", "por unidade", "per unit"]):
        return "pu"
    if t in ("3",) or any(w in t for w in ["pct", "percent", "%", "mvar", "por cento", "dlin"]):
        return "pct"
    return None


def _parse_four_floats(text: str):
    """Extract up to 4 floats from text (handles R=x X=y format and bare values)."""
    # Try key=value pairs first
    vals = {}
    for key in ("r", "x", "b", "l", "q"):
        m = re.search(rf'\b{key}\s*[=:]\s*([-+]?\d*[.,]?\d+)', text, re.IGNORECASE)
        if m:
            vals[key.lower()] = float(m.group(1).replace(",", "."))
    if vals:
        return vals

    # Bare sequence of numbers
    nums = [float(x.replace(",", ".")) for x in re.findall(r'[-+]?\d*[.,]?\d+', text)]
    return nums


_NET_HELP = {
    "NET1_SETUP": (
        "**Título do caso:** nome livre para identificar sua rede (ex: 'LT 230kV Teste'). "
        "Não afeta o cálculo.\n\n"
        "**Base MVA:** potência de referência do sistema. O padrão no Brasil é **100 MVA**. "
        "Altere apenas se seus dados de R/X já estiverem em outra base.\n\n"
        "Você pode responder os dois juntos (ex: `LT 230kV, 100 MVA`) ou separados."
    ),
    "NET2_count": (
        "**Número de barras:**\n"
        "Uma barra representa uma subestação ou nó da rede. Redes simples têm 2–5 barras. "
        "O limite aqui é 20.\n\n"
        "Toda rede precisa de:\n"
        "- Exatamente **1 barra de referência** (tipo 2 / slack)\n"
        "- Pelo menos **1 barra de carga** ou geração\n\n"
        "Exemplo mínimo: 2 barras (1 referência + 1 carga), 1 linha."
    ),
    "NET2_number": (
        "**Número da barra:** identificador único entre 1 e 99999.\n"
        "Pode ser qualquer valor (ex: 1, 2, 3 ou 1001, 1002). "
        "Não pode se repetir."
    ),
    "NET2_name": (
        "**Nome da barra:** rótulo de até 12 caracteres.\n"
        "Exemplos: GER_USINA, CARGA_CID, REF_SWING, SE_230.\n"
        "Use apenas letras, números e sublinhados."
    ),
    "NET2_kv": (
        "**Tensão nominal em kV:** nível de tensão da barra.\n"
        "Tensões padrão do SIN: 138, 230, 345, 440, 500, 765 kV.\n"
        "Todas as barras conectadas por linhas simples devem ter a mesma tensão."
    ),
    "NET2_tipo": (
        "**Tipos de barra no ANAREDE:**\n\n"
        "**0 — PQ (carga):** P e Q fixos. Use para subestações de consumo.\n\n"
        "**1 — PV (geração):** você define P e a tensão-alvo; o ANAREDE ajusta Q.\n\n"
        "**2 — Referência (slack):** OBRIGATÓRIA — deve existir exatamente UMA. "
        "Balancea toda a geração/carga. Geralmente é a maior usina."
    ),
    "NET2_pg": "**Geração ativa em MW:** potência que o gerador injeta na rede. Exemplo: 100 MW.",
    "NET2_v_pu": (
        "**Tensão setpoint em pu:** valor que o gerador/referência tentará manter.\n"
        "Faixa típica: 0.95–1.05 pu. Exemplo: 1.02 pu."
    ),
    "NET2_qmin": "**Qmin em Mvar:** limite mínimo de geração reativa. Negativo = absorção. Exemplo: −50.",
    "NET2_qmax": "**Qmax em Mvar:** limite máximo de geração reativa. Exemplo: 50.",
    "NET2_pl": "**Carga ativa em MW:** potência consumida. Exemplo: 100 MW. Use 0 se não houver carga.",
    "NET2_ql": "**Carga reativa em Mvar:** reativo consumido. Tipicamente 20–40% da carga ativa. Use 0 se não houver.",
    "NET3_count": (
        "**Número de linhas:**\n"
        "Para N barras, você precisa de pelo menos N−1 linhas para conectar a rede.\n\n"
        "**Modos de parâmetros:**\n"
        "**1 — por km:** R(Ω/km), X(Ω/km), B(μS/km) + comprimento → conversão automática\n"
        "**2 — pu:** R, X, B em por unidade na base do sistema\n"
        "**3 — %/Mvar:** R%, X%, Q em Mvar (direto para DLIN)"
    ),
    "NET3_from": "**Barra origem:** número de onde a linha parte. Deve ser uma barra já definida.",
    "NET3_to": "**Barra destino:** número onde a linha chega. Deve ser diferente da origem.",
    "NET3_circuit": "**Circuito:** normalmente 1. Use 2, 3... para circuitos paralelos entre o mesmo par de barras.",
    "NET3_mode": (
        "**Modo de entrada:**\n"
        "1 ou `por_km` — R(Ω/km), X(Ω/km), B(μS/km) + comprimento em km\n"
        "2 ou `pu` — R, X, B em pu na base do sistema\n"
        "3 ou `%` — R%, X%, susceptância em Mvar (valores prontos para o DLIN)"
    ),
    "NET3_values": (
        "**Exemplo de entrada por km:**\n"
        "`R=0.0257 X=0.2995 B=5.4542 L=180`\n"
        "ou compacto: `0.0257 0.2995 5.4542 180`\n\n"
        "**Exemplo em %/Mvar:**\n"
        "`R=0.87 X=10.19 Q=51.93`\n"
        "ou compacto: `0.87 10.19 51.93`"
    ),
    "NET4_REVIEW": (
        "**Comandos disponíveis:**\n"
        "- `editar barra N` — redigitar dados da barra N\n"
        "- `editar linha N` — redigitar dados da linha N\n"
        "- `adicionar barra` — incluir nova barra\n"
        "- `adicionar linha` — incluir nova linha\n"
        "- `remover linha N` — remover a linha N\n"
        "- `confirmar` — gerar o PWF (somente sem erros)"
    ),
    "NET5_GENERATE": (
        "Copie o conteúdo do bloco de código e salve como arquivo `.pwf` "
        "(ex: `minha_rede.pwf`) no seu computador. "
        "Em seguida, abra o ANAREDE para carregar o arquivo."
    ),
    "NET6_RUN": (
        "**QUESTÃO ABERTA:** O caminho exato de menu para abrir um arquivo PWF novo no ANAREDE "
        "não foi confirmado pelo manual — não será inventado aqui.\n\n"
        "Instrução geral: procure 'Abrir' ou 'Carregar arquivo' no menu principal do ANAREDE "
        "e selecione o arquivo .pwf salvo. Após carregar, execute o fluxo com **Ctrl+R**."
    ),
    "NET7_RESULTS": (
        "**Lendo os resultados:**\n"
        "- Tensões aparecem próximas a cada barra no diagrama (pu ou kV)\n"
        "- Fluxos aparecem nas extremidades das linhas (MW e Mvar)\n"
        "- Hachura **VERMELHA**: sobrecarga ou sobretensão\n"
        "- Hachura **AZUL**: subtensão\n\n"
        "**Para salvar como SAV:** QUESTÃO ABERTA — procedimento não confirmado pelo manual."
    ),
}


# ── NET state machine ─────────────────────────────────────────────────────────

_NET_BACK = {
    "NET2_BUSES": "NET1_SETUP",
    "NET3_LINES": "NET2_BUSES",
    "NET4_REVIEW": "NET3_LINES",
    "NET5_GENERATE": "NET4_REVIEW",
    "NET6_RUN": "NET5_GENERATE",
    "NET7_RESULTS": "NET6_RUN",
}


def _net_help(key: str) -> str:
    return _NET_HELP.get(key, "Sem ajuda disponível para esta etapa.")


def _net_is_help(text: str) -> bool:
    t = text.strip().lower()
    return any(w in t for w in ["ajuda", "help", "não sei", "nao sei", "como", "o que é", "o que e"])


def _net_is_back(text: str) -> bool:
    return text.strip().lower() in ("voltar", "volta", "anterior", "back")


def _net_finalize_bus(data: dict, current: dict) -> str:
    """Commit current bus to network, advance index, return next prompt."""
    network = data["network"]
    net2 = data["net2"]
    network["buses"].append(dict(current))
    net2["idx"] += 1
    net2["current"] = {}
    total = net2["total"]
    idx = net2["idx"]
    bus_num = current["number"]
    tipo_label = {0: "PQ", 1: "PV", 2: "Referência"}.get(current.get("tipo", 0), "?")
    if idx >= total:
        # All buses collected — move to NET3_LINES
        st.session_state.sim_step = "NET3_LINES"
        data.pop("net2", None)
        return _net_lines_start(data)
    net2["field"] = "number"
    return (
        f"✅ Barra **{bus_num}** ({tipo_label}) registrada.\n\n"
        f"**Barra {idx + 1} de {total}.** Número da barra (1 a 99999):"
    )


def _net_lines_start(data: dict) -> str:
    """Return the opening prompt for NET3_LINES."""
    # Check if a line was pre-filled from pending_lt
    pending_lt = data.get("pending_lt")
    if pending_lt and data.get("network", {}).get("lines") is None:
        data["network"]["lines"] = []
    network = data.get("network", {})
    buses = network.get("buses", [])
    n_buses = len(buses)
    bus_list = ", ".join(str(b["number"]) for b in buses)
    data["net3"] = {"idx": 0, "field": "count", "current": {}}
    if not network.get("lines"):
        network["lines"] = []
    return (
        f"Ótimo! **{n_buses} barra(s)** registrada(s).\n\n"
        f"Barras disponíveis: **{bus_list}**\n\n"
        "**Quantas linhas a rede terá?**\n\n"
        f"(Para {n_buses} barras conectadas, você precisa de pelo menos **{n_buses - 1}** linha(s))\n\n"
        "💡 Digite `ajuda` para ver os modos de parâmetros disponíveis (por km, pu ou %)."
    )


def _net_finalize_line(data: dict, current: dict) -> str:
    """Commit current line to network, advance index, return next prompt."""
    network = data["network"]
    net3 = data["net3"]
    ln_id = len(network["lines"]) + 1
    current["id"] = ln_id
    network["lines"].append(dict(current))
    net3["idx"] += 1
    net3["current"] = {}
    total = net3["total"]
    idx = net3["idx"]
    calc = current.get("calc_str", "")
    calc_section = f"\n\n{calc}" if calc else ""
    if idx >= total:
        # All lines collected — move to NET4_REVIEW
        st.session_state.sim_step = "NET4_REVIEW"
        data.pop("net3", None)
        return _net_show_review(data) + calc_section
    net3["field"] = "from_bus"
    buses = network.get("buses", [])
    bus_list = ", ".join(str(b["number"]) for b in buses)
    return (
        f"✅ Linha **{ln_id}** (barras {current['from_bus']}–{current['to_bus']}) registrada."
        + calc_section
        + f"\n\n---\n\n**Linha {idx + 1} de {total}.**\n\n"
        f"Barras disponíveis: **{bus_list}**\n\n"
        "Barra **origem**:"
    )


def _net_show_review(data: dict) -> str:
    """Return NET4_REVIEW prompt with summary table and validation issues."""
    network = data.get("network", {})
    summary = format_network_summary(network)
    issues = validate_network(network)
    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    parts = [f"**Revisão da rede:**\n\n{summary}"]

    if errors:
        parts.append("\n\n**❌ ERROS (impedem a geração do arquivo):**")
        for e in errors:
            parts.append(f"\n- {e['message']}\n  *Por quê:* {e['why_it_matters']}\n  *Como corrigir:* {e['how_to_fix']}")
    if warnings:
        parts.append("\n\n**⚠️ AVISOS:**")
        for w in warnings:
            parts.append(f"\n- {w['message']}\n  *Como corrigir:* {w['how_to_fix']}")
    if not errors and not warnings:
        parts.append("\n\n✅ **Nenhum erro ou aviso — rede pronta para gerar o arquivo PWF.**")

    if errors:
        parts.append(
            "\n\n**Corrija os erros acima** antes de continuar.\n"
            "Use `editar barra N`, `editar linha N`, `adicionar barra`, `adicionar linha`, `remover linha N`."
        )
    else:
        parts.append(
            "\n\nDigite **confirmar** para gerar o arquivo PWF, "
            "ou edite a rede com os comandos acima."
        )

    return "".join(parts)


def _handle_net_state(user_text: str):
    """Drive the NET* state machine. Returns response string or None."""
    step = st.session_state.sim_step
    data = st.session_state.sim_data

    # Global: voltar
    if _net_is_back(user_text) and step in _NET_BACK:
        prev_step = _NET_BACK[step]
        st.session_state.sim_step = prev_step
        # Re-enter the previous step's prompt
        if prev_step == "NET1_SETUP":
            data.pop("net2", None)
            net = data.get("network", {})
            return (
                f"Voltando à configuração inicial.\n\n"
                f"Título atual: **{net.get('title','—')}** | Base: **{net.get('base_mva',100)} MVA**\n\n"
                "Informe o novo título e base MVA, ou **confirmar** para manter."
            )
        if prev_step == "NET2_BUSES":
            data.pop("net3", None)
            net2_total = len(data.get("network", {}).get("buses", []))
            return (
                f"Voltando às barras. {net2_total} barra(s) registrada(s).\n\n"
                + _net_lines_start(data).replace("Ótimo! ", "")
            )
        if prev_step == "NET3_LINES":
            data.pop("net3", None)
            return "Voltando às linhas.\n\n" + _net_lines_start(data)
        if prev_step == "NET4_REVIEW":
            return "Voltando à revisão.\n\n" + _net_show_review(data)
        if prev_step == "NET5_GENERATE":
            pwf = data.get("net_pwf", "")
            return (
                "Voltando ao arquivo gerado.\n\n"
                f"```\n{pwf}\n```\n\n"
                "Digite **continuar** para prosseguir."
            )
        if prev_step == "NET6_RUN":
            return _net6_prompt(data)
        return None

    # ── NET1_SETUP ────────────────────────────────────────────────────────────
    if step == "NET1_SETUP":
        if _net_is_help(user_text):
            return _net_help("NET1_SETUP") + "\n\n**Título e base MVA:**"
        # Accept "confirmar" to keep defaults
        t = user_text.strip()
        network = data.setdefault("network", {
            "title": "Meu Caso", "base_mva": 100.0, "buses": [], "lines": []
        })
        if t.lower() in ("confirmar", "ok", "padrão", "padrao", "default"):
            pass  # keep defaults
        else:
            # Try to parse title + base MVA
            mva_m = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:mva|MVA)', t, re.IGNORECASE)
            if mva_m:
                network["base_mva"] = float(mva_m.group(1).replace(",", "."))
                title_part = re.sub(r'[\d.,]+\s*(?:mva|MVA)', '', t, flags=re.IGNORECASE).strip().strip(",;-")
                if title_part:
                    network["title"] = title_part[:50]
            else:
                # Just a title, default base MVA
                if t:
                    network["title"] = t[:50]

        data.setdefault("net_setup_field", "done")
        st.session_state.sim_step = "NET2_BUSES"
        data["net2"] = {"total": None, "idx": 0, "field": "count", "current": {}}
        return (
            f"✅ Caso: **{network['title']}** | Base: **{network['base_mva']} MVA**\n\n"
            "**Quantas barras a rede terá?** (mínimo **2**, máximo **20**)\n\n"
            "💡 Digite `ajuda` para saber como organizar as barras."
        )

    # ── NET2_BUSES ────────────────────────────────────────────────────────────
    if step == "NET2_BUSES":
        net2 = data.setdefault("net2", {"total": None, "idx": 0, "field": "count", "current": {}})
        network = data.setdefault("network", {"title": "Meu Caso", "base_mva": 100.0, "buses": [], "lines": []})
        total = net2.get("total")
        field = net2.get("field", "count")

        if _net_is_help(user_text):
            help_key = f"NET2_{field}" if f"NET2_{field}" in _NET_HELP else "NET2_count"
            return _net_help(help_key) + f"\n\n*(Retomando pergunta sobre **{field}**)*"

        # Phase 1: get bus count
        if field == "count" or total is None:
            n = _parse_net_int(user_text, 2, 20)
            if n is None:
                return "Quantas barras a rede terá? Informe um número entre **2** e **20**."
            net2["total"] = n
            net2["idx"] = 0
            net2["field"] = "number"
            net2["current"] = {}
            return f"**Barra 1 de {n}.**\n\nNúmero da barra (1 a 99999, ex: **1**):"

        # Phase 2: collecting per-bus fields
        idx = net2["idx"]
        current = net2.setdefault("current", {})

        if field == "number":
            n = _parse_net_int(user_text, 1, 99999)
            if n is None:
                return f"Número da barra {idx + 1} (1 a 99999, ex: **{idx + 1}**):"
            existing = {b["number"] for b in network["buses"]}
            if n in existing:
                return f"Número **{n}** já existe. Informe um número diferente:"
            current["number"] = n
            net2["field"] = "name"
            return f"Nome da barra **{n}** (até 12 caracteres, ex: **SE_{n}**):"

        if field == "name":
            name = re.sub(r'\s+', '_', user_text.strip())[:12]
            if not name:
                return "Nome não pode estar vazio. Informe o nome da barra (ex: **BARRA_A**):"
            current["name"] = name
            net2["field"] = "kv"
            return f"Tensão nominal de **{name}** em kV (ex: **230**):"

        if field == "kv":
            kv = _parse_net_float(user_text, 0.1)
            if kv is None:
                return "Tensão nominal em kV (ex: **230**, 138, 500):"
            current["kv"] = kv
            net2["field"] = "tipo"
            return (
                f"Tipo da barra **{current.get('name','')}** ({kv} kV):\n\n"
                "**0** — PQ (carga — P e Q fixos)\n\n"
                "**1** — PV (geração — tensão controlada)\n\n"
                "**2** — Referência (slack — balanço do sistema, obrigatória)"
            )

        if field == "tipo":
            tipo = _parse_bus_tipo(user_text)
            if tipo is None:
                return "Informe **0** (PQ), **1** (PV) ou **2** (Referência):"
            current["tipo"] = tipo
            current.setdefault("v_pu", 1.0)
            current.setdefault("angle_deg", 0.0)
            current.setdefault("p_gen_mw", 0.0)
            current.setdefault("q_min_mvar", 0.0)
            current.setdefault("q_max_mvar", 0.0)
            current.setdefault("p_load_mw", 0.0)
            current.setdefault("q_load_mvar", 0.0)
            if tipo == 2:
                net2["field"] = "v_pu"
                return "Tensão de referência em pu (ex: **1.05**; faixa típica: 0.95–1.10):"
            elif tipo == 1:
                net2["field"] = "pg"
                return f"Geração ativa de **{current.get('name','')}** em MW (ex: **100**):"
            else:
                net2["field"] = "pl"
                return f"Carga ativa de **{current.get('name','')}** em MW (ex: **100**; use **0** se sem carga):"

        if field == "pg":
            pg = _parse_net_float(user_text, 0.0)
            if pg is None:
                return "Geração ativa em MW (ex: **100**; use 0 se sem geração):"
            current["p_gen_mw"] = pg
            net2["field"] = "v_pu"
            return f"Tensão setpoint de **{current.get('name','')}** em pu (ex: **1.02**):"

        if field == "v_pu":
            v = _parse_net_float(user_text, 0.5, 1.5)
            if v is None:
                return "Tensão em pu (ex: **1.02**; faixa típica: 0.95–1.10):"
            current["v_pu"] = v
            if current.get("tipo") == 1:
                net2["field"] = "qmin"
                return "Qmin em Mvar — limite mínimo de reativo (ex: **-100**; negativo = absorção):"
            else:
                return _net_finalize_bus(data, current)

        if field == "qmin":
            qmin = _parse_net_float(user_text)
            if qmin is None:
                return "Qmin em Mvar (ex: **-100**):"
            current["q_min_mvar"] = qmin
            net2["field"] = "qmax"
            return "Qmax em Mvar — limite máximo de reativo (ex: **100**):"

        if field == "qmax":
            qmax = _parse_net_float(user_text)
            if qmax is None:
                return "Qmax em Mvar (ex: **100**):"
            current["q_max_mvar"] = qmax
            return _net_finalize_bus(data, current)

        if field == "pl":
            pl = _parse_net_float(user_text, 0.0)
            if pl is None:
                return "Carga ativa em MW (ex: **100**; use **0** se sem carga):"
            current["p_load_mw"] = pl
            net2["field"] = "ql"
            return "Carga reativa em Mvar (ex: **50**; use **0** se sem reativo):"

        if field == "ql":
            ql = _parse_net_float(user_text, 0.0)
            if ql is None:
                return "Carga reativa em Mvar (ex: **50**; use **0**):"
            current["q_load_mvar"] = ql
            return _net_finalize_bus(data, current)

        return "Não entendi. Digite `ajuda` para orientação ou continue com os dados da barra."

    # ── NET3_LINES ────────────────────────────────────────────────────────────
    if step == "NET3_LINES":
        net3 = data.setdefault("net3", {"total": None, "idx": 0, "field": "count", "current": {}})
        network = data.setdefault("network", {})
        network.setdefault("lines", [])
        total = net3.get("total")
        field = net3.get("field", "count")

        if _net_is_help(user_text):
            help_key = f"NET3_{field}" if f"NET3_{field}" in _NET_HELP else "NET3_count"
            return _net_help(help_key) + "\n\n*(Retomando pergunta sobre a linha)*"

        # Check for pre-filled line from pending_lt
        if field == "count" and total is None:
            pending_lt = data.get("pending_lt", {})
            if pending_lt and data.get("net3_lt_prefilled") is None:
                # Pre-fill line from pending_lt
                kv = pending_lt.get("voltage_kv")
                r = pending_lt.get("R_ohm_km")
                x = pending_lt.get("X_ohm_km")
                b = pending_lt.get("B_us_km")
                L = pending_lt.get("length_km")
                if all(v is not None for v in [kv, r, x, b, L]):
                    try:
                        conv = convert_line_params(kv, "per_km", {"R": r, "X": x, "B": b}, L,
                                                   base_mva=network.get("base_mva", 100.0))
                        prefilled_line = {
                            "id": 1,
                            "from_bus": None,
                            "to_bus": None,
                            "circuit": 1,
                            "r_pct": conv["r_pct"],
                            "x_pct": conv["x_pct"],
                            "q_mvar": conv["q_mvar"],
                            "param_mode": "per_km",
                            "calc_str": conv["calc_str"],
                        }
                        data["net3_prefilled_line"] = prefilled_line
                        data["net3_lt_prefilled"] = True
                        buses = network.get("buses", [])
                        bus_list = ", ".join(str(b["number"]) for b in buses)
                        net3["field"] = "count"
                        return (
                            "✅ Parâmetros da sua LT foram convertidos automaticamente:\n\n"
                            + conv["calc_str"] + "\n\n"
                            "---\n\n"
                            f"Barras disponíveis: **{bus_list}**\n\n"
                            "**Quantas linhas a rede terá no total?**\n\n"
                            "(A linha acima já será a Linha 1 — ainda preciso saber de/para qual barra)"
                        )
                    except Exception:
                        pass

            n = _parse_net_int(user_text, 1, 50)
            if n is None:
                return "Quantas linhas a rede terá? Informe um número (ex: **1**, **3**):"
            net3["total"] = n
            net3["idx"] = 0

            # If a prefilled line exists, start by asking its endpoints
            prefilled = data.get("net3_prefilled_line")
            if prefilled:
                net3["current"] = dict(prefilled)
                net3["field"] = "from_bus"
                buses = network.get("buses", [])
                bus_list = ", ".join(str(b["number"]) for b in buses)
                return (
                    f"**Linha 1 de {n} (parâmetros já convertidos da sua LT).**\n\n"
                    f"Barras disponíveis: **{bus_list}**\n\n"
                    "Barra **origem** da linha:"
                )
            net3["field"] = "from_bus"
            net3["current"] = {}
            buses = network.get("buses", [])
            bus_list = ", ".join(str(b["number"]) for b in buses)
            return (
                f"**Linha 1 de {n}.**\n\n"
                f"Barras disponíveis: **{bus_list}**\n\n"
                "Barra **origem** (número, ex: **1**):"
            )

        idx = net3["idx"]
        current = net3.setdefault("current", {})
        buses = network.get("buses", [])
        bus_nums = {b["number"] for b in buses}
        bus_list = ", ".join(str(b["number"]) for b in buses)

        if field == "from_bus":
            n = _parse_net_int(user_text, 1, 99999)
            if n is None or n not in bus_nums:
                return f"Barra origem deve ser um dos números existentes: **{bus_list}**"
            current["from_bus"] = n
            net3["field"] = "to_bus"
            return f"Barra **destino** da linha (barras disponíveis: **{bus_list}**):"

        if field == "to_bus":
            n = _parse_net_int(user_text, 1, 99999)
            if n is None or n not in bus_nums:
                return f"Barra destino deve ser um dos números existentes: **{bus_list}**"
            if n == current.get("from_bus"):
                return "Barra destino deve ser diferente da origem. Informe outro número:"
            current["to_bus"] = n
            net3["field"] = "circuit"
            return "Número do **circuito** (normalmente **1**; use 2, 3 para circuitos paralelos):"

        if field == "circuit":
            c = _parse_net_int(user_text, 1, 9)
            if c is None:
                c_m = re.search(r'\b([1-9])\b', user_text)
                c = int(c_m.group(1)) if c_m else 1
            current["circuit"] = c
            # If this line has pre-filled params (from pending_lt), skip mode/values
            if current.get("r_pct") is not None:
                return _net_finalize_line(data, current)
            net3["field"] = "mode"
            return (
                "**Modo de entrada dos parâmetros:**\n\n"
                "**1** — por km: R(Ω/km), X(Ω/km), B(μS/km) + comprimento\n\n"
                "**2** — pu: R, X, B em por unidade\n\n"
                "**3** — %/Mvar: R%, X%, Q em Mvar (direto para DLIN)"
            )

        if field == "mode":
            mode = _parse_line_mode(user_text)
            if mode is None:
                return "Informe **1** (por km), **2** (pu) ou **3** (%/Mvar):"
            current["param_mode"] = mode
            net3["field"] = "values"
            if mode == "per_km":
                return (
                    "Informe R (Ω/km), X (Ω/km), B (μS/km) e comprimento (km).\n\n"
                    "Exemplo: `R=0.0257 X=0.2995 B=5.4542 L=180`\n"
                    "ou compacto: `0.0257 0.2995 5.4542 180`"
                )
            elif mode == "pu":
                return (
                    "Informe R (pu), X (pu) e B (pu) na base do sistema.\n\n"
                    "Exemplo: `R=0.001 X=0.05 B=0.02`\n"
                    "ou compacto: `0.001 0.05 0.02`"
                )
            else:
                return (
                    "Informe R (%), X (%) e Q (Mvar).\n\n"
                    "Exemplo: `R=0.87 X=10.19 Q=51.93`\n"
                    "ou compacto: `0.87 10.19 51.93`"
                )

        if field == "values":
            mode = current.get("param_mode", "per_km")
            parsed = _parse_four_floats(user_text)
            base_mva = network.get("base_mva", 100.0)
            kv = None
            bus_map = {b["number"]: b for b in buses}
            f_bus = current.get("from_bus")
            if f_bus and f_bus in bus_map:
                kv = bus_map[f_bus].get("kv", 230.0)

            try:
                if mode == "per_km":
                    if isinstance(parsed, dict):
                        r = parsed.get("r", parsed.get("R"))
                        x = parsed.get("x", parsed.get("X"))
                        b = parsed.get("b", parsed.get("B"))
                        L = parsed.get("l", parsed.get("L", parsed.get("length")))
                    else:
                        r, x, b, L = (parsed + [None]*4)[:4]
                    if None in (r, x, b, L):
                        return "Não consegui identificar todos os parâmetros. Exemplo: `R=0.0257 X=0.2995 B=5.4542 L=180`"
                    conv = convert_line_params(kv or 230.0, "per_km", {"R": r, "X": x, "B": b}, L, base_mva)
                elif mode == "pu":
                    if isinstance(parsed, dict):
                        r = parsed.get("r", parsed.get("R"))
                        x = parsed.get("x", parsed.get("X"))
                        b = parsed.get("b", parsed.get("B"))
                    else:
                        r, x, b = (parsed + [None]*3)[:3]
                    if None in (r, x, b):
                        return "Não consegui identificar os parâmetros. Exemplo: `R=0.001 X=0.05 B=0.02`"
                    conv = convert_line_params(kv or 230.0, "pu", {"R": r, "X": x, "B": b}, base_mva=base_mva)
                else:
                    if isinstance(parsed, dict):
                        r = parsed.get("r", parsed.get("R"))
                        x = parsed.get("x", parsed.get("X"))
                        q = parsed.get("q", parsed.get("Q", parsed.get("b", parsed.get("B"))))
                    else:
                        r, x, q = (parsed + [None]*3)[:3]
                    if None in (r, x, q):
                        return "Não consegui identificar os parâmetros. Exemplo: `R=0.87 X=10.19 Q=51.93`"
                    conv = convert_line_params(kv or 230.0, "pct", {"R": r, "X": x, "Q": q}, base_mva=base_mva)

                current["r_pct"] = conv["r_pct"]
                current["x_pct"] = conv["x_pct"]
                current["q_mvar"] = conv["q_mvar"]
                current["calc_str"] = conv["calc_str"]
                return _net_finalize_line(data, current)

            except Exception as exc:
                return f"Erro na conversão: {exc}. Digite `ajuda` para ver o formato esperado."

        return "Não entendi. Digite `ajuda` para orientação."

    # ── NET4_REVIEW ───────────────────────────────────────────────────────────
    if step == "NET4_REVIEW":
        if _net_is_help(user_text):
            return _net_help("NET4_REVIEW") + "\n\n" + _net_show_review(data)

        t = user_text.strip().lower()
        network = data.get("network", {})

        # confirmar
        if any(w in t for w in ["confirmar", "confirma", "ok", "gerar", "continuar", "prosseguir"]):
            issues = validate_network(network)
            errors = [i for i in issues if i["severity"] == "error"]
            if errors:
                return "❌ Há erros que precisam ser corrigidos antes de gerar o arquivo:\n" + "\n".join(
                    f"- {e['message']}" for e in errors
                )
            # Generate PWF
            try:
                pwf_text = build_full_pwf(network)
                data["net_pwf"] = pwf_text
                st.session_state.sim_step = "NET5_GENERATE"
                return (
                    "✅ Arquivo PWF gerado com sucesso!\n\n"
                    "Copie o conteúdo abaixo, salve como **minha_rede.pwf** e abra no ANAREDE:\n\n"
                    f"```\n{pwf_text}\n```\n\n"
                    "Digite **continuar** quando tiver salvo o arquivo."
                )
            except Exception as exc:
                return f"Erro ao gerar o arquivo: {exc}"

        # editar barra N
        m = re.search(r'\beditar\s+barra\s+(\d+)\b', t)
        if m:
            bus_num = int(m.group(1))
            buses = network.get("buses", [])
            bus_map = {b["number"]: b for b in buses}
            if bus_num not in bus_map:
                return f"Barra **{bus_num}** não encontrada. Barras existentes: {[b['number'] for b in buses]}"
            # Remove bus and re-enter NET2 for just this bus (simplified: remove and re-ask)
            network["buses"] = [b for b in buses if b["number"] != bus_num]
            # Remove lines that used this bus
            network["lines"] = [ln for ln in network.get("lines", []) if ln.get("from_bus") != bus_num and ln.get("to_bus") != bus_num]
            # Re-number line ids
            for i, ln in enumerate(network["lines"]):
                ln["id"] = i + 1
            st.session_state.sim_step = "NET2_BUSES"
            existing_count = len(network["buses"])
            data["net2"] = {
                "total": existing_count + 1,
                "idx": existing_count,
                "field": "number",
                "current": {"number": bus_num},
            }
            data["net2"]["current"]["number"] = bus_num
            data["net2"]["field"] = "name"
            return (
                f"Barra **{bus_num}** removida para reedição. "
                f"As linhas que usavam essa barra também foram removidas.\n\n"
                f"**Redigitando barra {bus_num}:**\n\nNome da barra (ex: **SE_{bus_num}**):"
            )

        # editar linha N
        m = re.search(r'\beditar\s+linha\s+(\d+)\b', t)
        if m:
            ln_id = int(m.group(1))
            lines = network.get("lines", [])
            if not any(ln["id"] == ln_id for ln in lines):
                return f"Linha **{ln_id}** não encontrada."
            network["lines"] = [ln for ln in lines if ln["id"] != ln_id]
            for i, ln in enumerate(network["lines"]):
                ln["id"] = i + 1
            st.session_state.sim_step = "NET3_LINES"
            remaining = len(network["lines"])
            data["net3"] = {"total": remaining + 1, "idx": remaining, "field": "from_bus", "current": {}}
            buses = network.get("buses", [])
            bus_list = ", ".join(str(b["number"]) for b in buses)
            return (
                f"Linha **{ln_id}** removida. Redigitando:\n\n"
                f"Barras disponíveis: **{bus_list}**\n\nBarra **origem**:"
            )

        # remover linha N
        m = re.search(r'\bremover\s+linha\s+(\d+)\b', t)
        if m:
            ln_id = int(m.group(1))
            lines = network.get("lines", [])
            if not any(ln["id"] == ln_id for ln in lines):
                return f"Linha **{ln_id}** não encontrada."
            network["lines"] = [ln for ln in lines if ln["id"] != ln_id]
            for i, ln in enumerate(network["lines"]):
                ln["id"] = i + 1
            return "Linha removida.\n\n" + _net_show_review(data)

        # adicionar barra
        if "adicionar barra" in t:
            buses = network.get("buses", [])
            existing = len(buses)
            st.session_state.sim_step = "NET2_BUSES"
            data["net2"] = {"total": existing + 1, "idx": existing, "field": "number", "current": {}}
            return "Adicionando nova barra.\n\nNúmero da nova barra (1 a 99999):"

        # adicionar linha
        if "adicionar linha" in t:
            lines = network.get("lines", [])
            existing = len(lines)
            buses = network.get("buses", [])
            bus_list = ", ".join(str(b["number"]) for b in buses)
            st.session_state.sim_step = "NET3_LINES"
            data["net3"] = {"total": existing + 1, "idx": existing, "field": "from_bus", "current": {}}
            return f"Adicionando nova linha.\n\nBarras disponíveis: **{bus_list}**\n\nBarra **origem**:"

        return _net_show_review(data)

    # ── NET5_GENERATE ─────────────────────────────────────────────────────────
    if step == "NET5_GENERATE":
        if _net_is_help(user_text):
            return _net_help("NET5_GENERATE") + "\n\nDigite **continuar** quando tiver salvo o arquivo."
        t = user_text.strip().lower()
        if any(w in t for w in ["continuar", "ok", "salvo", "salvei", "pronto", "sim"]):
            st.session_state.sim_step = "NET6_RUN"
            return _net6_prompt(data)
        # Re-show PWF if asked
        pwf = data.get("net_pwf", "")
        return (
            "O arquivo PWF:\n\n"
            f"```\n{pwf}\n```\n\n"
            "Digite **continuar** quando tiver salvo."
        )

    # ── NET6_RUN ──────────────────────────────────────────────────────────────
    if step == "NET6_RUN":
        if _net_is_help(user_text):
            return _net_help("NET6_RUN") + "\n\nO que aparece no canto superior direito do ANAREDE?"

        # Check convergence from user's report
        if _is_converged(user_text):
            data["net7_color"] = "green"
            st.session_state.sim_step = "NET7_RESULTS"
            return _net7_converged_prompt(data)
        if _is_not_converged(user_text):
            color = "yellow" if "amarelo" in user_text.lower() else "red" if "vermelho" in user_text.lower() else None
            data["net7_color"] = color or "unknown"
            st.session_state.sim_step = "NET7_RESULTS"
            return _net7_not_converged(data)

        return "O que aparece no canto superior direito do ANAREDE após executar o fluxo?"

    # ── NET7_RESULTS ──────────────────────────────────────────────────────────
    if step == "NET7_RESULTS":
        if _net_is_help(user_text):
            return _net_help("NET7_RESULTS")

        t = user_text.strip().lower()
        color = data.get("net7_color", "unknown")

        # Not yet classified — detect color
        if color == "unknown":
            if "vermelho" in t or "divergiu" in t:
                data["net7_color"] = "red"
                return _net7_not_converged(data)
            if "amarelo" in t or "iteraç" in t or "limite" in t:
                data["net7_color"] = "yellow"
                return _net7_not_converged(data)
            if _is_converged(user_text):
                data["net7_color"] = "green"
                return _net7_converged_prompt(data)
            return (
                "O que aparece no canto superior direito?\n\n"
                "- **Verde**: convergido\n- **Amarelo**: limite de iterações\n- **Vermelho**: divergiu"
            )

        if color == "green":
            # Handle post-results choices
            if any(w in t for w in ["bess", "inserir bess", "adicionar bess"]):
                # Transition to BESS flow using this network as base
                # OPEN QUESTION: exact flow for inserting BESS into a fresh PWF case
                return (
                    "**QUESTÃO ABERTA:** A inserção de BESS em um caso gerado do zero "
                    "(sem SAV base existente) requer confirmação do fluxo no manual do ANAREDE. "
                    "Por ora, salve o caso como SAV no ANAREDE e use o fluxo BESS normal a partir do SAV.\n\n"
                    "Deseja encerrar ou continuar com outro cenário?"
                )
            if any(w in t for w in ["statcom"]):
                return (
                    "**QUESTÃO ABERTA:** Mesmo que o BESS — inserção de STATCOM em caso do zero. "
                    "Salve como SAV e use o fluxo STATCOM normal.\n\n"
                    "Deseja encerrar ou continuar?"
                )
            if any(w in t for w in ["contingência", "contingencia", "n-1", "n1"]):
                # Jump to STEP11B contingency flow with NETWORK context
                st.session_state.sim_step = "STEP11B"
                return (
                    "Iniciando análise de contingências N-1.\n\n"
                    "Quais linhas deseja incluir? Informe no formato:\n"
                    "- `linha 1-2 circuito 1`\n- `gerador barra 1`"
                )
            if any(w in t for w in ["encerrar", "fim", "finalizar", "terminar"]):
                st.session_state.sim_step = "IDLE"
                st.session_state.sim_data = {}
                st.session_state.simulation_mode = False
                st.session_state.sim_status = None
                return "Sessão encerrada. O arquivo PWF foi gerado com sucesso. Se precisar de mais ajuda, é só perguntar."
            return _net7_converged_prompt(data)

        # Not converged — handle edit redirect
        if any(w in t for w in ["editar", "corrigir", "voltar", "net4", "revisar"]):
            st.session_state.sim_step = "NET4_REVIEW"
            return "Voltando à revisão da rede.\n\n" + _net_show_review(data)
        if any(w in t for w in ["encerrar", "fim", "finalizar"]):
            st.session_state.sim_step = "IDLE"
            st.session_state.sim_data = {}
            st.session_state.simulation_mode = False
            st.session_state.sim_status = None
            return "Sessão encerrada."

        return _net7_not_converged(data)

    return None


def _net6_prompt(data: dict) -> str:
    """Return the NET6_RUN prompt explaining how to load the PWF."""
    # OPEN QUESTION: exact ANAREDE menu path for opening a new PWF file
    return (
        "Ótimo! Arquivo salvo.\n\n"
        "**Para carregar no ANAREDE:**\n\n"
        "⚠️ **QUESTÃO ABERTA:** O caminho exato de menu para abrir um arquivo PWF novo no ANAREDE "
        "não foi confirmado pelo manual indexado — não será inventado aqui.\n\n"
        "Instrução geral baseada no uso típico do ANAREDE:\n"
        "1. Abra o ANAREDE\n"
        "2. Procure no menu principal a opção para abrir/carregar um arquivo de rede\n"
        "3. Selecione o arquivo `.pwf` que você salvou\n"
        "4. Após carregar, execute o fluxo de potência com **Ctrl+R**\n\n"
        "O que aparece no canto superior direito do ANAREDE após executar o fluxo?\n\n"
        "- **Verde**: convergido ✅\n"
        "- **Amarelo**: limite de iterações — não convergiu\n"
        "- **Vermelho**: divergiu"
    )


def _net7_converged_prompt(data: dict) -> str:
    network = data.get("network", {})
    n_buses = len(network.get("buses", []))
    n_lines = len(network.get("lines", []))
    return (
        "✅ **O caso convergiu!**\n\n"
        f"Sua rede com **{n_buses} barras** e **{n_lines} linhas** foi calculada com sucesso.\n\n"
        "**Como interpretar os resultados:**\n"
        "- Tensões de barra aparecem próximas a cada barra no diagrama (em pu ou kV)\n"
        "- Fluxos de linha aparecem nas extremidades (MW e Mvar)\n"
        "- Hachura **VERMELHA**: sobrecarga ou sobretensão\n"
        "- Hachura **AZUL**: subtensão\n\n"
        "**Para salvar o caso:** ⚠️ QUESTÃO ABERTA — o procedimento exato para criar um SAV "
        "a partir deste caso precisa ser confirmado com o manual do ANAREDE.\n\n"
        "**Próximos passos disponíveis:**\n"
        "- `inserir BESS` — adicionar bateria ao caso\n"
        "- `inserir STATCOM` — adicionar compensador reativo\n"
        "- `contingências` ou `n-1` — análise de contingências\n"
        "- `encerrar` — finalizar"
    )


def _net7_not_converged(data: dict) -> str:
    network = data.get("network", {})
    color = data.get("net7_color", "unknown")
    checklist = diagnose_nonconvergence(network, color)
    checklist_str = "\n\n".join(checklist)
    return (
        "❌ **O caso não convergiu.**\n\n"
        "**Diagnóstico para esta rede:**\n\n"
        + checklist_str
        + "\n\n---\n\n"
        "**Opções:**\n"
        "- `editar rede` — voltar à revisão para corrigir parâmetros\n"
        "- `encerrar` — finalizar\n\n"
        "⚠️ *Diagnóstico gerado automaticamente — PENDENTE REVISÃO POR ESPECIALISTA (Thomas).*"
    )


# ── LT implicit-intent detection ──────────────────────────────────────────────

_LT_PARAM_SIGS = [
    r"\bR\s*[=:]\s*\d",
    r"\bX\s*[=:]\s*\d",
    r"\bB\s*[=:]\s*\d",
    r"\d[.,]\d+\s*ohm",
    r"\d[.,]\d+\s*(?:μS|uS|µS)",
    r"\b\d+\s*km\b",
    r"\b\d{2,3}\s*kV\b",
]

_LT_CONTEXT_SIGS = [
    r"\banarede\b",
    r"\bdlin\b",
    r"\bdbar\b",
    r"\blinha\s+de\s+transmiss",
    r"\bLT\b",
    r"\bintegr[ao]",
    r"\bmodel[ao]",
    r"\binserir?\b",
    r"\bsimul[ao]",
]


def _is_lt_data_message(text: str) -> bool:
    """Return True if the message looks like raw transmission-line parameter data."""
    param_hits = sum(1 for p in _LT_PARAM_SIGS if re.search(p, text, re.IGNORECASE))
    if param_hits < 2:
        return False
    context_hits = sum(1 for p in _LT_CONTEXT_SIGS if re.search(p, text, re.IGNORECASE))
    # ≥2 param signals + ≥1 context keyword is sufficient.
    # Require ≥3 param signals when no context keyword, to avoid false positives
    # on generic questions that merely mention kV and km.
    return context_hits >= 1 or param_hits >= 3


def _parse_lt_params(text: str) -> dict:
    """Extract LT physical parameters from a message; returns whatever was found."""
    params: dict = {}
    m = re.search(r"\b(\d{2,3})\s*kV\b", text, re.IGNORECASE)
    if m:
        params["voltage_kv"] = float(m.group(1))
    m = re.search(r"\b(\d+(?:[.,]\d+)?)\s*km\b", text, re.IGNORECASE)
    if m:
        params["length_km"] = float(m.group(1).replace(",", "."))
    m = re.search(r"\bR\s*[=:]\s*(\d+(?:[.,]\d+)?)", text, re.IGNORECASE)
    if m:
        params["R_ohm_km"] = float(m.group(1).replace(",", "."))
    m = re.search(r"\bX\s*[=:]\s*(\d+(?:[.,]\d+)?)", text, re.IGNORECASE)
    if m:
        params["X_ohm_km"] = float(m.group(1).replace(",", "."))
    m = re.search(r"\bB\s*[=:]\s*(\d+(?:[.,]\d+)?)", text, re.IGNORECASE)
    if m:
        params["B_us_km"] = float(m.group(1).replace(",", "."))
    return params


def _format_lt_params(params: dict) -> str:
    """Format detected LT parameters as a compact readable string."""
    parts = []
    if "voltage_kv" in params:
        parts.append(f"{int(params['voltage_kv'])} kV")
    if "length_km" in params:
        parts.append(f"{params['length_km']} km")
    if "R_ohm_km" in params:
        parts.append(f"R = {params['R_ohm_km']} Ω/km")
    if "X_ohm_km" in params:
        parts.append(f"X = {params['X_ohm_km']} Ω/km")
    if "B_us_km" in params:
        parts.append(f"B = {params['B_us_km']} μS/km")
    return ", ".join(parts)


def _parse_years(text: str) -> list[int]:
    """Return list of years found in text."""
    return [int(y) for y in re.findall(r"\b(20\d\d)\b", text)]


def _normalize_str(s: str) -> str:
    """Lowercase, strip accents, collapse non-alphanumeric to spaces."""
    s = s.lower()
    nfkd = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in nfkd if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_scenario(text: str, db: str):
    lookup = _PARPEL_SCENARIO_NAMES if db in ("ONS", "PARPEL") else _PDE_SCENARIO_NAMES

    # Step 1: extract a digit (1–6 PAR/PEL, 1–8 PDE) anywhere in the message
    max_n = "6" if db in ("ONS", "PARPEL") else "8"
    digit_match = re.search(r"\b([1-" + max_n + r"])\b", text.strip())
    if digit_match and digit_match.group(1) in lookup:
        return lookup[digit_match.group(1)]

    # Step 2: normalize input and each scenario name, then try substring
    # match and word-subset match (handles partial names and missing accents)
    norm_input = _normalize_str(text)
    for key, name in lookup.items():
        if key.isdigit():
            continue
        norm_key = _normalize_str(key)
        if norm_key in norm_input:
            return name
        # Partial match: every word the user typed appears in the scenario name
        input_words = set(norm_input.split())
        if input_words and input_words.issubset(set(norm_key.split())):
            return name

    return None


def _sav_filename_hint(db: str, scenario: str, year: int) -> str:
    if db in ("ONS", "PARPEL"):
        return (
            f"Procure pelo arquivo SAV: **{year}.SAV**\n\n"
            "No ANAREDE:\n"
            "1. Vá em **Histórico > Operações**\n"
            f"2. Selecione o caso correspondente ao cenário **{scenario}**\n"
            "3. Clique em **Restabelecer**\n\n"
            "Após carregar, verifique o canto superior direito do ANAREDE. "
            "O caso base já vem convergido — deve aparecer um quadrado **VERDE** "
            "com o texto 'Convergido'.\n\n"
            "O que aparece no canto superior direito?"
        )
    else:
        pde_ref = {
            "Máxima Diurna Seco":     f"{year}_1. PD 2035 - MÁXIMA DIURNA SECO.PWF",
            "Máxima Diurna Úmido":    f"{year}_2. PD 2035 - MÁXIMA DIURNA ÚMIDO.PWF",
            "Máxima Noturna Seco":    f"{year}_3. PD 2035 - MÁXIMA NOTURNA SECO.PWF",
            "Máxima Noturna Úmido":   f"{year}_4. PD 2035 - MÁXIMA NOTURNA ÚMIDO.PWF",
            "Mínima Noturna Seco":    f"{year}_5. PD 2035 - MÍNIMA NOTURNA SECO.PWF",
            "Mínima Noturna Úmido":   f"{year}_6. PD 2035 - MÍNIMA NOTURNA ÚMIDO.PWF",
            "Máxima Coincidente SIN": f"{year}_7. PD 2035 - MÁXIMA COINCIDENTE SIN.PWF",
            "Mínima Líquida Diurna":  f"{year}_8. PD 2035 - MÍNIMA LÍQUIDA DIURNA.PWF",
        }
        pwf_ref = pde_ref.get(scenario, f"{year} {scenario}.PWF")
        return (
            f"Para carregar o caso base, utilize o arquivo SAV correspondente "
            f"ao ano **{year}** da base PDE 2035.\n\n"
            "⚠️ **IMPORTANTE: Sempre carregue o arquivo SAV, não o PWF.**\n"
            "- O SAV já vem convergido\n"
            "- No ANAREDE: **Histórico > Operações** > selecione o caso "
            f"**{scenario}** > clique em **Restabelecer**\n"
            f"- O arquivo PWF (`{pwf_ref}`) existe na base mas serve apenas "
            "como referência — para simulação sempre prefira o SAV\n\n"
            "Após carregar e restabelecer o cenário, o que aparece no canto "
            "superior direito do ANAREDE?"
        )


def _is_converged(text: str) -> bool:
    t = text.lower()
    neg = any(w in t for w in ["não ", "nao ", "n convergiu", "n convergido"])
    pos = any(w in t for w in ["convergido", "convergiu", "verde", "converge"])
    return pos and not neg


def _is_not_converged(text: str) -> bool:
    t = text.lower()
    return any(w in t for w in [
        "não convergido", "nao convergido", "não convergiu", "nao convergiu",
        "amarelo", "vermelho", "não converge", "nao converge",
    ])


def _parse_bess_mode(text: str):
    t = text.strip().lower()
    if t == "1" or any(w in t for w in ["pv", "tensão", "tensao", "controle", "gfm"]):
        return "PV"
    if t == "2" or any(w in t for w in ["pq", "despacho fixo", "fixo"]):
        return "PQ"
    return None


def _parse_mva(text: str):
    # Require an explicit MVA unit to avoid grabbing unrelated numbers (kV, km, etc.)
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:mva|MW|MVA)\b", text, re.IGNORECASE)
    if m:
        return m.group(1).replace(",", ".")
    # Bare number only when the entire message is a single numeric token
    m = re.search(r"^\s*(\d+(?:[.,]\d+)?)\s*$", text.strip())
    if m:
        return m.group(1).replace(",", ".")
    return None


def _parse_active_power(text: str):
    """Extract active power P (MW) from phrases like 'potência ativa 80 MW' or 'P=80'."""
    m = re.search(
        r"(?:pot[eê]ncia\s+ativa|ativa)[^\d]*(\d+(?:[.,]\d+)?)",
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1).replace(",", ".")
    m = re.search(r"\bp\s*[=:]\s*(\d+(?:[.,]\d+)?)", text, re.IGNORECASE)
    if m:
        return m.group(1).replace(",", ".")
    return None


def _bess_pwf_lines(data: dict) -> str:
    bus_from   = data.get("bess_bus", "")         # existing bus (bus_from)
    bus_to     = data.get("bess_bus_number", "")  # new BESS bus (bus_to)
    mva        = data.get("bess_mva", "100")
    mode_type  = "1" if data.get("bess_mode") == "PV" else "0"
    try:
        s = float(mva)
    except Exception:
        s = 100.0
    try:
        p = float(data["bess_p_mw"]) if data.get("bess_p_mw") is not None else 0.0
    except Exception:
        p = 0.0

    # DBAR + DLIN + FIM — generated entirely by anarede_lib, no LLM involvement
    pwf_block = generate_dbar_block(
        bus_number=bus_from,
        bess_bus_number=bus_to,
        bus_type=mode_type,
        S_mva=s,
        P_mw=p,
    )
    return (
        "Copie as linhas abaixo em um editor de texto (ex: Bloco de Notas), "
        "salve como **BESS_modificacao.pwf** e carregue no ANAREDE:\n\n"
        f"```\n"
        f"{pwf_block}\n"
        f"```\n\n"
        "Após inserir a BESS, o quadrado no canto superior direito mudará para "
        "**amarelo** ('Não Convergido'). Isso é normal."
    )


def extract_sim_context(message: str) -> dict:
    """
    Scan a single message for signals from multiple simulation steps.
    Returns a dict with keys:
      convergence: 'green' | 'red' | None
      lst:         'existing' | 'new' | None
      bus_number:  str | None
      bess_mode:   'PV' | 'PQ' | None
    """
    t = message.lower()

    # Convergence
    if _is_converged(message):
        convergence = "green"
    elif _is_not_converged(message):
        convergence = "red"
    else:
        convergence = None

    # LST
    existing_signals = ["tenho", "existe", "já tenho", "ja tenho", "tenho lst",
                        "carreguei", "existente", "tenho o arquivo", "tenho um"]
    new_signals = ["não tenho", "nao tenho", "desenhar", "novo", "criar",
                   "não tenho lst", "nao tenho lst"]
    if any(s in t for s in new_signals):
        lst = "new"
    elif any(s in t for s in existing_signals):
        lst = "existing"
    else:
        lst = None

    # Bus number
    bus_match = re.search(r"\b(?:barramento|mesma\s+barra|barra)\s+(\d{4,5})\b", t)
    if bus_match:
        bus_number = bus_match.group(1)
    else:
        bus_match = re.search(r"(?<![.,\d])(\d{4,5})\b", message)
        bus_number = bus_match.group(1) if bus_match else None

    # BESS mode
    bess_mode = _parse_bess_mode(message)

    # S_mva — number immediately followed by "mva"
    mva_match = re.search(r"(\d+(?:[.,]\d+)?)\s*mva", t)
    S_mva = float(mva_match.group(1).replace(",", ".")) if mva_match else None

    # P_mw — use existing helper first, then "N mw" standalone when S_mva present
    p_mw_str = _parse_active_power(message)
    if p_mw_str is None:
        mw_match = re.search(r"(\d+(?:[.,]\d+)?)\s*mw\b", t)
        if mw_match and (mva_match is None or mw_match.start() != mva_match.start()):
            p_mw_str = mw_match.group(1).replace(",", ".")
    P_mw = float(p_mw_str.replace(",", ".")) if p_mw_str else None

    return {
        "convergence": convergence,
        "lst": lst,
        "bus_number": bus_number,
        "bess_mode": bess_mode,
        "S_mva": S_mva,
        "P_mw": P_mw,
    }


def _parse_q_limits(text: str):
    """Parse Qmin and Qmax from text. Returns (q_min, q_max) or (None, None)."""
    m_min = re.search(r"q(?:min|m[íi]n)[:\s]+(-?\d+(?:[.,]\d+)?)", text, re.IGNORECASE)
    m_max = re.search(r"q(?:max|m[áa]x)[:\s]+(-?\d+(?:[.,]\d+)?)", text, re.IGNORECASE)
    if m_min and m_max:
        return float(m_min.group(1).replace(",", ".")), float(m_max.group(1).replace(",", "."))
    # Try "-60 a 60" or "-60/60"
    m = re.search(r"(-?\d+(?:[.,]\d+)?)\s*(?:a|/)\s*(\d+(?:[.,]\d+)?)", text)
    if m:
        return float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
    return None, None


def _is_free_question(text: str) -> bool:
    """Return True if the message looks like a free technical question, not a simulation step answer."""
    t = text.strip()
    if t.endswith("?"):
        return True
    tl = t.lower()
    _STARTERS = [
        "o que é", "o que são", "o que significa", "o que faz",
        "como funciona", "como é", "como se", "como fazer", "como posso",
        "por que", "porque", "qual é a diferença", "quais são",
        "me explique", "explique", "me fale sobre", "fale sobre",
        "você pode explicar", "pode me explicar", "pode me dizer",
    ]
    return any(tl.startswith(s) for s in _STARTERS)


def _current_step_question() -> str:
    """Return the question for the CURRENT simulation step.

    Derived live from ``sim_step`` (and the relevant ``sim_data`` sub-state)
    every time it is called, so pause/resume nudges always reflect where the
    simulation actually is — never a value cached when pause was first entered.
    """
    step = st.session_state.sim_step
    data = st.session_state.sim_data
    db = data.get("db", "ONS")
    sim_type = data.get("sim_type", "BESS")
    device_label = "STATCOM" if sim_type == "STATCOM" else "BESS"

    if step == "IDLE_LT_CONFIRM":
        return (
            "Você quer que eu te guie pelo processo de inserção no ANAREDE?\n\n"
            "1. **Sim** — iniciar simulação guiada\n\n"
            "2. **Não** — só quero uma resposta técnica"
        )
    if step == "IDLE_LT_NET_CHOICE":
        return (
            "Como deseja usar os dados desta linha?\n\n"
            "**1.** Montar uma rede nova do zero\n\n"
            "**2.** Inserir BESS/STATCOM em caso PAR/PEL/PDE existente"
        )
    if step == "NET1_SETUP":
        net = data.get("network", {})
        return (
            f"Título: **{net.get('title','Meu Caso')}** | Base: **{net.get('base_mva',100)} MVA**\n\n"
            "Informe novo título e base MVA, ou **confirmar** para manter."
        )
    if step == "NET2_BUSES":
        net2 = data.get("net2", {})
        field = net2.get("field", "count")
        total = net2.get("total")
        idx = net2.get("idx", 0)
        if field == "count" or total is None:
            return "**Quantas barras a rede terá?** (mínimo 2, máximo 20)"
        current = net2.get("current", {})
        prompts = {
            "number": f"**Barra {idx+1} de {total}.** Número da barra (1 a 99999):",
            "name": f"Nome da barra **{current.get('number','')}** (até 12 caracteres):",
            "kv": f"Tensão nominal de **{current.get('name','')}** em kV:",
            "tipo": "Tipo: **0** PQ / **1** PV / **2** Referência:",
            "pg": "Geração ativa em MW:",
            "v_pu": "Tensão setpoint em pu:",
            "qmin": "Qmin em Mvar:",
            "qmax": "Qmax em Mvar:",
            "pl": "Carga ativa em MW:",
            "ql": "Carga reativa em Mvar:",
        }
        return prompts.get(field, "Continue com os dados da barra.")
    if step == "NET3_LINES":
        net3 = data.get("net3", {})
        field = net3.get("field", "count")
        total = net3.get("total")
        idx = net3.get("idx", 0)
        if field == "count" or total is None:
            return "**Quantas linhas a rede terá?**"
        prompts = {
            "from_bus": f"**Linha {idx+1} de {total}.** Barra **origem**:",
            "to_bus": "Barra **destino**:",
            "circuit": "Número do **circuito** (normalmente 1):",
            "mode": "Modo: **1** por km / **2** pu / **3** %/Mvar:",
            "values": "Informe os parâmetros:",
        }
        return prompts.get(field, "Continue com os dados da linha.")
    if step == "NET4_REVIEW":
        return "**Revisão da rede.** Digite `confirmar` para gerar o PWF."
    if step == "NET5_GENERATE":
        return "Arquivo gerado. Digite **continuar** quando tiver salvo."
    if step == "NET6_RUN":
        return "O que aparece no canto superior direito do ANAREDE?"
    if step == "NET7_RESULTS":
        return "O que você observa? Digite `encerrar`, `inserir BESS`, `contingências` ou `editar rede`."
    if step == "STEP1":
        return (
            "**Qual base de dados deseja utilizar?**\n\n"
            "1. **EPE (PDE)**\n\n"
            "2. **ONS (PAR/PEL)**\n\n"
            "3. **Minha própria rede** (montar do zero)"
        )
    if step == "STEP2":
        return (
            "**Qual ano (ou anos) deseja estudar?** "
            "(ex: **2028** ou **2027, 2028, 2029**)"
        )
    if step == "STEP3":
        return _PARPEL_SCENARIOS if db == "ONS" else _PDE_SCENARIOS
    if step == "STEP4":
        return "O que aparece no canto superior direito do ANAREDE após carregar o caso?"
    if step == "STEP6":
        return (
            "Para visualizar a região de estudo: **Opção A** — carregar um arquivo "
            "LST (**Diagrama > Carregar**); **Opção B** — desenhar com o ícone do "
            "**lápis**. Qual opção você vai utilizar?"
        )
    if step == "STEP7":
        if sim_type == "BESS" and "bess_bus" in data:
            return (
                "**Qual o modo de operação da BESS?**\n\n"
                "1. **Controle de tensão (barra PV — tipo 2)**\n\n"
                "2. **Despacho fixo (barra PQ — tipo 1)**"
            )
        return f"Qual é a barra onde deseja inserir o {device_label}?"
    if step == "STEP8":
        if "bess_mva" not in data:
            return "**Qual a potência nominal da BESS em MVA?**"
        if "bess_p_mw" not in data:
            return "**Qual a potência ativa em MW?**"
        return (
            "Qual número de barra está disponível no seu caso para a nova barra "
            "da BESS? (escolha um número que não exista no caso atual)"
        )
    if step == "STATCOM_STEP_Q":
        return (
            "**Qual a capacidade reativa do STATCOM?** Informe Qmin e Qmax em "
            "Mvar (ex: `Qmin -100 Mvar, Qmax 100 Mvar`)."
        )
    if step == "STATCOM_STEP_CBUS":
        return (
            "**O STATCOM vai controlar a tensão da própria barra ou de uma barra "
            "remota?**\n\n1. **Barra local (padrão)**\n\n2. **Barra remota** "
            "(informe o número da barra a controlar)"
        )
    if step == "STEP9":
        return "Confirme quando o caso estiver salvo no ANAREDE (responda **salvo** ou **pronto**)."
    if step == "STEP10":
        return "O que aparece no canto superior direito do ANAREDE após rodar o fluxo?"
    if step == "STEP11":
        return "O que você está observando no diagrama?"
    if step == "STEP11B":
        stage = data.get("contingency_stage")
        if stage == "guide":
            return (
                "Informe as linhas ou geradores para a análise N-1 "
                "(ex: `linha 1001-1002 circuito 1` ou `gerador barra 1005`)."
            )
        if stage == "done":
            return (
                "**Executar agora** (Ctrl+E), **adicionar mais** contingências "
                "ou **encerrar contingências**?"
            )
        if stage == "awaiting_results":
            return "O que aparece no relatório de contingências e no diagrama?"
        return "Deseja realizar análise de contingências N-1? Responda **Sim** ou **Não**."
    if step == "STEP12":
        return (
            "Deseja continuar com outro cenário ou patamar de carga?\n\n"
            "- Responda com o **nome ou número do cenário** para ir direto\n"
            "- Informe um **novo ano** (2026–2040) para trocar o horizonte\n"
            "- Digite **encerrar** para finalizar a sessão de simulação"
        )
    return ""


def _handle_sim_state(user_text: str) -> str | None:
    """
    Drive the simulation state machine.
    Returns a template response string, or None if the LLM should answer.
    """
    step = st.session_state.sim_step
    data = st.session_state.sim_data

    # If simulation is paused, only IDLE intent detection should work
    if st.session_state.sim_status == "paused" and step != "IDLE":
        # Allow encerrar even while paused
        t_lower = user_text.lower()
        _ENCERRAR = ["encerrar", "finalizar", "terminar"]
        if any(s in t_lower for s in _ENCERRAR):
            st.session_state.simulation_mode = False
            st.session_state.sim_step = "IDLE"
            st.session_state.sim_data = {}
            st.session_state.sim_status = None
            try:
                clear_paused_state(st.session_state["session_id"])
            except Exception:
                pass
            return (
                "Sessão de simulação encerrada.\n\n"
                "Se precisar retomar ou tiver dúvidas sobre o SIN, é só perguntar."
            )
        return None  # Let LLM handle while paused

    # If mid-simulation and user asked a free question, let LLM handle it
    # (simulation state is preserved; ↩️ reminder appended by the LLM branch)
    # IDLE_LT_CONFIRM is excluded: it handles free questions internally (abandons
    # the LT confirmation and routes cleanly to the LLM).
    if (step not in ("IDLE", "IDLE_LT_CONFIRM", "STEP12")
            and not step.startswith("NET")
            and not step == "IDLE_LT_NET_CHOICE"
            and _is_free_question(user_text)):
        return None

    # ── Global: encerrar / restart checks (before any step logic) ─────────────
    t_lower = user_text.lower()
    _ENCERRAR = ["encerrar", "finalizar", "terminar", "fim", "sair", "encerra", "finaliza"]
    if step not in ("IDLE", "STEP12") and any(s in t_lower for s in _ENCERRAR):
        st.session_state.simulation_mode = False
        st.session_state.sim_step = "IDLE"
        st.session_state.sim_data = {}
        st.session_state.sim_status = None
        try:
            clear_paused_state(st.session_state["session_id"])
        except Exception:
            pass
        return (
            "Sessão de simulação encerrada. Os resultados ficam registrados no histórico acima.\n\n"
            "Se precisar retomar ou tiver dúvidas sobre o SIN, é só perguntar."
        )

    _RESTART = [
        "quero simular", "iniciar simulação", "nova simulação",
        "começar de novo", "quero inserir um bess", "quero inserir um statcom",
    ]
    if step not in ("IDLE",) and any(s in t_lower for s in _RESTART):
        _restart_type = "STATCOM" if "statcom" in t_lower else "BESS"
        st.session_state.sim_data = {"sim_type": _restart_type}
        st.session_state.sim_step = "STEP1"
        st.session_state.simulation_mode = True
        st.session_state.sim_status = "active"
        return (
            "Reiniciando a simulação do zero!\n\n"
            "Antes de começarmos, você vai precisar baixar os arquivos da base "
            "de dados. Existem duas fontes principais:\n\n"
            "📥 **PAR/PEL (ONS)** — planejamento operacional, horizonte de 5 anos.\n\n"
            "📥 **PDE (EPE)** — planejamento de expansão, horizonte de 10 anos.\n\n"
            "**Qual base de dados deseja utilizar?**\n\n"
            "1. **EPE (PDE)** — planejamento de expansão de longo prazo (~10 anos)\n\n"
            "2. **ONS (PAR/PEL)** — planejamento operacional de médio prazo (~5 anos)"
        )

    # ── IDLE: check for simulation intent ─────────────────────────────────────
    if step == "IDLE":
        if _is_network_intent(user_text):
            if st.session_state.sim_status == "paused":
                try:
                    clear_paused_state(st.session_state["session_id"])
                except Exception:
                    pass
            st.session_state.simulation_mode = True
            st.session_state.sim_status = "active"
            st.session_state.sim_step = "NET1_SETUP"
            data["sim_type"] = "NETWORK"
            data["network"] = {"title": "Meu Caso", "base_mva": 100.0, "buses": [], "lines": []}
            return (
                "Ótimo! Vou te guiar para montar uma rede do zero no ANAREDE.\n\n"
                "Precisarei de:\n"
                "1. **Título e base MVA** do caso\n"
                "2. **Dados de cada barra** (número, nome, tensão, tipo, cargas/geração)\n"
                "3. **Parâmetros de cada linha** (R, X, B — aceito Ω/km, pu ou % diretamente)\n\n"
                "Ao final, gero o arquivo `.pwf` completo pronto para o ANAREDE.\n\n"
                "---\n\n"
                "**Qual o título deste caso e a potência base?**\n\n"
                "Exemplo: `LT 230kV Teste, 100 MVA`\n\n"
                "Ou apenas pressione **confirmar** para usar os padrões (título: 'Meu Caso', base: 100 MVA)."
            )
        if _is_simulation_intent(user_text):
            # Clear any paused state when starting fresh
            if st.session_state.sim_status == "paused":
                try:
                    clear_paused_state(st.session_state["session_id"])
                except Exception:
                    pass
            st.session_state.simulation_mode = True
            st.session_state.sim_status = "active"
            st.session_state.sim_step = "STEP1"
            data["sim_type"] = "STATCOM" if "statcom" in user_text.lower() else "BESS"
            return (
                "Ótimo! Vou te guiar pelo processo de simulação passo a passo.\n\n"
                "Antes de começarmos, você vai precisar baixar os arquivos da base "
                "de dados. Existem duas fontes principais:\n\n"
                "📥 **PAR/PEL (ONS)** — planejamento operacional, horizonte de 5 anos. "
                "Base lançada no início do ano com revisões ao longo do ano. "
                "Acesso via Portal SINTEGRE (cadastro gratuito):\n"
                "https://www.ons.org.br/topo/acesso-restrito\n\n"
                "📥 **PDE (EPE)** — planejamento de expansão, horizonte de 10 anos. "
                "Download público direto, sem cadastro:\n"
                "https://www.epe.gov.br/pt/areas-de-atuacao/energia-eletrica/planejamento-da-transmissao/bases-de-dados-de-simulacao\n\n"
                "Você pode ir baixando enquanto respondemos as próximas perguntas.\n\n"
                "---\n\n"
                "**Qual base de dados deseja utilizar?**\n\n"
                "1. **EPE (PDE)** — foco em planejamento de expansão de longo prazo, "
                "horizonte de ~10 anos. Modelos com maior incerteza sobre o futuro.\n\n"
                "2. **ONS (PAR/PEL)** — foco em planejamento operacional de médio prazo, "
                "horizonte de ~5 anos. Modelos mais detalhados e confiáveis para "
                "decisões operativas.\n\n"
                "Para estudos de inserção de tecnologias como BESS no SIN, o "
                "PAR/PEL do ONS é geralmente preferível por ter modelos mais detalhados."
            )
        if _is_lt_data_message(user_text):
            pending_lt = _parse_lt_params(user_text)
            data["pending_lt"] = pending_lt
            data["pending_question"] = user_text
            st.session_state.sim_step = "IDLE_LT_CONFIRM"
            lt_summary = _format_lt_params(pending_lt)
            detected_str = f": **{lt_summary}**" if lt_summary else ""
            return (
                f"Identifiquei parâmetros de linha de transmissão na sua mensagem{detected_str}.\n\n"
                "Você quer que eu te guie pelo processo de inserção no ANAREDE?\n\n"
                "1. **Sim** — iniciar simulação guiada\n\n"
                "2. **Não** — só quero uma resposta técnica"
            )
        return None  # Let LLM answer

    # ── IDLE_LT_CONFIRM: user is confirming whether to start guided flow ───────
    if step == "IDLE_LT_CONFIRM":
        tl = user_text.lower().strip()

        # If the user asks an unrelated free question, abandon the confirmation
        if _is_free_question(user_text):
            st.session_state.sim_step = "IDLE"
            st.session_state.sim_data = {}
            return None

        if tl in ("1", "sim", "s", "quero", "iniciar") or any(
            w in tl for w in ["sim", "quero", "iniciar", "pode", "vamos"]
        ):
            pending_lt = data.get("pending_lt", {})
            lt_summary = _format_lt_params(pending_lt)
            st.session_state.simulation_mode = True
            st.session_state.sim_status = "active"
            st.session_state.sim_step = "IDLE_LT_NET_CHOICE"
            # Keep pending_lt in sim_data
            return (
                (f"Ótimo! Parâmetros registrados: **{lt_summary}**.\n\n" if lt_summary else "Ótimo!\n\n")
                + "Como deseja usar os dados desta linha?\n\n"
                "**1.** Montar uma rede nova do zero com esta linha já incluída\n\n"
                "**2.** Inserir BESS/STATCOM em um caso PAR/PEL/PDE existente "
                "(fluxo com base de dados ONS ou EPE)"
            )

        if tl in ("2", "não", "nao", "n", "não") or any(
            w in tl for w in ["não", "nao", "apenas", "só", "so", "tecnica", "técnica"]
        ):
            original_q = data.get("pending_question")
            st.session_state.sim_step = "IDLE"
            st.session_state.sim_data = {}
            if original_q:
                # Store for main handler to feed to LLM instead of the "não" message
                st.session_state["_lt_confirm_question"] = original_q
            return None  # LLM will answer the original question

        return (
            "Não entendi a resposta. Você quer iniciar a simulação guiada?\n\n"
            "1. **Sim** — iniciar simulação guiada\n\n"
            "2. **Não** — só quero uma resposta técnica"
        )

    # ── IDLE_LT_NET_CHOICE: user chose "sim" at IDLE_LT_CONFIRM ──────────────
    if step == "IDLE_LT_NET_CHOICE":
        tl = user_text.strip().lower()

        if tl in ("1",) or any(w in tl for w in ["rede", "zero", "nova", "montar", "construir"]):
            # Option 1 — build new network, pre-fill line from pending_lt
            pending_lt = data.get("pending_lt", {})
            st.session_state.sim_step = "NET1_SETUP"
            data["sim_type"] = "NETWORK"
            data["network"] = {"title": "Meu Caso", "base_mva": 100.0, "buses": [], "lines": []}
            lt_summary = _format_lt_params(pending_lt)
            return (
                f"Ótimo! A linha (**{lt_summary}**) será automaticamente incluída na rede.\n\n"
                "Vou precisar que você defina as barras primeiro, e depois a conversão "
                "dos parâmetros será aplicada na linha.\n\n"
                "---\n\n"
                "**Qual o título deste caso e a potência base?**\n\n"
                "Exemplo: `LT 230kV Teste, 100 MVA`\n\n"
                "Ou **confirmar** para padrões (título: 'Meu Caso', base: 100 MVA)."
            )

        if tl in ("2",) or any(w in tl for w in ["bess", "statcom", "par", "pel", "pde", "ons", "epe", "existente", "caso existente"]):
            # Option 2 — current BESS/STATCOM flow
            st.session_state.sim_step = "STEP1"
            data["sim_type"] = "BESS"
            return (
                "Certo! Seguindo pelo fluxo de inserção em caso existente.\n\n"
                "Os parâmetros da LT ficam registrados para referência.\n\n"
                "---\n\n"
                "**Qual base de dados deseja utilizar?**\n\n"
                "1. **EPE (PDE)** — planejamento de expansão, horizonte de ~10 anos.\n\n"
                "2. **ONS (PAR/PEL)** — planejamento operacional, horizonte de ~5 anos."
            )

        return (
            "Não entendi. Por favor, escolha:\n\n"
            "**1** — Montar uma rede nova do zero\n\n"
            "**2** — Inserir BESS/STATCOM em caso PAR/PEL/PDE existente"
        )

    # ── STEP 1: waiting for EPE/ONS choice ────────────────────────────────────
    if step == "STEP1":
        t = user_text.strip().lower()
        if t == "3" or any(w in t for w in ["rede", "zero", "própria", "propria", "montar"]):
            # Option 3 — build from scratch
            st.session_state.sim_step = "NET1_SETUP"
            data["sim_type"] = "NETWORK"
            data["network"] = {"title": "Meu Caso", "base_mva": 100.0, "buses": [], "lines": []}
            return (
                "Ótimo! Vou te guiar para montar uma rede do zero.\n\n"
                "**Qual o título deste caso e a potência base?**\n\n"
                "Exemplo: `LT 230kV Teste, 100 MVA`\n\n"
                "Ou **confirmar** para padrões (título: 'Meu Caso', base: 100 MVA)."
            )
        if t == "1" or any(w in t for w in ["epe", "pde", "expansão", "expansao", "longo prazo"]):
            data["db"] = "EPE"
            label = "PDE (EPE)"
        elif t == "2" or any(w in t for w in ["ons", "par", "pel", "operacional"]):
            data["db"] = "ONS"
            label = "PAR/PEL (ONS)"
        else:
            return (
                "Não identifiquei a escolha. Por favor, responda com:\n\n"
                "**1** — EPE (PDE)\n\n**2** — ONS (PAR/PEL)\n\n"
                "**3** — Minha própria rede (montar do zero)"
            )
        st.session_state.sim_step = "STEP2"
        return (
            f"Ótimo, usaremos o **{label}**.\n\n"
            "**Qual ano (ou anos) deseja estudar?**\n\n"
            "Pode informar um único ano (ex: **2028**) ou múltiplos anos "
            "(ex: **2027, 2028, 2029**). O normal é estudar um conjunto de anos diferentes."
        )

    # ── STEP 2: waiting for year(s) ───────────────────────────────────────────
    if step == "STEP2":
        years = _parse_years(user_text)
        if not years:
            return "Não identifiquei o(s) ano(s). Por favor, informe o ano desejado (ex: **2028**)."
        data["years"] = years
        data["year_idx"] = 0
        db = data["db"]
        st.session_state.sim_step = "STEP3"
        scenarios = _PARPEL_SCENARIOS if db == "ONS" else _PDE_SCENARIOS
        years_str = ", ".join(str(y) for y in years)
        return f"Anos selecionados: **{years_str}**.\n\n{scenarios}"

    # ── STEP 3: waiting for scenario ──────────────────────────────────────────
    if step == "STEP3":
        db = data.get("db", "ONS")
        scenario = _parse_scenario(user_text, db)
        if scenario is None:
            scenarios = _PARPEL_SCENARIOS if db == "ONS" else _PDE_SCENARIOS
            return "Não identifiquei o cenário. Por favor, selecione pelo número:\n\n" + scenarios
        data["scenario"] = scenario
        year = data["years"][data.get("year_idx", 0)]
        data["year"] = year
        st.session_state.sim_step = "STEP4"
        return f"Cenário selecionado: **{scenario}** — ano **{year}**.\n\n" + _sav_filename_hint(db, scenario, year)

    # ── STEP 4: convergence check of base case ────────────────────────────────
    if step == "STEP4":
        ctx = extract_sim_context(user_text)
        if ctx["convergence"] == "red":
            return (
                "O caso base não está convergido, o que é incomum pois os casos da "
                "EPE e ONS já vêm convergidos. Verifique se:\n\n"
                "- Carregou o arquivo SAV correto\n"
                "- Selecionou o caso correto em **Histórico > Operações**\n"
                "- O arquivo não está corrompido\n\n"
                "Tente recarregar o arquivo e informe novamente o que aparece "
                "no canto superior direito."
            )
        if ctx["convergence"] != "green":
            return "O que aparece no canto superior direito do ANAREDE após carregar o caso?"

        # Base case is converged — fast-forward as far as the message allows
        converged_prefix = "Perfeito! O caso base está convergido.\n\n---\n\n"
        sim_type = data.get("sim_type", "BESS")
        device_label = "STATCOM" if sim_type == "STATCOM" else "BESS"

        # If bus number provided, skip straight to STEP7 — BESS only
        if sim_type == "BESS" and ctx["bus_number"] is not None:
            data["bess_bus"] = ctx["bus_number"]
            if ctx["bess_mode"] is not None:
                data["bess_mode"] = ctx["bess_mode"]
                mode_label = "PV (controle de tensão)" if ctx["bess_mode"] == "PV" else "PQ (despacho fixo)"
                if ctx["S_mva"] is not None:
                    data["bess_mva"] = str(ctx["S_mva"])
                    if ctx["P_mw"] is not None:
                        data["bess_p_mw"] = str(ctx["P_mw"])
                        st.session_state.sim_step = "STEP8"
                        return (
                            converged_prefix
                            + f"Barra **{ctx['bus_number']}**, modo **{mode_label}**, "
                            f"potência **{ctx['S_mva']} MVA**, P ativa: **{ctx['P_mw']} MW** identificados.\n\n"
                            "Qual número de barra está disponível no seu caso para a nova barra da BESS?\n\n"
                            "(escolha um número que não exista no caso atual)"
                        )
                    st.session_state.sim_step = "STEP8"
                    return (
                        converged_prefix
                        + f"Barra **{ctx['bus_number']}**, modo **{mode_label}**, "
                        f"potência nominal **{ctx['S_mva']} MVA** registrada.\n\n"
                        "**Qual a potência ativa em MW?**\n\n"
                        "Os limites de potência reativa serão calculados: "
                        "Q_max = √(S² − P²), Q_min = −Q_max"
                    )
                st.session_state.sim_step = "STEP8"
                return (
                    converged_prefix
                    + f"Barra selecionada: **{ctx['bus_number']}** e modo **{mode_label}** identificados.\n\n"
                    "**Qual a potência nominal da BESS em MVA?**\n\n"
                    "Os limites de potência reativa serão calculados automaticamente: "
                    "Q_max = √(S² − P²), Q_min = −Q_max"
                )
            st.session_state.sim_step = "STEP7"
            # bess_bus already set — jump to mode question
            return (
                converged_prefix
                + f"Barra selecionada: **{ctx['bus_number']}**.\n\n"
                "Para inserir a BESS nessa barra, recomenda-se criar uma nova barra "
                "conectada à barra desejada por uma linha com reatância de **0.00001 pu** "
                "(resistência e susceptância zeradas).\n\n"
                "**Qual o modo de operação da BESS?**\n\n"
                "1. **Controle de tensão (barra PV — tipo 2):** recomendado para estudos "
                "do SIN, especialmente se o leilão exigir modo GFM.\n\n"
                "2. **Despacho fixo (barra PQ — tipo 1):** injeção fixa de potência ativa e reativa."
            )

        # No bus info — check LST choice
        lst_question = (
            "**Agora vamos preparar a visualização da região de estudo.**\n\n"
            "A tela do ANAREDE está em branco. Para visualizar os resultados "
            "graficamente, você precisa carregar ou desenhar um diagrama LST.\n\n"
            "**Opção A** — Se já tiver um arquivo LST:\n"
            "Vá em **Diagrama > Carregar** e selecione o arquivo LST.\n\n"
            "**Opção B** — Se não tiver:\n"
            "Clique no ícone do **lápis** no menu superior. Aparecerá um diálogo "
            "com os elementos que podem ser modelados. Desenhe a região ao entorno "
            "da barra que deseja estudar.\n\n"
            "Qual opção você vai utilizar?"
        )
        if ctx["lst"] is not None:
            # LST answered inline — skip STEP6 and go to STEP7
            st.session_state.sim_step = "STEP7"
            return (
                converged_prefix
                + f"Ótimo! LST identificado.\n\n"
                f"**Agora vamos modelar o {device_label}.**\n\n"
                f"Qual é a barra onde deseja inserir o {device_label}?\n\n"
                "Dica: escolha a subestação com maior carga na área de estudo "
                "que disponha de margem para injeção de potência."
            )

        st.session_state.sim_step = "STEP6"
        return converged_prefix + lst_question

    # ── STEP 6: LST diagram ───────────────────────────────────────────────────
    if step == "STEP6":
        sim_type = data.get("sim_type", "BESS")
        device_label = "STATCOM" if sim_type == "STATCOM" else "BESS"
        ctx = extract_sim_context(user_text)
        # Fast-forward if bus number (and optionally mode) already provided — BESS only
        if sim_type == "BESS" and ctx["bus_number"] is not None:
            data["bess_bus"] = ctx["bus_number"]
            if ctx["bess_mode"] is not None:
                data["bess_mode"] = ctx["bess_mode"]
                mode_label = "PV (controle de tensão)" if ctx["bess_mode"] == "PV" else "PQ (despacho fixo)"
                if ctx["S_mva"] is not None:
                    data["bess_mva"] = str(ctx["S_mva"])
                    if ctx["P_mw"] is not None:
                        data["bess_p_mw"] = str(ctx["P_mw"])
                        st.session_state.sim_step = "STEP8"
                        return (
                            "Ótimo!\n\n"
                            f"Barra **{ctx['bus_number']}**, modo **{mode_label}**, "
                            f"potência **{ctx['S_mva']} MVA**, P ativa: **{ctx['P_mw']} MW** identificados.\n\n"
                            "Qual número de barra está disponível no seu caso para a nova barra da BESS?\n\n"
                            "(escolha um número que não exista no caso atual)"
                        )
                    st.session_state.sim_step = "STEP8"
                    return (
                        "Ótimo!\n\n"
                        f"Barra **{ctx['bus_number']}**, modo **{mode_label}**, "
                        f"potência nominal **{ctx['S_mva']} MVA** registrada.\n\n"
                        "**Qual a potência ativa em MW?**\n\n"
                        "Os limites de potência reativa serão calculados: "
                        "Q_max = √(S² − P²), Q_min = −Q_max"
                    )
                st.session_state.sim_step = "STEP8"
                return (
                    "Ótimo!\n\n"
                    f"Barra selecionada: **{ctx['bus_number']}** e modo **{mode_label}** identificados.\n\n"
                    "**Qual a potência nominal da BESS em MVA?**\n\n"
                    "Os limites de potência reativa serão calculados automaticamente: "
                    "Q_max = √(S² − P²), Q_min = −Q_max"
                )
            st.session_state.sim_step = "STEP7"
            # bess_bus already set — jump straight to mode question
            return (
                "Ótimo!\n\n"
                f"Barra selecionada: **{ctx['bus_number']}**.\n\n"
                "Para inserir a BESS nessa barra, recomenda-se criar uma nova barra "
                "conectada à barra desejada por uma linha com reatância de **0.00001 pu** "
                "(resistência e susceptância zeradas).\n\n"
                "**Qual o modo de operação da BESS?**\n\n"
                "1. **Controle de tensão (barra PV — tipo 2):** recomendado para estudos "
                "do SIN, especialmente se o leilão exigir modo GFM.\n\n"
                "2. **Despacho fixo (barra PQ — tipo 1):** injeção fixa de potência ativa e reativa."
            )
        st.session_state.sim_step = "STEP7"
        return (
            "Ótimo!\n\n"
            f"**Agora vamos modelar o {device_label}.**\n\n"
            f"Qual é a barra onde deseja inserir o {device_label}?\n\n"
            + (
                "Dica: escolha a subestação com maior carga na área de estudo "
                "que disponha de margem para injeção de potência. O ONS disponibiliza "
                "mapas interativos e relatórios indicando a margem de escoamento de "
                "geração das subestações da rede básica."
                if sim_type == "BESS" else
                "Dica: escolha a subestação com problema de tensão que o STATCOM deve regular."
            )
        )

    # ── STEP 7: bus identification ────────────────────────────────────────────
    if step == "STEP7":
        sim_type = data.get("sim_type", "BESS")
        # ── STATCOM path: just ask for bus, then Q limits ─────────────────────
        if sim_type == "STATCOM":
            bus_match = re.search(r"(?<![.,\d])(\d{4,5})\b", user_text)
            if bus_match:
                data["statcom_bus"] = bus_match.group(1)
            elif 2 <= len(user_text.strip()) <= 50:
                data["statcom_bus"] = user_text.strip()
            else:
                return "Qual é a barra onde deseja inserir o STATCOM?"
            st.session_state.sim_step = "STATCOM_STEP_Q"
            return (
                f"Barra selecionada: **{data['statcom_bus']}**.\n\n"
                "**Qual a capacidade reativa do STATCOM?**\n\n"
                "Informe Qmin e Qmax em Mvar.\n\n"
                "Exemplo: `Qmin -100 Mvar, Qmax 100 Mvar`"
            )
        # ── BESS path ─────────────────────────────────────────────────────────
        if "bess_bus" not in data:
            # Parse bus from user message — accept any number or short name
            bus_match = re.search(r"(?<![.,\d])(\d{4,5})\b", user_text)
            if bus_match:
                data["bess_bus"] = bus_match.group(1)
            else:
                # Accept short text as a subestação name, but reject long
                # parameter dumps that the regex couldn't parse into a bus number
                stripped = user_text.strip()
                if 2 <= len(stripped) <= 50:
                    data["bess_bus"] = stripped
                else:
                    return (
                        "Não identifiquei a barra. Por favor, informe apenas o número "
                        "ou nome da barra onde deseja inserir a BESS."
                    )
            bus = data["bess_bus"]
            # Fast-forward to STEP8 if mode also provided in the same message
            mode = _parse_bess_mode(user_text)
            if mode is not None:
                data["bess_mode"] = mode
                mode_label = "PV (controle de tensão)" if mode == "PV" else "PQ (despacho fixo)"
                ctx7 = extract_sim_context(user_text)
                if ctx7["S_mva"] is not None:
                    data["bess_mva"] = str(ctx7["S_mva"])
                    if ctx7["P_mw"] is not None:
                        data["bess_p_mw"] = str(ctx7["P_mw"])
                        st.session_state.sim_step = "STEP8"
                        return (
                            f"Barra **{bus}**, modo **{mode_label}**, "
                            f"potência **{ctx7['S_mva']} MVA**, P ativa: **{ctx7['P_mw']} MW** identificados.\n\n"
                            "Qual número de barra está disponível no seu caso para a nova barra da BESS?\n\n"
                            "(escolha um número que não exista no caso atual)"
                        )
                    st.session_state.sim_step = "STEP8"
                    return (
                        f"Barra **{bus}**, modo **{mode_label}**, "
                        f"potência nominal **{ctx7['S_mva']} MVA** registrada.\n\n"
                        "**Qual a potência ativa em MW?**\n\n"
                        "Os limites de potência reativa serão calculados: "
                        "Q_max = √(S² − P²), Q_min = −Q_max"
                    )
                st.session_state.sim_step = "STEP8"
                return (
                    f"Barra selecionada: **{bus}** e modo **{mode_label}** identificados.\n\n"
                    "**Qual a potência nominal da BESS em MVA?**\n\n"
                    "Para o estudo, recomenda-se variar a potência ativa injetada:\n"
                    "- Comece com +100% (injeção máxima), 0% e -100% (carga)\n"
                    "- Para cada valor, verifique convergência e impactos no sistema\n\n"
                    "Os limites de potência reativa serão calculados automaticamente: "
                    "Q_max = √(S² − P²), Q_min = −Q_max"
                )
            return (
                f"Barra selecionada: **{bus}**.\n\n"
                "Para inserir a BESS nessa barra, recomenda-se criar uma nova barra "
                "conectada à barra desejada por uma linha com reatância de **0.00001 pu** "
                "(resistência e susceptância zeradas).\n\n"
                "**Qual o modo de operação da BESS?**\n\n"
                "1. **Controle de tensão (barra PV — tipo 2):** recomendado para estudos "
                "do SIN, especialmente se o leilão exigir modo GFM. A barra é configurada "
                "com despacho fixo de potência ativa e tensão-alvo que a BESS tentará controlar.\n\n"
                "2. **Despacho fixo (barra PQ — tipo 1):** injeção fixa de potência ativa e reativa."
            )
        else:
            # Waiting for mode
            mode = _parse_bess_mode(user_text)
            if mode is None:
                return (
                    "Não identifiquei o modo. Responda **1** (controle de tensão / PV) "
                    "ou **2** (despacho fixo / PQ)."
                )
            data["bess_mode"] = mode
            mode_label = "PV (controle de tensão)" if mode == "PV" else "PQ (despacho fixo)"
            ctx7 = extract_sim_context(user_text)
            if ctx7["S_mva"] is not None:
                data["bess_mva"] = str(ctx7["S_mva"])
                if ctx7["P_mw"] is not None:
                    data["bess_p_mw"] = str(ctx7["P_mw"])
                    st.session_state.sim_step = "STEP8"
                    return (
                        f"Modo **{mode_label}**, potência **{ctx7['S_mva']} MVA**, "
                        f"P ativa: **{ctx7['P_mw']} MW** identificados.\n\n"
                        "Qual número de barra está disponível no seu caso para a nova barra da BESS?\n\n"
                        "(escolha um número que não exista no caso atual)"
                    )
                st.session_state.sim_step = "STEP8"
                return (
                    f"Modo **{mode_label}**, potência nominal **{ctx7['S_mva']} MVA** registrada.\n\n"
                    "**Qual a potência ativa em MW?**\n\n"
                    "Os limites de potência reativa serão calculados: "
                    "Q_max = √(S² − P²), Q_min = −Q_max"
                )
            st.session_state.sim_step = "STEP8"
            return (
                f"Modo selecionado: **{mode_label}**.\n\n"
                "**Qual a potência nominal da BESS em MVA?**\n\n"
                "Para o estudo, recomenda-se variar a potência ativa injetada:\n"
                "- Comece com +100% (injeção máxima), 0% e -100% (carga)\n"
                "- Para cada valor, verifique convergência e impactos no sistema\n\n"
                "Os limites de potência reativa serão calculados automaticamente: "
                "Q_max = √(S² − P²), Q_min = −Q_max"
            )

    # ── STEP 8: BESS power config ─────────────────────────────────────────────
    if step == "STEP8":
        if "bess_mva" not in data:
            # Sub-step 8a: collect S_mva; advance only if P_mw also present
            mva = _parse_mva(user_text)
            if mva is None:
                return "Não identifiquei a potência. Por favor, informe o valor em MVA (ex: **100**)."
            data["bess_mva"] = mva
            p_mw = _parse_active_power(user_text)
            if p_mw is not None:
                data["bess_p_mw"] = p_mw
                return (
                    f"Potência nominal: **{mva} MVA**, P ativa: **{p_mw} MW**.\n\n"
                    "Qual número de barra está disponível no seu caso para a nova barra da BESS?\n\n"
                    "(escolha um número que não exista no caso atual)"
                )
            # P_mw not given yet — ask for it explicitly
            return (
                f"Potência nominal: **{mva} MVA** registrada.\n\n"
                "**Qual a potência ativa em MW?**\n\n"
                "Os limites de potência reativa serão calculados: "
                "Q_max = √(S² − P²), Q_min = −Q_max"
            )
        elif "bess_p_mw" not in data:
            # Sub-step 8b: collect P_mw — this message is never treated as a bus number
            p_mw = _parse_active_power(user_text)
            if p_mw is None:
                m = re.search(r"(\d+(?:[.,]\d+)?)\s*mw\b", user_text, re.IGNORECASE)
                if m:
                    p_mw = m.group(1).replace(",", ".")
            if p_mw is None:
                m = re.search(r"^\s*(\d+(?:[.,]\d+)?)\s*$", user_text.strip())
                if m:
                    p_mw = m.group(1).replace(",", ".")
            if p_mw is None:
                return "Não identifiquei a potência ativa. Por favor, informe em MW (ex: **80**)."
            data["bess_p_mw"] = p_mw
            return (
                f"P ativa: **{p_mw} MW** registrada.\n\n"
                "Qual número de barra está disponível no seu caso para a nova barra da BESS?\n\n"
                "(escolha um número que não exista no caso atual)"
            )
        else:
            # Sub-step 8c: both S_mva and P_mw confirmed — collect new BESS bus number
            bus_num_match = re.search(r"(?<![.,\d])(\d{4,5})\b", user_text)
            if not bus_num_match:
                return (
                    "Não identifiquei o número da barra. "
                    "Por favor, informe um número de barra disponível (ex: **9999**)."
                )
            data["bess_bus_number"] = bus_num_match.group(1)
            bus_to = data["bess_bus_number"]
            mva = data["bess_mva"]
            st.session_state.sim_step = "STEP9"
            pwf_lines = _bess_pwf_lines(data)
            return (
                f"Barra da BESS: **{bus_to}** — Potência nominal: **{mva} MVA**.\n\n"
                + pwf_lines
                + "\n\n---\n\n"
                "**Antes de rodar o fluxo de potência, salve o caso com a BESS incluída.**\n\n"
                "No ANAREDE:\n"
                "1. Vá em **Histórico > Operações**\n"
                "2. No campo **'Caso'**, coloque um número diferente dos casos já existentes\n"
                "3. Clique em **Salvar**\n\n"
                "Confirme quando o caso estiver salvo."
            )

    # ── STEP 9: waiting for save confirmation ─────────────────────────────────
    if step == "STEP9":
        t = user_text.lower()
        if any(kw in t for kw in ["salvo", "salvei", "ok", "sim", "pronto", "feito", "confirmado", "salv"]):
            st.session_state.sim_step = "STEP10"
            return (
                "Ótimo! Caso salvo.\n\n"
                "**Agora rode o algoritmo de fluxo de potência.**\n\n"
                "Forma mais rápida: pressione **Ctrl + R** no teclado.\n"
                "Isso repete a última configuração do algoritmo salva no SAV.\n\n"
                "Alternativa: vá em **Análise > Cálculo de Fluxo de Potência** para "
                "acessar todos os métodos e controles disponíveis.\n\n"
                "Após rodar, o que aparece no canto superior direito do ANAREDE?"
            )
        return "Confirme quando o caso estiver salvo no ANAREDE (responda 'salvo' ou 'pronto')."

    # ── STEP 10: convergence check of modified case ───────────────────────────
    if step == "STEP10":
        if _is_converged(user_text):
            data.pop("divergence_color", None)
            st.session_state.sim_step = "STEP11"
            return (
                "Ótimo! O caso convergiu.\n\n"
                "Salve o caso convergido (pode sobrescrever o caso salvo no passo anterior).\n\n"
                "**Para verificar o impacto no diagrama:**\n"
                "- Sobrecargas e sobretensões aparecem com **hachura VERMELHA**\n"
                "- Subtensões aparecem com **hachura AZUL**\n"
                "- Verifique também os impactos na barra de referência e nas "
                "principais barras de geração do SIN\n\n"
                "O que você está observando no diagrama?"
            )
        # ── Already asked for color — detect vermelho vs amarelo first ────────
        elif data.get("divergence_color") == "unknown":
            t = user_text.lower()
            if "vermelho" in t or "red" in t or "divergiu" in t:
                data["divergence_color"] = "red"
                return (
                    "**O fluxo divergiu (vermelho).** Causas prováveis:\n\n"
                    "1. **Potência injetada muito alta** para a rede local\n"
                    "   → Reduza P para 50% e tente novamente (Ctrl+R)\n\n"
                    "2. **Geração reativa insuficiente** na barra\n"
                    "   → Verifique se Qmax é adequado para a tensão local\n\n"
                    "3. **Rede fraca na região**\n"
                    "   → Tente modo PQ em vez de PV\n\n"
                    "Recarregue o caso (Histórico > Operações > Restabelecer) "
                    "e informe o que aparece após tentar novamente."
                )
            elif "amarelo" in t or "yellow" in t or "iteraç" in t or "limite" in t:
                data["divergence_color"] = "yellow"
                return (
                    "O caso atingiu o limite de iterações sem convergir. "
                    "Isso geralmente indica convergência lenta, não instabilidade numérica. Tente:\n\n"
                    "**PASSO 1 — Aumente o número de iterações no ANAREDE:**\n"
                    "Análise > Cálculo de Fluxo de Potência > campo 'Número de Iterações' "
                    "→ aumente para 100 ou 200.\n\n"
                    "**PASSO 2 — Ative o flat start:**\n"
                    "No código EXLF, ative a opção FLAT para inicializar todas as tensões "
                    "em 1.0 pu e ângulos em zero.\n\n"
                    "**PASSO 3 — Desative controles temporariamente:**\n"
                    "No código EXLF, desative CTAP (controle automático de tap) e CREM "
                    "(controle remoto de tensão) e tente convergir primeiro sem eles.\n\n"
                    "**PASSO 4 — Se ainda não convergir:**\n"
                    "Reduza a potência ativa da BESS para 50% e tente novamente com os passos acima."
                )
            else:
                return (
                    "Não identifiquei a cor. "
                    "O indicador no canto superior direito ficou **vermelho** (divergiu) "
                    "ou **amarelo** (limite de iterações)?"
                )
        # ── First time hearing about non-convergence — ask for color ──────────
        elif _is_not_converged(user_text):
            data["divergence_color"] = "unknown"
            return (
                "O caso não convergiu. O que apareceu no canto superior direito?\n\n"
                "- **Vermelho**: o algoritmo divergiu\n"
                "- **Amarelo**: atingiu o limite de iterações sem convergir"
            )
        elif data.get("divergence_color") in ("red", "yellow"):
            # Known color, still not converging — generic retry tips
            return (
                "O caso não convergiu. Vamos tentar resolver.\n\n"
                "**PASSO 1** — Recarregue o caso salvo antes de rodar o fluxo:\n"
                "Histórico > Operações > selecione o caso salvo > Restabelecer\n\n"
                "**PASSO 2** — Reduza a injeção de potência ativa da BESS para um "
                "valor próximo de zero e rode novamente (Ctrl + R).\n\n"
                "**PASSO 3** — Se convergiu com valor baixo, aumente gradualmente "
                "a potência injetada até encontrar o limite que o sistema suporta.\n\n"
                "Recarregue o caso e informe o que aparece no canto superior direito."
            )
        else:
            return "O que aparece no canto superior direito do ANAREDE após rodar o fluxo?"

    # ── STEP 11: results analysis ─────────────────────────────────────────────
    if step == "STEP11":
        t = user_text.lower()
        _RESULT_SIGNALS = [
            "hachura", "vermelho", "azul", "sobrecarrega", "subtensão", "subtensao",
            "sobretensão", "sobretensao", "estável", "estavel", "convergiu",
            "impacto", "sem impacto", "observ", "diagrama", "nada", "ok", "sim",
            "não vi", "nao vi", "normal", "tudo", "sem problema",
        ]
        has_results = any(s in t for s in _RESULT_SIGNALS)
        if not has_results:
            # Nothing recognisable — let LLM answer and keep step at STEP11
            return None
        st.session_state.sim_step = "STEP11B"
        ack = "Análise registrada.\n\n" if has_results else ""
        return (
            ack
            + "Deseja realizar uma análise de contingências N-1 na região de estudo?\n\n"
            "- **Sim** — vou te guiar pela configuração e execução das contingências no ANAREDE\n"
            "- **Não** — seguimos para os próximos passos recomendados"
        )

    # ── STEP 11B: contingency guide ───────────────────────────────────────────
    if step == "STEP11B":
        t = user_text.lower()
        stage = st.session_state.sim_data.get("contingency_stage")

        # ── Sub-state: waiting for yes/no (stage not yet set) ─────────────────
        if stage is None:
            if any(kw in t for kw in ["sim", "quero", "gostaria", "contingência",
                                       "contingencia", "n-1", "n1", "yes"]):
                st.session_state.sim_data["contingency_stage"] = "guide"
                return (
                    "Ótimo! Para análise de contingências N-1 no ANAREDE:\n\n"
                    "**1. Execute o cálculo:**\n"
                    "No ANAREDE: **Análise > Contingências (EXCT)** ou pressione **Ctrl+E**.\n\n"
                    "**2. Interprete os resultados:**\n"
                    "- **Hachura VERMELHA**: sobrecarga ou sobretensão na contingência\n"
                    "- **Hachura AZUL**: subtensão na contingência\n"
                    "- Sem hachura: sistema suporta a contingência\n\n"
                    "Quais linhas ou geradores deseja incluir na análise N-1?\n\n"
                    "Exemplos:\n"
                    "- `linha 1001-1002 circuito 1`\n"
                    "- `linha entre barras 1001 e 1002, circuito 1`\n"
                    "- `gerador barra 1005`"
                )
            if any(kw in t for kw in ["não", "nao", "pular", "skip"]):
                st.session_state.sim_step = "STEP12"
                return (
                    "**Próximos passos recomendados:**\n\n"
                    "1. Repetir esta simulação para outros patamares de carga e geração "
                    "(máxima noturna, mínima noturna, etc.)\n"
                    "2. Testar em outros anos do período escolhido\n"
                    "3. Simular contingências N-1 (desligamento de linhas e geradores) "
                    "na região de estudo\n"
                    "4. Após validar em regime permanente com ANAREDE, testar a solução "
                    "no ANATEM para verificar o desempenho dinâmico\n\n"
                    "Deseja continuar com outro cenário ou patamar de carga?"
                )
            return (
                "Deseja realizar análise de contingências N-1? "
                "Responda **Sim** ou **Não**."
            )

        # ── Sub-state: waiting for contingency data ────────────────────────────
        if stage == "guide":
            contingencies = []
            ctg_id = 1

            # LINE patterns (in priority order — most specific first)
            _LINE_PATS = [
                # "linha entre barras 1001 e 1002, circuito 1"
                r"linha\s+entre\s+barras?\s+(\d{4,5})\s+e\s+(\d{4,5})"
                r"(?:[\s,]+circuito\s*(\d+))?",
                # "linha 1001-1002 circuito 1"  or  "linha 1001–1002"
                r"linha\s+(\d{4,5})\s*[-–]\s*(\d{4,5})"
                r"(?:[\s,]+circuito\s*(\d+))?",
                # "linha 1001 1002 circuito 1"
                r"linha\s+(\d{4,5})\s+(\d{4,5})"
                r"(?:[\s,]+circuito\s*(\d+))?",
            ]
            seen_lines = set()
            for pat in _LINE_PATS:
                for m in re.finditer(pat, user_text, re.IGNORECASE):
                    key = (m.group(1), m.group(2))
                    if key in seen_lines:
                        continue
                    seen_lines.add(key)
                    bf, bt, ci = m.group(1), m.group(2), m.group(3)
                    contingencies.append({
                        "id": ctg_id,
                        "name": f"LT {bf}-{bt}",
                        "type": "line",
                        "bus_from": int(bf),
                        "bus_to": int(bt),
                        "circuit": int(ci) if ci else 1,
                    })
                    ctg_id += 1

            # GENERATOR patterns
            _GEN_PATS = [
                r"(?:gerador|gera[cç][aã]o)\s+barra\s+(\d{4,5})",
                r"gerador\s+(\d{4,5})",
            ]
            seen_gens = set()
            for pat in _GEN_PATS:
                for m in re.finditer(pat, user_text, re.IGNORECASE):
                    bus = m.group(1)
                    if bus in seen_gens:
                        continue
                    seen_gens.add(bus)
                    contingencies.append({
                        "id": ctg_id,
                        "name": f"GER {bus}",
                        "type": "generator",
                        "bus": int(bus),
                    })
                    ctg_id += 1

            if contingencies:
                dctg_block = generate_contingency_block(contingencies)
                st.session_state.sim_data["contingency_stage"] = "done"
                return (
                    f"Bloco DCTG gerado com **{len(contingencies)}** "
                    f"contingência(s):\n\n"
                    f"```\n{dctg_block}\n```\n\n"
                    "Carregue este bloco no ANAREDE antes de executar.\n\n"
                    "**Deseja adicionar mais contingências ou podemos executar?**\n\n"
                    "- **Executar agora** — pressione **Ctrl+E** no ANAREDE "
                    "(Análise > Contingências > EXCT)\n"
                    "- **Adicionar mais** — informe mais linhas ou geradores\n"
                    "- **Encerrar contingências** — ir para os próximos passos"
                )
            return (
                "Não identifiquei linhas ou geradores na mensagem.\n\n"
                "Use um dos formatos:\n"
                "- `linha 1001-1002 circuito 1`\n"
                "- `linha entre barras 1001 e 1002, circuito 1`\n"
                "- `gerador barra 1005`"
            )

        # ── Sub-state: done — waiting for next action ──────────────────────────
        if stage == "done":
            if any(kw in t for kw in ["executar", "ctrl", "exct", "rodar", "executar agora"]):
                st.session_state.sim_data["contingency_stage"] = "awaiting_results"
                return (
                    "Pressione **Ctrl+E** no ANAREDE ou vá em "
                    "**Análise > Contingências (EXCT)** para rodar a análise N-1.\n\n"
                    "Após a execução, verifique o relatório de violações e o diagrama:\n"
                    "- **Hachura VERMELHA**: sobrecarga ou sobretensão em alguma contingência\n"
                    "- **Hachura AZUL**: subtensão em alguma contingência\n"
                    "- Sem hachura: sistema robusto\n\n"
                    "O que aparece no relatório e no diagrama?"
                )
            if any(kw in t for kw in ["adicionar", "mais", "outra", "outro"]):
                st.session_state.sim_data["contingency_stage"] = "guide"
                return (
                    "Informe as próximas contingências:\n\n"
                    "- `linha XXXX-YYYY circuito N`\n"
                    "- `gerador barra XXXXX`"
                )
            # Default (encerrar / anything else) → next steps
            st.session_state.sim_step = "STEP12"
            return (
                "**Próximos passos recomendados:**\n\n"
                "1. Repetir esta simulação para outros patamares de carga e geração "
                "(máxima noturna, mínima noturna, etc.)\n"
                "2. Testar em outros anos do período escolhido\n"
                "3. Simular contingências N-1 (desligamento de linhas e geradores) "
                "na região de estudo\n"
                "4. Após validar em regime permanente com ANAREDE, testar a solução "
                "no ANATEM para verificar o desempenho dinâmico\n\n"
                "Deseja continuar com outro cenário ou patamar de carga?"
            )

        # ── Sub-state: awaiting N-1 results report ─────────────────────────────
        if stage == "awaiting_results":
            st.session_state.sim_step = "STEP12"
            st.session_state.sim_data.pop("contingency_stage", None)
            _OVERLOAD = ["sobrecarga", "vermelh", "overload", "sobrecarrega",
                         "termicamente", "carregamento"]
            _UNDERVOLT = ["subtensão", "subtensao", "azul", "queda de tensão",
                          "queda de tensao", "tensão baixa"]
            _STABLE    = ["sem hachura", "estável", "estavel", "suportou",
                          "suporta", "sem violação", "sem violacao", "nada", "ok"]
            if any(kw in t for kw in _OVERLOAD):
                # Try to extract a mentioned line from the report
                line_ref = re.search(r"linha\s+([\d\w][\d\w-]*)", user_text, re.IGNORECASE)
                line_mention = f" na linha **{line_ref.group(1)}**" if line_ref else ""
                interpretation = (
                    f"**Sobrecarga detectada na contingência N-1{line_mention}.** "
                    "Ao perder o elemento testado, a linha fica termicamente "
                    "sobrecarregada. Ações recomendadas:\n\n"
                    "1. Verificar se há reforço de rede planejado na região\n"
                    "2. Avaliar redução da potência do BESS para aliviar o carregamento\n"
                    "3. Registrar a violação no relatório de estudo"
                )
            elif any(kw in t for kw in _UNDERVOLT):
                interpretation = (
                    "**Subtensão detectada na contingência N-1.** "
                    "A perda do elemento causa queda de tensão abaixo do limite. "
                    "Ações recomendadas:\n\n"
                    "1. Avaliar aumento do suporte reativo na região\n"
                    "2. Verificar se o BESS em modo PV pode compensar a queda\n"
                    "3. Considerar instalação de banco de capacitores"
                )
            elif any(kw in t for kw in _STABLE):
                interpretation = (
                    "**Sistema robusto** — a contingência N-1 é suportada sem violações. "
                    "O BESS não causa problemas de segurança na contingência testada."
                )
            else:
                interpretation = "Resultado registrado."
            return (
                interpretation + "\n\n---\n\n"
                "Deseja continuar com outro cenário ou patamar de carga?"
            )

    # ── STEP 12: awaiting continuation choice ─────────────────────────────────
    if step == "STEP12":
        t = user_text.lower()
        db = data.get("db", "ONS")

        # ── Explicit end signal only — matched as whole words so unrelated
        #    input never ends the session abruptly (e.g. "determinar" no longer
        #    trips "terminar", and a bare "não" is treated as unrecognized). ──
        _END_TOKENS = {"encerrar", "encerra", "finalizar", "finaliza",
                       "terminar", "fim", "sair"}
        if _END_TOKENS & set(re.findall(r"\w+", t)):
            st.session_state.simulation_mode = False
            st.session_state.sim_step = "IDLE"
            st.session_state.sim_data = {}
            st.session_state.sim_status = None
            try:
                clear_paused_state(st.session_state["session_id"])
            except Exception:
                pass
            return (
                "Simulação encerrada. Os resultados ficam registrados no histórico acima.\n\n"
                "Se precisar retomar ou tiver outras dúvidas sobre o SIN, é só perguntar."
            )

        # BUG 2a — Restart full simulation from STEP1
        if any(kw in t for kw in ["quero simular", "simular novamente", "reiniciar",
                                   "recomeçar", "recomecar", "nova simulação", "nova simulacao"]):
            st.session_state.sim_data = {}
            st.session_state.sim_step = "STEP1"
            st.session_state.simulation_mode = True
            st.session_state.sim_status = "active"
            return (
                "**Qual base de dados deseja utilizar?**\n\n"
                "1. **EPE (PDE)** — planejamento de expansão, horizonte de ~10 anos. "
                "Modelos com maior incerteza sobre o futuro.\n\n"
                "2. **ONS (PAR/PEL)** — planejamento operacional, horizonte de ~5 anos. "
                "Modelos mais detalhados e confiáveis para decisões operativas.\n\n"
                "Para estudos de inserção de tecnologias como BESS no SIN, o "
                "PAR/PEL do ONS é geralmente preferível por ter modelos mais detalhados."
            )

        # BUG 2b — New year (2026–2040) → restart from STEP3 keeping same database
        new_years = _parse_years(user_text)
        if new_years and all(2026 <= y <= 2040 for y in new_years):
            data["years"] = new_years
            data["year_idx"] = 0
            data.pop("scenario", None)
            for key in ["bess_bus", "bess_bus_number", "bess_mva", "bess_p_mw", "bess_mode"]:
                data.pop(key, None)
            st.session_state.sim_step = "STEP3"
            years_str = ", ".join(str(y) for y in new_years)
            scenarios = _PARPEL_SCENARIOS if db == "ONS" else _PDE_SCENARIOS
            return f"Ano(s) atualizado(s): **{years_str}**.\n\n{scenarios}"

        # BUG 2c — Mode/power input → resume BESS config from STEP7 or STEP8
        ctx12 = extract_sim_context(user_text)
        if ctx12["bess_mode"] is not None:
            prev_bus = data.get("bess_bus")
            for key in ["bess_bus_number", "bess_mva", "bess_p_mw", "bess_mode"]:
                data.pop(key, None)
            data["bess_mode"] = ctx12["bess_mode"]
            mode_label = "PV (controle de tensão)" if ctx12["bess_mode"] == "PV" else "PQ (despacho fixo)"
            if ctx12["S_mva"] is not None:
                data["bess_mva"] = str(ctx12["S_mva"])
                if ctx12["P_mw"] is not None:
                    data["bess_p_mw"] = str(ctx12["P_mw"])
            if prev_bus is not None:
                data["bess_bus"] = prev_bus
                if ctx12["S_mva"] is not None:
                    if ctx12["P_mw"] is not None:
                        st.session_state.sim_step = "STEP8"
                        return (
                            f"Modo **{mode_label}**, potência **{ctx12['S_mva']} MVA**, "
                            f"P ativa: **{ctx12['P_mw']} MW** identificados. "
                            f"Mantendo barra **{prev_bus}** da simulação anterior.\n\n"
                            "Qual número de barra está disponível no seu caso para a nova barra da BESS?\n\n"
                            "(escolha um número que não exista no caso atual)"
                        )
                    st.session_state.sim_step = "STEP8"
                    return (
                        f"Modo **{mode_label}**, potência nominal **{ctx12['S_mva']} MVA** registrada. "
                        f"Mantendo barra **{prev_bus}** da simulação anterior.\n\n"
                        "**Qual a potência ativa em MW?**\n\n"
                        "Os limites de potência reativa serão calculados: "
                        "Q_max = √(S² − P²), Q_min = −Q_max"
                    )
                st.session_state.sim_step = "STEP8"
                return (
                    f"Modo **{mode_label}** identificado. Mantendo barra **{prev_bus}**.\n\n"
                    "**Qual a potência nominal da BESS em MVA?**\n\n"
                    "Os limites de potência reativa serão calculados automaticamente: "
                    "Q_max = √(S² − P²), Q_min = −Q_max"
                )
            st.session_state.sim_step = "STEP7"
            return (
                f"Modo **{mode_label}** identificado.\n\n"
                "**Qual é a barra onde deseja inserir a BESS?**"
            )

        # Scenario given directly (name or number) → treat as STEP3 answer
        scenario = _parse_scenario(user_text, db)
        if scenario is not None:
            year = data["years"][data.get("year_idx", 0)]
            for key in ["bess_bus", "bess_bus_number", "bess_mva", "bess_p_mw",
                        "bess_mode", "scenario"]:
                data.pop(key, None)
            data["scenario"] = scenario
            data["year"] = year
            st.session_state.sim_step = "STEP4"
            return f"Cenário selecionado: **{scenario}** — ano **{year}**.\n\n" + _sav_filename_hint(db, scenario, year)

        # Generic yes/continue → go to STEP3 and ask for scenario
        if any(kw in t for kw in ["sim", "outro", "continuar", "próximo", "proximo",
                                   "outro cenário", "outro cenario"]) or t.strip() in ("s", "sim"):
            data.pop("scenario", None)
            for key in ["bess_bus", "bess_bus_number", "bess_mva", "bess_p_mw", "bess_mode"]:
                data.pop(key, None)
            st.session_state.sim_step = "STEP3"
            scenarios = _PARPEL_SCENARIOS if db == "ONS" else _PDE_SCENARIOS
            return "Qual cenário deseja estudar agora?\n\n" + scenarios

        # Anything unrecognized (including out-of-range numbers) always shows
        # the same clarification — never silently ignored, never routed to RAG,
        # and never ends the session without an explicit end signal.
        return (
            "Não entendi sua resposta. Deseja continuar com outro cenário ou "
            "patamar de carga?\n\n"
            "- Responda com o **nome ou número do cenário** para ir direto\n"
            "- Informe um **novo ano** (2026–2040) para trocar o horizonte\n"
            "- Digite **encerrar** para finalizar a sessão de simulação"
        )

    # ── STATCOM STEP Q: collect Q limits ─────────────────────────────────────
    if step == "STATCOM_STEP_Q":
        q_min, q_max = _parse_q_limits(user_text)
        if q_min is None or q_max is None:
            return (
                "Não identifiquei os limites. Por favor, informe Qmin e Qmax em Mvar.\n\n"
                "Exemplo: `Qmin -100 Mvar, Qmax 100 Mvar`"
            )
        data["statcom_q_min"] = q_min
        data["statcom_q_max"] = q_max
        st.session_state.sim_step = "STATCOM_STEP_CBUS"
        return (
            f"Limites reativos: **Qmin = {int(q_min)} Mvar**, **Qmax = {int(q_max)} Mvar**.\n\n"
            "**O STATCOM vai controlar a tensão da própria barra ou de uma barra remota?**\n\n"
            "1. **Barra local (padrão)** — STATCOM controla a tensão da própria barra\n"
            "2. **Barra remota** — informe o número da barra a controlar"
        )

    # ── STATCOM STEP CBUS: controlled bus + generate output ──────────────────
    if step == "STATCOM_STEP_CBUS":
        t = user_text.lower().strip()
        bus_str = data.get("statcom_bus", "99999")
        q_min = data.get("statcom_q_min", -100.0)
        q_max = data.get("statcom_q_max", 100.0)

        controlled_bus = None
        if t == "1" or any(w in t for w in ["local", "própria", "propria", "mesma"]):
            controlled_bus = None
            cb_label = f"barra local ({bus_str})"
        else:
            m = re.search(r"(?<![.,\d])(\d{4,5})\b", user_text)
            if m:
                controlled_bus = int(m.group(1))
                cb_label = f"barra remota **{controlled_bus}**"
            else:
                controlled_bus = None
                cb_label = f"barra local ({bus_str})"

        try:
            bus_int = int(bus_str)
        except (ValueError, TypeError):
            bus_int = 99999

        pwf_block = generate_statcom_block(
            bus_number=bus_int,
            q_min=q_min,
            q_max=q_max,
            controlled_bus=controlled_bus,
        )
        st.session_state.sim_step = "STEP9"
        return (
            f"Barra controlada: **{cb_label}**.\n\n"
            "Copie as linhas abaixo em um editor de texto (ex: Bloco de Notas), "
            "salve como **STATCOM_modificacao.pwf** e carregue no ANAREDE:\n\n"
            f"```\n{pwf_block}\n```\n\n"
            "Após inserir o STATCOM, o quadrado no canto superior direito mudará para "
            "**amarelo** ('Não Convergido'). Isso é normal.\n\n"
            "---\n\n"
            "**Antes de rodar o fluxo de potência, salve o caso com o STATCOM incluído.**\n\n"
            "No ANAREDE:\n"
            "1. Vá em **Histórico > Operações**\n"
            "2. No campo **'Caso'**, coloque um número diferente dos casos já existentes\n"
            "3. Clique em **Salvar**\n\n"
            "Confirme quando o caso estiver salvo."
        )

    # ── NET states: build-from-scratch guided flow ────────────────────────────
    if step.startswith("NET"):
        return _handle_net_state(user_text)

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
    _user = st.session_state["user"]
    st.markdown(f"**{_user.get('full_name', '')}** ({_user.get('email', '')})")
    if st.button("Sair", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.divider()

    _step_labels = {
        "IDLE":             "",
        "IDLE_LT_CONFIRM":  "Confirmação: dados de LT detectados",
        "IDLE_LT_NET_CHOICE": "Escolha: rede nova ou caso existente",
        "NET1_SETUP":   "NET 1: Título e base MVA",
        "NET2_BUSES":   "NET 2: Barras",
        "NET3_LINES":   "NET 3: Linhas",
        "NET4_REVIEW":  "NET 4: Revisão",
        "NET5_GENERATE": "NET 5: Arquivo PWF",
        "NET6_RUN":     "NET 6: Carregar no ANAREDE",
        "NET7_RESULTS": "NET 7: Resultados",
        "STEP1":  "STEP 1: Base de dados",
        "STEP2":  "STEP 2: Ano(s)",
        "STEP3":  "STEP 3: Cenário",
        "STEP4":  "STEP 4: Carregar SAV",
        "STEP6":  "STEP 6: Diagrama LST",
        "STEP7":  "STEP 7: Barra",
        "STEP8":  "STEP 8: Potência BESS",
        "STATCOM_STEP_Q":    "STATCOM: Limites reativos",
        "STATCOM_STEP_CBUS": "STATCOM: Barra controlada",
        "STEP9":  "STEP 9: Salvar caso",
        "STEP10": "STEP 10: Rodar fluxo",
        "STEP11":  "STEP 11: Resultados",
        "STEP11B": "STEP 11B: Contingências N-1",
        "STEP12":  "STEP 12: Próximos passos",
    }

    if st.session_state.sim_status == "paused":
        step_label = _step_labels.get(st.session_state.sim_step, "")
        st.warning(f"⏸️ Simulação pausada\n{step_label}")
        col_resume, col_end = st.columns(2)
        with col_resume:
            if st.button("▶️ Retomar", use_container_width=True):
                st.session_state.sim_status = "active"
                st.session_state.simulation_mode = True
                try:
                    clear_paused_state(st.session_state["session_id"])
                except Exception:
                    pass
                last_q = _current_step_question()
                if last_q:
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": f"Simulação retomada.\n\n{last_q}",
                    })
                st.rerun()
        with col_end:
            if st.button("⏹️ Encerrar", use_container_width=True):
                st.session_state.simulation_mode = False
                st.session_state.sim_step = "IDLE"
                st.session_state.sim_data = {}
                st.session_state.sim_status = None
                try:
                    clear_paused_state(st.session_state["session_id"])
                except Exception:
                    pass
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": "Simulação encerrada.",
                })
                st.rerun()
    elif st.session_state.sim_status == "active":
        step_label = _step_labels.get(st.session_state.sim_step, "")
        st.success(f"🔬 Modo: Guia de Simulação\n{step_label}")
        if st.button("⏸️ Pausar simulação", use_container_width=True):
            st.session_state.sim_status = "paused"
            st.session_state.simulation_mode = False
            try:
                save_paused_state(
                    st.session_state["session_id"],
                    st.session_state.sim_step,
                    st.session_state.sim_data,
                )
            except Exception:
                pass
            st.session_state.messages.append({
                "role": "assistant",
                "content": (
                    "Simulação pausada. Você pode fazer perguntas livres.\n\n"
                    "Use o botão **▶️ Retomar** na barra lateral ou digite "
                    "**retomar** para voltar à simulação."
                ),
            })
            st.rerun()
    else:
        st.info("💬 Modo: Conversa Livre")

    st.divider()
    if st.button("🗑️ Limpar conversa", use_container_width=True):
        st.session_state.messages = [st.session_state.messages[0]]
        st.session_state.simulation_mode = False
        st.session_state.sim_step = "IDLE"
        st.session_state.sim_data = {}
        st.session_state.sim_status = None
        st.session_state.study = StudyState()
        st.session_state.chain = None
        st.session_state.chain_error = None
        clear_study()
        try:
            clear_paused_state(st.session_state["session_id"])
        except Exception:
            pass
        st.rerun()

    st.divider()
    st.caption(
        "💡 O processo de simulação é conduzido inteiramente "
        "pelo chat. Não é necessário fazer upload de arquivos."
    )
    st.caption("v6.3.0")

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

    # Log user message + update session
    try:
        log_chat_message(
            st.session_state["user"]["id"],
            st.session_state["session_id"],
            "user", prompt,
            st.session_state.get("sim_step"),
        )
        update_session(
            st.session_state["session_id"],
            sim_type=st.session_state.sim_data.get("sim_type"),
            sim_step=st.session_state.get("sim_step"),
        )
    except Exception:
        pass

    # ── Handle "retomar" text command while paused ─────────────────────────────
    _resume_kws = ["retomar", "continuar simulação", "continuar simulacao",
                   "voltar à simulação", "voltar a simulacao", "resume"]
    if st.session_state.sim_status == "paused" and any(
        kw in prompt.lower() for kw in _resume_kws
    ):
        st.session_state.sim_status = "active"
        st.session_state.simulation_mode = True
        try:
            clear_paused_state(st.session_state["session_id"])
        except Exception:
            pass
        last_q = _current_step_question()
        _resume_msg = "Simulação retomada."
        if last_q:
            _resume_msg += f"\n\n{last_q}"
        with st.chat_message("assistant"):
            st.markdown(_resume_msg)
        st.session_state.messages.append({"role": "assistant", "content": _resume_msg})
        try:
            log_chat_message(
                st.session_state["user"]["id"],
                st.session_state["session_id"],
                "assistant", _resume_msg,
                st.session_state.get("sim_step"),
            )
        except Exception:
            pass
        save_study(st.session_state.study)
        st.stop()

    # ── Auto-resume: if paused and user gives a simulation-like answer ────────
    if st.session_state.sim_status == "paused" and not _is_free_question(prompt):
        # Check if the answer looks like it could advance the sim state machine
        _test_step = st.session_state.sim_step
        if _test_step not in ("IDLE", "STEP12") and not _is_simulation_intent(prompt):
            st.session_state.sim_status = "active"
            st.session_state.simulation_mode = True
            try:
                clear_paused_state(st.session_state["session_id"])
            except Exception:
                pass

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
            study_context = st.session_state.study.summary()
            full_prompt = prompt
            # If user just declined IDLE_LT_CONFIRM, answer their original question
            _lt_q = st.session_state.get("_lt_confirm_question")
            if _lt_q:
                full_prompt = _lt_q
                del st.session_state["_lt_confirm_question"]

            # Inject compact simulation context nudge if mid-simulation
            active_step = st.session_state.sim_step
            sim_context_note = ""
            if active_step not in ("IDLE", "STEP12") and st.session_state.sim_status == "active":
                _nudge_labels = {
                    "NET1_SETUP":   "título e base MVA",
                    "NET2_BUSES":   "dados das barras",
                    "NET3_LINES":   "dados das linhas",
                    "NET4_REVIEW":  "revisão da rede",
                    "NET5_GENERATE": "arquivo PWF gerado",
                    "NET6_RUN":     "resultado do fluxo",
                    "NET7_RESULTS": "resultados da simulação",
                    "STEP1": "base de dados",
                    "STEP2": "ano(s)",
                    "STEP3": "cenário de carga",
                    "STEP4": "convergência do caso base",
                    "STEP6": "diagrama LST",
                    "STEP7": "barra de inserção",
                    "STEP8": "potência da BESS",
                    "STATCOM_STEP_Q": "limites reativos",
                    "STATCOM_STEP_CBUS": "barra controlada",
                    "STEP9": "confirmação de salvamento",
                    "STEP10": "resultado do fluxo",
                    "STEP11": "análise de resultados",
                    "STEP11B": "contingências N-1",
                }
                nudge = _nudge_labels.get(active_step, "próximo passo")
                sim_context_note = (
                    f"\n\n---\n↩️ Quando terminar, responda sobre **{nudge}** "
                    "para continuar a simulação."
                )

            with st.spinner("Consultando base de conhecimento..."):
                try:
                    result = st.session_state.chain.invoke({
                        "question": full_prompt,
                        "study_context": study_context,
                    })
                    answer = result["answer"] + sim_context_note
                    sources = list({
                        doc.metadata.get("source", "desconhecido")
                        for doc in result.get("source_documents", [])
                    })
                except Exception as e:
                    answer = (
                        f"Ocorreu um erro ao processar sua pergunta: `{e}`\n\n"
                        "Verifique se o Qdrant e o Ollama estão acessíveis."
                    ) + sim_context_note
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

    # Log assistant message
    try:
        log_chat_message(
            st.session_state["user"]["id"],
            st.session_state["session_id"],
            "assistant", answer,
            st.session_state.get("sim_step"),
        )
    except Exception:
        pass

    save_study(st.session_state.study)
