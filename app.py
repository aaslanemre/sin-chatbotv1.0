import hashlib
import importlib
import re
import streamlit as st
from agents.pwf_agent import generate_dbar_block
from agents.results_analyzer import save_results_file, check_convergence, format_results_report
from utils.anarede_lib import generate_dlin_block
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

if "simulation_mode" not in st.session_state:
    st.session_state.simulation_mode = False


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


def _parse_years(text: str) -> list[int]:
    """Return list of years found in text."""
    return [int(y) for y in re.findall(r"\b(20\d\d)\b", text)]


def _parse_scenario(text: str, db: str):
    t = text.strip().lower()
    lookup = _PARPEL_SCENARIO_NAMES if db in ("ONS", "PARPEL") else _PDE_SCENARIO_NAMES
    m = re.match(r"^(\d)$", t)
    if m and m.group(1) in lookup:
        return lookup[m.group(1)]
    for key, name in lookup.items():
        if key in t or key.replace("ú", "u").replace("ã", "a").replace("é", "e") in t:
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
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:mva|mw|MW|MVA)?", text)
    if m:
        return m.group(1).replace(",", ".")
    return None


def _bess_pwf_lines(data: dict) -> str:
    bus_from   = data.get("bess_bus", "")         # existing bus (bus_from)
    bus_to     = data.get("bess_bus_number", "")  # new BESS bus (bus_to)
    mva        = data.get("bess_mva", "100")
    mode_type  = "2" if data.get("bess_mode") == "PV" else "1"
    try:
        s = float(mva)
    except Exception:
        s = 100.0

    # DBAR block — new BESS bus, Q limits at max (P=0 → Q_max = S)
    dbar_block = generate_dbar_block(
        bus_number=bus_to,
        bus_name=f"BESS_{str(bus_from)[:5]}",
        bus_type=mode_type,
        S_mva=s,
        P_mw=0.0,
    )
    # DLIN block — dummy branch from existing bus to new BESS bus
    dlin_block = generate_dlin_block(
        bus_from=bus_from,
        bus_to=bus_to,
        reactance=0.00001,
    )
    return (
        "Copie as linhas abaixo em um editor de texto (ex: Bloco de Notas), "
        "salve como **BESS_modificacao.pwf** e carregue no ANAREDE:\n\n"
        f"```\n"
        f"{dbar_block}\n\n"
        f"{dlin_block}\n\n"
        f"FIM\n"
        f"```\n\n"
        "Após inserir a BESS, o quadrado no canto superior direito mudará para "
        "**amarelo** ('Não Convergido'). Isso é normal."
    )


def _handle_sim_state(user_text: str) -> str | None:
    """
    Drive the simulation state machine.
    Returns a template response string, or None if the LLM should answer.
    """
    step = st.session_state.sim_step
    data = st.session_state.sim_data

    # ── IDLE: check for simulation intent ─────────────────────────────────────
    if step == "IDLE":
        if _is_simulation_intent(user_text):
            st.session_state.simulation_mode = True
            st.session_state.sim_step = "STEP1"
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
        return None  # Let LLM answer

    # ── STEP 1: waiting for EPE/ONS choice ────────────────────────────────────
    if step == "STEP1":
        t = user_text.strip().lower()
        if t == "1" or any(w in t for w in ["epe", "pde", "expansão", "expansao", "longo prazo"]):
            data["db"] = "EPE"
            label = "PDE (EPE)"
        elif t == "2" or any(w in t for w in ["ons", "par", "pel", "operacional"]):
            data["db"] = "ONS"
            label = "PAR/PEL (ONS)"
        else:
            return (
                "Não identifiquei a escolha. Por favor, responda com **1** (EPE/PDE) "
                "ou **2** (ONS/PAR/PEL)."
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
        if _is_converged(user_text):
            st.session_state.sim_step = "STEP6"
            return (
                "Perfeito! O caso base está convergido.\n\n"
                "---\n\n"
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
        elif _is_not_converged(user_text):
            return (
                "O caso base não está convergido, o que é incomum pois os casos da "
                "EPE e ONS já vêm convergidos. Verifique se:\n\n"
                "- Carregou o arquivo SAV correto\n"
                "- Selecionou o caso correto em **Histórico > Operações**\n"
                "- O arquivo não está corrompido\n\n"
                "Tente recarregar o arquivo e informe novamente o que aparece "
                "no canto superior direito."
            )
        else:
            return "O que aparece no canto superior direito do ANAREDE após carregar o caso?"

    # ── STEP 6: LST diagram ───────────────────────────────────────────────────
    if step == "STEP6":
        st.session_state.sim_step = "STEP7"
        return (
            "Ótimo!\n\n"
            "**Agora vamos modelar a BESS.**\n\n"
            "Qual é a barra onde deseja inserir a BESS?\n\n"
            "Dica: escolha a subestação com maior carga na área de estudo "
            "que disponha de margem para injeção de potência. O ONS disponibiliza "
            "mapas interativos e relatórios indicando a margem de escoamento de "
            "geração das subestações da rede básica."
        )

    # ── STEP 7: bus identification + BESS mode ───────────────────────────────
    if step == "STEP7":
        if "bess_bus" not in data:
            # Parse bus from user message — accept any number or name
            bus_match = re.search(r"\b(\d{4,5})\b", user_text)
            if bus_match:
                data["bess_bus"] = bus_match.group(1)
            else:
                # Accept any non-trivial text as bus name
                stripped = user_text.strip()
                if len(stripped) >= 2:
                    data["bess_bus"] = stripped
                else:
                    return (
                        "Não identifiquei a barra. Por favor, informe o número "
                        "ou nome da barra onde deseja inserir a BESS."
                    )
            bus = data["bess_bus"]
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
            # Sub-step 8a: collect apparent power rating
            mva = _parse_mva(user_text)
            if mva is None:
                return "Não identifiquei a potência. Por favor, informe o valor em MVA (ex: **100**)."
            data["bess_mva"] = mva
            return (
                f"Potência nominal: **{mva} MVA**.\n\n"
                "Qual número de barra está disponível no seu caso para a nova barra da BESS?\n\n"
                "(escolha um número que não exista no caso atual)"
            )
        else:
            # Sub-step 8b: collect new BESS bus number, then generate output
            bus_num_match = re.search(r"\b(\d{4,5})\b", user_text)
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
            st.session_state.sim_step = "STEP11"
            return (
                "Ótimo! O caso convergiu.\n\n"
                "Salve o caso convergido (pode sobrescrever o caso salvo no passo anterior).\n\n"
                "**Para verificar o impacto da BESS no diagrama:**\n"
                "- Sobrecargas e sobretensões aparecem com **hachura VERMELHA**\n"
                "- Subtensões aparecem com **hachura AZUL**\n"
                "- Verifique também os impactos na barra de referência e nas "
                "principais barras de geração do SIN\n\n"
                "O que você está observando no diagrama?"
            )
        elif _is_not_converged(user_text):
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
        st.session_state.sim_step = "STEP12"
        return (
            "Obrigado pela análise!\n\n"
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

    # ── STEP 12: offer next iteration ─────────────────────────────────────────
    if step == "STEP12":
        t = user_text.lower()
        if any(kw in t for kw in ["sim", "outro", "continuar", "próximo", "proximo", "outro cenário"]):
            # Reset to STEP3 to pick a new scenario for the same year, or STEP2 for new year
            data.pop("scenario", None)
            st.session_state.sim_step = "STEP3"
            db = data.get("db", "ONS")
            scenarios = _PARPEL_SCENARIOS if db == "ONS" else _PDE_SCENARIOS
            return "Qual cenário deseja estudar agora?\n\n" + scenarios
        # Let LLM handle general questions
        return None

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
            "IDLE":  "",
            "STEP1":  "STEP 1: Base de dados",
            "STEP2":  "STEP 2: Ano(s)",
            "STEP3":  "STEP 3: Cenário",
            "STEP4":  "STEP 4: Carregar SAV",
            "STEP6":  "STEP 6: Diagrama LST",
            "STEP7":  "STEP 7: Barra / Modo BESS",
            "STEP8":  "STEP 8: Potência BESS",
            "STEP9":  "STEP 9: Salvar caso",
            "STEP10": "STEP 10: Rodar fluxo",
            "STEP11": "STEP 11: Resultados",
            "STEP12": "STEP 12: Próximos passos",
        }.get(st.session_state.sim_step, "")
        st.success(f"🔬 Modo: Guia de Simulação\n{step_label}")
    else:
        st.info("💬 Modo: Conversa Livre")

    st.divider()
    if st.button("🗑️ Limpar conversa", use_container_width=True):
        st.session_state.messages = [st.session_state.messages[0]]
        st.session_state.simulation_mode = False
        st.session_state.sim_step = "IDLE"
        st.session_state.sim_data = {}
        st.session_state.study = StudyState()
        st.session_state.chain = None
        st.session_state.chain_error = None
        clear_study()
        st.rerun()

    st.divider()
    st.caption(
        "💡 O processo de simulação é conduzido inteiramente "
        "pelo chat. Não é necessário fazer upload de arquivos."
    )
    st.caption("v3.0 experimental")

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
            study_context = st.session_state.study.summary()
            full_prompt = prompt

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
