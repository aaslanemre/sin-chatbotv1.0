"""
ANATEM guided flow (v6.6.0) — GUIDE ONLY.

Pure module: no Streamlit and no DB imports. A deterministic state machine
(regex + buttons/forms, the LLM never runs here) that tells the user what to do
in ANAREDE/ANATEM at each step of a dynamic (electromechanical stability) study.
It generates NO ANATEM text: no DEVT, STB, DMAQ, DFNT, TITU, DSIM/EXSI lines.

Main flow (SIN base, ONS or EPE):
  AT1 → AT2 → AT3 (ANAT0) → AT4 → AT5 → AT6 → AT7 → AT8 → (AT9 ⇄ AT8) → AT10 → AT11 → end
Small case / own network (option 3 at AT1, no ANAT0):
  AT1 → ATS2 → ATS3 → ATS4 (→ AT9 → ATS4) → ATS5 → end

v6.6.1 (revised Word guide + expert feedback P1–P5): ATS2 first asks whether the
user has a .SAV and a .STB (example-case guidance when not); AT6/ATS3 first ask
"conventional study or new equipment?"; AT5 uses the DARQ-only wording; AT8/ATS4
name the menu and F5; AT11/ATS5 offer a menu of event types (names only).

handle(step, data, text) -> (new_step, reply). new_step "IDLE" means the
simulation ends (the app resets its state). `data` (sim_data) is mutated in place
and only holds JSON-serialisable values (persisted on pause like the other flows).

Router helpers (names_anatem, is_anatem_intent, is_generic_sim_intent, ...) are
used by app.py to start this flow, to ask "ANAREDE ou ANATEM?" and to hand an
ANAREDE study over to this flow (build_handoff / initial_data).

Every user-facing technical text block below is marked
PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel): it is a condensed version of
the procedure in the experts' Word file and is not validated against the
ANATEM manual (codes, menus and columns are not checked here).
"""

import re
import unicodedata

from agents.ux import with_details

SIM_TYPE = "ANATEM"
PROGRAM_CHOICE_STEP = "IDLE_PROGRAM_CHOICE"

MAIN_STEPS = ["AT1", "AT2", "AT3", "AT4", "AT5", "AT6", "AT7", "AT8", "AT9", "AT10", "AT11"]
SMALL_STEPS = ["AT1", "ATS2", "ATS3", "ATS4", "ATS5"]
ALL_STEPS = MAIN_STEPS + SMALL_STEPS[1:]
EVENT_STEPS = ("AT11", "ATS5")

STEP_LABELS = {
    "AT1": "ANATEM 1: Porte e origem do caso",
    "AT2": "ANATEM 2: Caso base convergido",
    "AT3": "ANATEM 3: ANAT0",
    "AT4": "ANATEM 4: DMAQ ajustado",
    "AT5": "ANATEM 5: Edição do .stb",
    "AT6": "ANATEM 6: Equipamentos",
    "AT7": "ANATEM 7: Simulação de verificação",
    "AT8": "ANATEM 8: Primeira execução",
    "AT9": "ANATEM 9: Erro de inicialização (CDU)",
    "AT10": "ANATEM 10: Verificação das variáveis",
    "AT11": "ANATEM 11: Eventos (DEVT)",
    "ATS2": "ANATEM caso pequeno 2: .stb e DMAQ",
    "ATS3": "ANATEM caso pequeno 3: Equipamentos",
    "ATS4": "ANATEM caso pequeno 4: Teste sem eventos",
    "ATS5": "ANATEM caso pequeno 5: Eventos (DEVT)",
}

# "↩️ Quando terminar, responda sobre **…**" after a free question mid-flow.
NUDGE_LABELS = {
    "AT1": "a base do caso (ONS, EPE ou caso pequeno)",
    "AT2": "o arquivo .sav e o número do caso",
    "AT3": "o resultado do ANAT0",
    "AT4": "o nome do arquivo DMAQ",
    "AT5": "a edição do .stb",
    "AT6": "os modelos dos equipamentos",
    "AT7": "a preparação da simulação sem eventos",
    "AT8": "o resultado da execução no ANATEM",
    "AT9": "o erro de CDU",
    "AT10": "as variáveis plotadas",
    "AT11": "os eventos (DEVT)",
    "ATS2": "o .sav, o caso e as barras de geração",
    "ATS3": "os modelos dos equipamentos",
    "ATS4": "o teste sem eventos",
    "ATS5": "os eventos (DEVT)",
}

BASE_LABELS = {"ONS": "SIN — base ONS", "EPE": "SIN — base EPE",
               "PEQUENO": "Caso pequeno / rede própria"}
BASE_SHORT = {"ONS": "ONS", "EPE": "EPE", "PEQUENO": "Pequeno"}
# ANAREDE choice → AT1 option (handoff pre-selection)
HANDOFF_BASE = {"ONS": "ONS", "EPE": "EPE", "NETWORK": "PEQUENO"}

# Canonical answers (button texts). structured_input builds the buttons from
# these, and the parsers below accept them, so a click == typing the text.
T_ONS, T_EPE, T_SMALL = "SIN ONS", "SIN EPE", "Caso pequeno"
T_CONFIRM = "Confirmar"
T_RAN_OK, T_RAN_ERR = "Rodou sem erros", "Deu erro"
T_RUN_CDU_ERR = "Deu erro em um ou mais CDUs"
T_CONFIGURED = "Configurado"
T_YES, T_ALREADY = "Sim", "Já incluídos no .stb"
T_MODELS_DONE = "Modelos incluídos"
T_READY = "Pronto"
T_IN_DMAQ = "É de máquina síncrona (está no DMAQ)"
T_NOT_DMAQ = "Não está no DMAQ (eólica/FV/elo CC)"
T_GOV = "Regulador de velocidade (GOV)"
T_AVR = "Regulador de tensão (AVR) ou PSS"
T_FLAT, T_VARYING = "Flat (constante)", "Variando"
T_SMALL_OSC = "Oscilação ≤ 0,001 pu (ondas triangulares/escadinha)"
T_LARGE_OSC = "Oscilação maior"
T_ADD_EVENT, T_END = "Adicionar outro evento", "Encerrar"
T_CONFIRM_MODELS, T_NO_MODELS = "Confirmar inclusão dos modelos", "Sem equipamentos"
T_FLAT_LINE, T_ERROR = "Flat (linha reta)", "Erro"
T_PROGRAM_ANAREDE, T_PROGRAM_ANATEM = "ANAREDE", "ANATEM"
# v6.6.1
T_HAS_FILES, T_NO_FILES = "Sim, já tenho", "Não tenho / quero um caso de exemplo"
T_FILES_CONTINUE = "Já tenho o .SAV e o .STB, continuar"
T_CONVENTIONAL = "Estudo convencional"
# The button reads "Incluir BESS/STATCOM/HVDC"; the text it sends must not start with
# "incluir … BESS", which app.py's ANAREDE-intent guard reads as a new ANAREDE request.
T_INCLUDE_EQUIP_LABEL, T_INCLUDE_EQUIP = "Incluir BESS/STATCOM/HVDC", "Com equipamentos: BESS/STATCOM/HVDC"
T_EVENT_DONE = "Evento inserido"
START_TEXT = {"ANAREDE": "Iniciar simulação ANAREDE", "ANATEM": "Iniciar simulação ANATEM"}
HANDOFF_TEXT = "Continuar para o ANATEM"


# ── normalisation ─────────────────────────────────────────────────────────────

def norm(text) -> str:
    """Lowercase, accents stripped, non-alphanumerics → spaces (same as app._normalize_str)."""
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _has(n, *words) -> bool:
    """Any of the (normalised) words/phrases appears in n as whole words."""
    return any(re.search(rf"\b{re.escape(w)}\b", n) for w in words)


# ── router (used by app.py at IDLE) ───────────────────────────────────────────

# Phrases that start the ANATEM flow directly (accent/case-insensitive).
_ANATEM_INTENT_TRIGGERS = [
    "quero passar meu caso para o anatem", "passar meu caso para o anatem",
    "iniciar simulação dinâmica", "iniciar simulacao dinamica",
    "quero iniciar uma simulação no anatem", "simulação no anatem",
    "quero simular no anatem", "rodar no anatem", "simulação dinâmica",
    "simulação de estabilidade", "estudo de estabilidade",
    "estabilidade eletromecânica", "análise transitória", "rodar o anat0",
    "usar o anat0", "preciso do anat0", "migrar para o anatem", "handoff anatem",
]
_TRIGGERS_NORM = [norm(t) for t in _ANATEM_INTENT_TRIGGERS]

# Single-word / ambiguous cues: only with a verb of intent.
_CUE_RE = re.compile(r"\b(?:anatem|anat0|dinamica|dinamico|estabilidade|transitori[oa]s?)\b")
_VERB_RE = re.compile(
    r"\b(?:quero|queria|preciso|precisaria|gostaria|vamos|iniciar|inicie|simular|simule|"
    r"rodar|rode|fazer|faca|comecar|comece|passar|passe)\b")
_ANATEM_NAME_RE = re.compile(r"\b(?:anatem|anat0)\b")
_ANAREDE_NAME_RE = re.compile(r"\banarede\b")
_ANAREDE_EQUIPMENT_RE = re.compile(r"\b(?:bess|baterias?|armazenamento|statcom)\b")
_QUESTION_START_RE = re.compile(
    r"^(?:como|o que|que|qual|quais|quando|onde|por que|porque|pra que|para que|quem|quanto|"
    r"sera|explique|me explique|fale sobre|me fale)\b")
_DESIRE_START_RE = re.compile(r"^(?:quero|queria|preciso|gostaria|vamos|iniciar|inicie|rodar|simular)\b")
_GENERIC_SIM_RE = re.compile(
    r"\b(?:quero|queria|preciso|precisaria|gostaria|vou|vamos|desejo|pretendo|iniciar|inicie|"
    r"comecar|comece|fazer|faca|rodar|rode)\b.*\bsimula(?:r|cao|coes)\b")


def names_anatem(text) -> bool:
    return bool(_ANATEM_NAME_RE.search(norm(text)))


def names_anarede(text) -> bool:
    return bool(_ANAREDE_NAME_RE.search(norm(text)))


def mentions_anarede_equipment(text) -> bool:
    return bool(_ANAREDE_EQUIPMENT_RE.search(norm(text)))


def is_question(text) -> bool:
    n = norm(text)
    if _QUESTION_START_RE.search(n):
        return True
    return str(text or "").strip().endswith("?") and not _DESIRE_START_RE.search(n)


def is_anatem_intent(text) -> bool:
    """A trigger phrase, or an ANATEM/dynamics cue together with a verb of intent.
    Questions ("O que é o ANATEM?", "Como funciona o ANAT0?") are never an intent."""
    if is_question(text):
        return False
    n = norm(text)
    if any(re.search(rf"\b{re.escape(t)}\b", n) for t in _TRIGGERS_NORM):
        return True
    return bool(_CUE_RE.search(n) and _VERB_RE.search(n))


def is_generic_sim_intent(text) -> bool:
    """'quero fazer uma simulação' — a simulation request that names no program."""
    if is_question(text):
        return False
    return bool(_GENERIC_SIM_RE.search(norm(text)))


def classify_program_choice(text):
    """Answer to 'ANAREDE ou ANATEM?': 'ANAREDE' | 'ANATEM' | 'CANCEL' | None."""
    n = norm(text)
    ar = n == "1" or _has(n, "anarede", "fluxo de potencia", "regime permanente")
    at = n == "2" or _has(n, "anatem", "anat0", "dinamica", "estabilidade")
    if ar and not at:
        return "ANAREDE"
    if at and not ar:
        return "ANATEM"
    if not ar and not at and _has(n, "cancelar", "cancela", "nenhum", "nao", "encerrar", "sair"):
        return "CANCEL"
    return None


PROGRAM_CHOICE_QUESTION = (
    "**Qual programa você quer usar?**\n\n"
    "⚡ **ANAREDE** — fluxo de potência (regime permanente)\n\n"
    "🌀 **ANATEM** — estabilidade eletromecânica (dinâmica)"
)
PROGRAM_CHOICE_RETRY = (
    "Não identifiquei o programa. Responda **ANAREDE** (ou **1**) ou **ANATEM** (ou **2**), "
    "ou **cancelar**.\n\n" + PROGRAM_CHOICE_QUESTION
)


# ── handoff ANAREDE → ANATEM ──────────────────────────────────────────────────

def _join(values):
    vals = [str(v) for v in values if v not in (None, "")]
    return ", ".join(vals) or None


def build_handoff(anarede_data, bess_devices=()) -> dict:
    """What the ANAREDE study captured, nothing more. The ANAREDE flow never asks
    for a .sav name or a case number, so those are None unless present in sim_data."""
    d = anarede_data or {}
    stype = d.get("sim_type") or "BESS"
    eq_type, eq_bus, mva = None, None, None
    if stype == "BESS":
        eq_type = "BESS"
        devs = list(bess_devices or [])
        eq_bus = _join(dev.get("bess_bus_number") for dev in devs)
        mva = _join(dev.get("bess_mva") for dev in devs)
    elif stype == "STATCOM":
        eq_type = "STATCOM"
        eq_bus = _join([d.get("statcom_bus")])
    return {
        "sim_type": stype,
        "sav_name": d.get("sav_name") or None,
        "case_number": d.get("case_number") or None,
        "equipment_type": eq_type,
        "equipment_bus": eq_bus,
        "mva": mva,
        "year": d.get("year"),
        "scenario": d.get("scenario"),
        "base": "NETWORK" if stype == "NETWORK" else d.get("db"),
    }


def initial_data(handoff=None) -> dict:
    data = {"sim_type": SIM_TYPE}
    if handoff:
        data["handoff"] = dict(handoff)
        suggested = HANDOFF_BASE.get(handoff.get("base"))
        if suggested:
            data["base_suggested"] = suggested
        if handoff.get("sav_name"):
            data["sav_name"] = handoff["sav_name"]
        if handoff.get("case_number"):
            data["case_number"] = str(handoff["case_number"])
    return data


def _handoff_equipment_line(data) -> str:
    h = data.get("handoff") or {}
    if not h.get("equipment_type"):
        return ""
    line = f"Do estudo no ANAREDE: **{h['equipment_type']}**"
    if h.get("equipment_bus"):
        line += f" na barra **{h['equipment_bus']}**"
    if h.get("mva"):
        line += f" ({h['mva']} MVA)"
    return line + "."


# ── texts ─────────────────────────────────────────────────────────────────────

# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
INTRO_FULL = (
    "Vou te guiar na **simulação dinâmica no ANATEM**, passo a passo. "
    "Eu não gero arquivos do ANATEM: indico o que fazer em cada etapa.\n\n"
    "**Antes de começar, confira:**\n"
    "1. A **base de dados dinâmica** (ONS ou EPE) está disponível.\n"
    "2. Os casos de fluxo de potência do SIN no ANAREDE normalmente **não** vêm ajustados "
    "para rodar direto com a base do ANATEM, o que causa erros de inicialização. Por isso, "
    "para casos do SIN, **rodar o ANAT0 antes é obrigatório**.\n"
    "3. Os modelos dinâmicos (**.cdu/.blq**) do BESS, STATCOM ou elo VSC-HVDC já estão "
    "validados e prontos para incluir."
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
INTRO_SHORT = (
    "Vou te guiar na **simulação dinâmica no ANATEM**. Lembre: base dinâmica disponível, "
    "ANAT0 obrigatório para casos do SIN e modelos .cdu/.blq validados."
)

_AT1_OPTIONS = (
    "1. **SIN — base ONS**\n"
    "2. **SIN — base EPE**\n"
    "3. **Caso pequeno / rede própria** (sem ANAT0)"
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_AT1_NOTE = "Tenha a pasta da base dinâmica do ONS ou da EPE **descompactada** no computador."


def _at1_question(data) -> str:
    sug = data.get("base_suggested")
    if sug:
        what = "o **caso pequeno / rede própria**" if sug == "PEQUENO" else f"a base **{BASE_SHORT[sug]}**"
        head = f"**Passo 1 — Porte e origem do caso.** Vamos manter {what}?"
        h = data.get("handoff") or {}
        ctx = ", ".join(str(v) for v in (h.get("year"), h.get("scenario")) if v)
        if ctx:
            head += f" (estudo no ANAREDE: {ctx})"
        return head + "\n\n" + _AT1_OPTIONS + "\n\nResponda **sim** para manter, ou escolha outra opção."
    return "**Passo 1 — Porte e origem do caso.** Qual caso você vai simular?\n\n" + _AT1_OPTIONS


def start_message(data, full_intro=True) -> str:
    intro = INTRO_FULL if full_intro else INTRO_SHORT
    return with_details(intro + "\n\n---\n\n" + _at1_question(data), _AT1_NOTE)


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_AT2_ASK = ("**Passo 2 — Caso base convergido.** Qual o nome do arquivo **.sav** e o número "
            "do caso? (ex: `caso_estudo.sav, caso 5`)")
_AT2_NOTE = ("No ANAREDE, o caso deve estar aberto e com o indicador verde **'Convergido'** "
             "no canto superior direito.")


def _at2_question(data) -> str:
    sav, case = data.get("sav_name"), data.get("case_number")
    if data.get("at2_confirm"):
        return (f"**Passo 2 — Caso base convergido.** Do estudo no ANAREDE: arquivo **{sav}**, "
                f"caso **{case}**. Confirma? (ou informe outro arquivo e caso)")
    if sav and not case:
        return f"Arquivo **{sav}** registrado. Qual o **número do caso**? (ex: `caso 5`)"
    if case and not sav:
        return f"Caso **{case}** registrado. Qual o nome do arquivo **.sav**? (ex: `caso_estudo.sav`)"
    return _AT2_ASK


def _base_folder(data) -> str:
    return {"ONS": "do ONS", "EPE": "da EPE"}.get(data.get("base"), "do ONS ou da EPE")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _at3_main(data) -> str:
    return (
        "**Passo 3 — ANAT0.** No ANAREDE, abra **Análise > ANAT0**:\n"
        "1. Aba **Opções**: marque a **primeira caixa** (usar o caso que já está na memória).\n"
        f"2. Aba **Etapa 1**: carregue **BNT1.DAT**, **BNT2.DAT** e **DMAQ.STB**, da pasta "
        f"**ANAT0** dentro da base {_base_folder(data)}.\n"
        "3. Em **'Arquivo DMAQ com número de unidades'**, informe o arquivo de saída "
        "(um arquivo existente é sobrescrito; ou use um nome novo).\n"
        "4. Execute.\n\n"
        "**O ANAT0 rodou sem erros?**"
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_AT3_DETAILS = (
    "O procedimento é idêntico para ONS e EPE; só muda a pasta da base.\n\n"
    "A **Etapa 2** não é usada para a inicialização. Os campos **'Arquivo Histórico de "
    "Origem/Destino'** só importam quando o caso não está na memória e a primeira caixa "
    "está desmarcada.\n\n"
    "Por que o ANAT0: no ANAREDE, uma usina do SIN é **uma única barra PV**; no ANATEM, ela é "
    "representada por **várias máquinas individuais**. O ANAT0 distribui a geração da barra "
    "entre as máquinas e ajusta o número de unidades ao ponto de operação do caso."
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_AT3_ERROR = (
    "**Erro no ANAT0.** O ANAT0 indica **violação de limite de potência ativa ou reativa** ao "
    "dividir a geração da barra entre as máquinas: a barra, no ANAREDE, está num ponto de "
    "operação incompatível com a capacidade das máquinas cadastradas.\n\n"
    "**Como corrigir:**\n"
    "1. Volte ao ANAREDE.\n"
    "2. Ajuste a geração ativa, ou alivie a geração/absorção de reativo dessa barra.\n"
    "3. Salve o **.sav** novamente.\n"
    "4. Rode o ANAT0 de novo.\n\n"
    "**O ANAT0 rodou sem erros?**"
)

# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.1: neutral example. OPEN: the Word file uses "dmaq_anat0.dma" here and ".DMA/.DAT"
# in the DARQ definition, the feedback talks about "DMAQ.DAT" — extension not settled.
_AT4_ASK = ("**Passo 4 — DMAQ ajustado.** Qual o nome do arquivo salvo pelo ANAT0? "
            "(ex: `dmaq_anat0`, com a extensão que você escolheu)")
_AT4_DETAILS = ("Esse arquivo contém o bloco **DMAQ** com o número de unidades de cada máquina "
                "síncrona ajustado ao ponto de operação.")


def _known(value) -> str:
    return f" (**{value}**)" if value else ""


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.1 (P3): wording of the revised Word file; only DARQ in the instructions.
def _at5_main(data) -> str:
    return (
        "**Passo 5 — Edição do .stb.** Abra o arquivo **.stb** da base em um editor de texto "
        "e faça três ajustes:\n"
        "1. **Substituir o arquivo .SAV:** No cartão **DARQ**, localize a declaração de arquivo "
        "associada à rede de fluxo de potência e atualize para o nome do seu arquivo .SAV "
        f"convergido{_known(data.get('sav_name'))}.\n"
        "2. **Conferir o número do caso:** Na linha de leitura do .SAV, confirme se o número do "
        "caso especificado corresponde exatamente ao número do caso convergido no ANAREDE e "
        f"processado no ANAT0{_known(data.get('case_number'))}.\n"
        "3. **Substituir o arquivo DMAQ:** No cartão **DARQ**, substitua a referência do arquivo "
        "DMAQ original pelo caminho do novo arquivo gerado pelo ANAT0"
        f"{_known(data.get('dmaq_name'))}.\n\n"
        f"Responda **{T_CONFIGURED}** quando terminar."
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.1 (P3): the main .stb codes as SEPARATE entries (revised Word file). ULOG appears
# only here and in the glossary, never in an instruction nor in a sentence with the other code.
STB_CODES = (
    "**Principais códigos do .stb:**\n"
    "- **ULOG:** Define a atribuição explícita de unidades lógicas computacionais de "
    "leitura/gravação.\n"
    "- **DARQ:** Declara o nome e o caminho dos arquivos externos utilizados na simulação "
    "dinâmica (arquivo .SAV de fluxo, arquivo de máquinas .DMA/.DAT, arquivos de "
    "controladores .CDU).\n\n"
    # expert feedback, split in two sentences so the two codes never share one
    "O cartão ULOG ainda existe em rotinas automatizadas e bases históricas. A atribuição de "
    "nomes de arquivos, porém, deve ser feita, idealmente, no bloco DARQ."
)


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.1 (P2): the equipment step is optional.
_EQUIP_BRANCH_Q = (
    "Seu estudo é puramente eletromecânico convencional (apenas máquinas síncronas e "
    "reguladores básicos) ou você pretende acoplar novos equipamentos de eletrônica de "
    "potência/armazenamento (BESS, STATCOM, elo VSC-HVDC)?"
)


def handoff_has_equipment_bus(data) -> bool:
    """The ANAREDE study carried a BESS/STATCOM bus → 'Incluir' is the default answer."""
    h = (data or {}).get("handoff") or {}
    return bool(h.get("equipment_type") and h.get("equipment_bus"))


def _equip_branch(head, data) -> str:
    text = f"{head} {_EQUIP_BRANCH_Q}"
    line = _handoff_equipment_line(data)
    if line:
        text += f"\n\n{line}"
    if handoff_has_equipment_bus(data):
        text += f" Sugestão: **{T_INCLUDE_EQUIP_LABEL}** (responda **sim** para manter)."
    return text


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _at6_main(data) -> str:
    """After 'Incluir': the v6.6.0 question (Sim / Já incluídos no .stb)."""
    line = _handoff_equipment_line(data)
    return ("**Passo 6 — Equipamentos.** Deseja incluir agora os modelos do **BESS, STATCOM ou "
            f"HVDC** no .stb? Responda **{T_YES}** para ver como, ou **{T_ALREADY}**."
            + (f"\n\n{line}" if line else ""))


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _at6_include(data) -> str:
    h = data.get("handoff") or {}
    where = (f" (do estudo no ANAREDE: {h['equipment_type']} na barra **{h['equipment_bus']}**)"
             if h.get("equipment_type") and h.get("equipment_bus") else "")
    return (
        "Inclua no **.stb** as chamadas aos arquivos dos modelos que você já tem "
        f"(**DCDU**, **DARQ** ou outros), associados às barras dos equipamentos{where}.\n\n"
        f"Responda **{T_MODELS_DONE}** quando terminar."
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_AT7_MAIN = (
    "**Passo 7 — Simulação de verificação (sem eventos).** No **.stb**:\n"
    "1. Desative ou comente os eventos de perturbação no bloco **DEVT**.\n"
    "2. Escolha as variáveis a monitorar no bloco **DPLT**.\n\n"
    f"Responda **{T_READY}** quando terminar."
)
_AT7_DETAILS = ("Essa simulação sem perturbação (flat run) verifica se o caso está bem "
                "inicializado: as variáveis devem ficar constantes.")

# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.1 (P4): same level of detail as the ANAREDE "Ctrl + R" step.
_AT8_MAIN = (
    "**Passo 8 — Primeira execução.** Carregue o **.stb** no ANATEM.\n\n"
    "Execute a simulação no ANATEM:\n"
    "1. Menu superior: **Simulação > Executar**;\n"
    "2. Ou use o atalho de teclado: **F5** para iniciar a simulação dinâmica.\n\n"
    "Depois leia o relatório de saída na janela de mensagens.\n\n"
    "**Rodou sem erros?**"
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
RUN_SHORT = "**Simulação > Executar** ou **F5**"

# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
CDU_NOTE = (
    "Com as bases oficiais do ONS/EPE, os CDUs são considerados validados e **não devem ser "
    "alterados**. O erro normalmente indica que a máquina está num ponto de operação "
    "estressado: a correção é um **ajuste fino do ponto de operação**, não do modelo do controlador."
)
_AT9_ASK = ("**Passo 9 — Erro de inicialização (CDU).** Qual o número do **CDU** indicado no "
            "relatório do ANATEM? (ex: `CDU 1042`)")


def _at9_where(cdu) -> str:
    return f"CDU **{cdu}**. Esse CDU está no arquivo **DMAQ**?"


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _at9_branch_a(data, cdu) -> str:
    dmaq = data.get("dmaq_name")
    dmaq_txt = f"o DMAQ (**{dmaq}**)" if dmaq else "o DMAQ"
    return (
        f"**Passo A** — Abra {dmaq_txt} em um editor de texto e procure (**Ctrl+F**) o "
        f"número **{cdu}**.\n\n"
        "**Passo B** — As primeiras colunas desse registro trazem o **número da barra** e o "
        "**grupo** do gerador.\n\n"
        "**Passo C** — O CDU é de qual controle?"
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_GOV_ADVICE = (
    "**Regulador de velocidade (GOV)** → problema de **potência ativa**. No ANAREDE, reduza "
    "levemente o **Pg** da máquina (ou aumente, se estiver abaixo do mínimo técnico)."
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_AVR_ADVICE = (
    "**Regulador de tensão (AVR) ou PSS** → problema de **tensão/reativo**. Melhore o perfil de "
    "tensão nessa barra (mais perto de **1,0 pu**) ou alivie a injeção/absorção de reativo da "
    "máquina usando taps ou compensadores próximos."
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_PASSO_D_SIN = (
    "**Passo D** — Depois de ajustar e convergir no ANAREDE, salve o **.sav**. Se as mudanças "
    "foram pequenas, **não** é preciso rodar o ANAT0 de novo nem corrigir o DMAQ. Se foram "
    "grandes, rode o ANAT0 novamente ou atualize o DMAQ manualmente. Depois, rode o ANATEM de novo "
    f"({RUN_SHORT})."
)
_PASSO_D_SMALL = ("**Passo D** — Depois de ajustar e convergir no ANAREDE, salve o **.sav** e "
                  f"rode o ANATEM de novo ({RUN_SHORT}).")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _at9_branch_b(cdu) -> str:
    return (
        f"Procure o CDU **{cdu}** nos outros arquivos do ANATEM:\n"
        "- **Usinas eólicas/fotovoltaicas** (os arquivos costumam ter nomes como `EOL_NE.dat` ou "
        "`UFV.DAT`, mas procure independentemente do nome): busque o código **DFNT**, que "
        "associa o CDU à barra do sistema.\n"
        "- **Elos CC**: busque **DCNV** ou **DCNE** (pode haver outros).\n\n"
        "Identifique o equipamento e a barra e ajuste o ponto de operação no ANAREDE como no "
        f"caso da máquina síncrona: salve o **.sav** e rode o ANATEM de novo ({RUN_SHORT})."
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_AT10_MAIN = (
    "**Passo 10 — Verificação das variáveis (PLOTCEPEL).** Abra os gráficos no **PLOTCEPEL**. "
    "Olhe primeiro a **escala do eixo Y**. As variáveis ficaram constantes (flat) ou variando?"
)
_OSC_QUESTION = ("Qual o tamanho da oscilação? (confira a **escala do eixo Y**: oscilações "
                 "≤ 0,001 pu aparecem como ondas triangulares ou em escadinha)")
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_OSC_SMALL = ("Oscilação **≤ 0,001 pu**: é precisão numérica do integrador — pode ignorar. "
              "O caso está **inicializado corretamente**.")
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_OSC_LARGE = ("Oscilação maior que 0,001 pu **não** é efeito numérico. Identifique **qual "
              "variável** está variando e a **qual máquina/CDU** ela pertence; depois ajuste o "
              "ponto de operação.")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.1 (P5): menu of event types. Names and DEVT card codes only — the guide never
# generates DEVT lines or column layouts.
# OPEN: the codes come from tester feedback and are not yet validated.
# (label, description, codes, what the event needs, keywords for the text fallback)
EVENT_TYPES = [
    ("Curto-circuito",
     "aplicação de defeito com instante de início e instante de abertura dos disjuntores "
     "para isolamento da falta", "APCB, APCC, APCL",
     "**onde** é o defeito (barra ou linha), **quando** ele começa (instante de aplicação) e "
     "**quando** termina (instante de abertura dos disjuntores que isolam a falta)",
     ("curto", "curto circuito", "defeito", "falta", "apcb", "apcc", "apcl")),
    ("Perda de linha de transmissão",
     "abertura permanente (ou abertura com religamento) de linha", "ABCI",
     "**qual linha** (barras de/para e circuito), **quando** ela abre e, se houver "
     "religamento, **quando** ela volta",
     ("perda de linha", "linha", "linhas", "lt", "abertura", "religamento", "abci")),
    ("Desligamento de unidade geradora",
     "rejeição de um bloco de geração síncrona", "RMGR",
     "**qual máquina** (barra e grupo), **quando** ela é desligada e **até quando** "
     "(ou se fica desligada até o fim da simulação)",
     ("gerador", "geradora", "geradores", "unidade geradora", "geracao", "maquina", "rmgr")),
    ("Rejeição de carga",
     "desconexão de blocos de demanda em barras de subestações de transmissão", "MDLP e MDLQ",
     "**qual barra**, **quanto** de carga (ativa e reativa) é desconectado e **quando** "
     "(e se volta antes do fim da simulação)",
     ("rejeicao de carga", "rejeicao", "corte de carga", "desconexao de carga", "mdlp", "mdlq")),
]
EVENT_LABELS = [e[0] for e in EVENT_TYPES]
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
EVENT_CODES_NOTE = ("Os códigos acima são os nomes dos cartões do bloco DEVT; a sintaxe exata e as "
                    "colunas devem ser conferidas na documentação do ANATEM.")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _events_main(step) -> str:
    n = "11" if step == "AT11" else "5"
    items = "\n".join(f"{i}. **{label}** — {desc} (código{'s' if ',' in codes or ' e ' in codes else ''}: "
                      f"{codes})" for i, (label, desc, codes, _, _) in enumerate(EVENT_TYPES, 1))
    return (
        f"**Passo {n} — Simulação de eventos (DEVT).** Qual evento você quer simular?\n\n"
        f"{items}\n\n"
        "Escolha pelo botão, pelo número ou pelo nome, ou digite **encerrar**."
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _event_reminder(label) -> str:
    needs = next(e[3] for e in EVENT_TYPES if e[0] == label)
    return (
        f"**{label}.** Para esse evento, defina: {needs}.\n\n"
        "Insira o evento no bloco **DEVT** do .stb (a sintaxe e as colunas estão na documentação "
        f"do ANATEM), rode o ANATEM ({RUN_SHORT}) e salve os resultados.\n\n"
        f"Clique em **{T_EVENT_DONE}** quando terminar, ou descreva o evento "
        "(ex: barra, instantes de início e fim)."
    )


def event_text(event) -> str:
    """One event as readable text: v6.6.1 dict {'type', 'note'} or a v6.6.0 string."""
    if isinstance(event, dict):
        note = event.get("note") or ""
        return (event.get("type") or "Evento") + (f" — {note}" if note else "")
    return str(event)


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.1 (P1): first ask whether the user has a .SAV and a .STB.
_ATS2_FILES_Q = ("**Passo 2 — Caso pequeno.** Você já tem um arquivo .SAV e um .STB para o seu caso?")
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# OPEN: the BESS flow says "Histórico > Operações > Salvar"; the expert wrote
# "Arquivo > Salvar Caso Histórico" — kept as written, to be confirmed.
# OPEN: the exact location of the example .STB is unconfirmed: no file name or path given.
ATS2_EXAMPLE_GUIDE = (
    "**Caso de exemplo.**\n"
    "- A pasta de instalação padrão do ANAREDE traz uma biblioteca de casos didáticos em formato "
    "**.PWF**, por exemplo o sistema-teste IEEE de 9 barras (**9BARRAS.PWF**), com o diagrama "
    "unifilar (**.LST**, ex: `9_barras.lst`) e um arquivo **.STB** desse caso.\n"
    "- No ANAREDE: abra o **9BARRAS.PWF**, rode o fluxo de potência (regime permanente) e salve "
    "o caso convergido como arquivo histórico **.SAV** pelo menu "
    "**Arquivo > Salvar Caso Histórico**.\n"
    "- O **.STB** do caso de exemplo também fica na pasta de instalação. Se você não o "
    "encontrar: este guia não consegue criar o .STB; use um .STB de exemplo da instalação do "
    "ANATEM ou consiga um com um colega.\n\n"
    f"Quando tiver o .SAV e o .STB, clique em **{T_FILES_CONTINUE}**."
)

# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_ATS2_ASK = ("**Passo 2 — Caso pequeno: .stb e DMAQ direto.** Informe o nome do arquivo **.sav**, "
             "o número do caso e as barras de geração (ex: `rede.sav, caso 1, barras 10, 20`).")
_ATS2_DETAILS = "Sem ANAT0: o bloco **DMAQ** é usado diretamente no .stb."


def _ats2_question(data) -> str:
    missing = [lbl for k, lbl in (("sav_name", "o nome do arquivo **.sav**"),
                                  ("case_number", "o **número do caso**"),
                                  ("gen_buses", "as **barras de geração**")) if not data.get(k)]
    if len(missing) == 3:
        return _ATS2_ASK
    return "Falta informar " + " e ".join(missing) + "."


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _ats2_done(data) -> str:
    buses = ", ".join(data["gen_buses"])
    return (
        f"Arquivo **{data['sav_name']}**, caso **{data['case_number']}**, barras de geração "
        f"**{buses}**.\n\n"
        "No arquivo **.stb**:\n"
        "1. **Substituir o arquivo .SAV:** No cartão **DARQ**, localize a declaração de arquivo "
        "associada à rede de fluxo de potência e atualize para o nome do seu arquivo .SAV "
        f"convergido (**{data['sav_name']}**).\n"
        "2. **Conferir o número do caso:** Na linha de leitura do .SAV, confirme se o número do "
        "caso especificado corresponde exatamente ao número do caso convergido no ANAREDE "
        f"(**{data['case_number']}**).\n"
        f"3. Use o bloco **DMAQ** diretamente, com as máquinas das barras **{buses}**."
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _ats3_main(data) -> str:
    """After 'Incluir': the v6.6.0 instruction."""
    line = _handoff_equipment_line(data)
    return ("**Passo 3 — Equipamentos (STATCOM, BESS, elo VSC).** Inclua os blocos dos modelos "
            "diretamente no **.stb**, usando **DFNT** ou outros códigos."
            + (f"\n\n{line}" if line else "")
            + f"\n\nClique em **{T_CONFIRM_MODELS}** quando terminar.")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_ATS4_MAIN = (
    "**Passo 4 — Teste de inicialização sem eventos (flat run).** Desative os eventos do "
    f"**DEVT**, rode o ANATEM ({RUN_SHORT}) e veja as variáveis no **PLOTCEPEL** (olhe primeiro "
    "a escala do eixo Y). As variáveis ficaram em linha reta, variando, ou deu erro?"
)

_STEP_DETAILS = {
    "AT1": _AT1_NOTE, "AT2": _AT2_NOTE, "AT3": _AT3_DETAILS, "AT4": _AT4_DETAILS,
    "AT5": STB_CODES, "AT7": _AT7_DETAILS, "AT9": CDU_NOTE, "ATS2": _ATS2_DETAILS,
    "AT11": EVENT_CODES_NOTE, "ATS5": EVENT_CODES_NOTE,
}


# ── step questions (resume, ajuda, LLM step context) ──────────────────────────

def question(step, data) -> str:
    """The question for the CURRENT step and sub-state (no 'Detalhes')."""
    data = data or {}
    if step == "AT1":
        return _at1_question(data)
    if step == "AT2":
        return _at2_question(data)
    if step == "AT3":
        return _AT3_ERROR if data.get("anat0_error") else _at3_main(data)
    if step == "AT4":
        return _AT4_ASK
    if step == "AT5":
        return _at5_main(data)
    if step == "AT6":
        if data.get("equip") == "pendente":
            return _at6_include(data)
        if data.get("equipment") == "include":
            return _at6_main(data)
        return _equip_branch("**Passo 6 — Equipamentos.**", data)
    if step == "AT7":
        return _AT7_MAIN
    if step == "AT8":
        return _AT8_MAIN
    if step == "AT9":
        cdu = data.get("cdu") or {}
        if not cdu.get("number"):
            return _AT9_ASK
        if not cdu.get("where"):
            return _at9_where(cdu["number"])
        return _at9_branch_a(data, cdu["number"])
    if step in ("AT10", "ATS4"):
        if data.get("osc_pending"):
            return _OSC_QUESTION
        return _AT10_MAIN if step == "AT10" else _ATS4_MAIN
    if step in EVENT_STEPS:
        if data.get("event_pending"):
            return _event_reminder(data["event_pending"])
        if data.get("events") and not data.get("event_menu"):
            return f"**{len(data['events'])} evento(s) registrado(s).** Deseja adicionar outro evento ou encerrar?"
        return _events_main(step)
    if step == "ATS2":
        if ats2_files_question(data):
            return _ATS2_FILES_Q
        if data.get("ats2_files") == "guide":
            return ATS2_EXAMPLE_GUIDE
        return _ats2_question(data)
    if step == "ATS3":
        if data.get("equipment") == "include":
            return _ats3_main(data)
        return _equip_branch("**Passo 3 — Equipamentos.**", data)
    return ""


def ats2_files_question(data) -> bool:
    """ATS2 starts with 'do you have a .SAV and a .STB?' unless a .sav is already known
    (handoff, or back from ATS3) or the question was answered."""
    return not (data or {}).get("sav_name") and not (data or {}).get("ats2_files")


def _entry(step, data) -> str:
    """Message shown when the flow ENTERS `step` (sub-state reset): main + Detalhes."""
    if step == "AT9":
        return _AT9_ASK + "\n\n" + "ℹ️ " + CDU_NOTE
    return with_details(question(step, data), _STEP_DETAILS.get(step, ""))


# Per-step sub-states; entering any step starts it clean.
_SUBSTATE_KEYS = ("at2_confirm", "anat0_error", "cdu", "osc_pending", "ats2_files",
                  "event_pending", "event_menu")


def _enter(step, data, prefix=""):
    for k in _SUBSTATE_KEYS:
        data.pop(k, None)
    if step == "AT2" and data.get("sav_name") and data.get("case_number"):
        data["at2_confirm"] = True
    if step in ("AT6", "ATS3"):   # the equipment question is asked again from the start
        data.pop("equip", None)
        data.pop("equipment", None)
    return step, prefix + _entry(step, data)


# ── parsers ───────────────────────────────────────────────────────────────────

_SAV_RE = re.compile(r"([^\s,;:'\"`()]+\.sav)\b", re.I)
_FILE_RE = re.compile(r"([^\s,;:'\"`()]+\.[A-Za-z0-9]{2,5})(?![\w.])")
_CASE_KW_RE = re.compile(r"\bcaso\s*(?:n(?:[ºo°.]|umero|úmero)?\s*)?(?<![.,\d])(\d{1,5})(?![.,]?\d)", re.I)
_INT_RE = re.compile(r"(?<![.,\d\w])(\d{1,5})(?![.,]?\d)")
# CDU number: 1–6 digits, never part of a decimal ("0.1042" is not CDU 1042)
_CDU_RE = re.compile(r"(?<![.,\d])(\d{1,6})(?![.,]?\d)")
_BUSES_RE = re.compile(
    r"\bbarras?(?:\s+(?:de\s+)?gera\w*|\s+geradoras?)?\s*[:=]?\s*"
    r"((?:\d{1,5}\s*(?:,|;|\be\b|\s)\s*)*\d{1,5})", re.I)

_YES = ("sim", "s", "ok", "confirmar", "confirmo", "confirma", "manter", "mantenha", "pode",
        "isso", "correto", "certo")
_DONE = ("configurado", "configurei", "pronto", "feito", "ok", "sim", "concluido", "terminei",
         "incluidos", "incluido", "confirmar", "confirmado")
_FILLERS = ("quero", "vamos", "pode", "por", "favor", "ok", "entao", "agora", "vou", "eu")
END_TOKENS = ("encerrar", "encerra", "encerre", "finalizar", "finaliza", "finalize",
              "terminar", "termina", "fim", "sair")
_END_TAIL = {"a", "o", "simulacao", "estudo", "sessao", "anatem", "agora", "por", "favor",
             "aqui", "tudo", "isso"}
_RESTART_WORDS = ("nova simulacao", "comecar de novo", "reiniciar", "recomecar")


def parse_sav(text):
    m = _SAV_RE.search(text or "")
    return m.group(1) if m else None


def parse_case(text, sav=None):
    t = text or ""
    if sav:
        t = t.replace(sav, " ")
    m = _CASE_KW_RE.search(t)
    if m:
        return str(int(m.group(1)))
    nums = _INT_RE.findall(t)
    return str(int(nums[0])) if len(nums) == 1 else None


def parse_cdu(text):
    m = _CDU_RE.search(text or "")
    return str(int(m.group(1))) if m and int(m.group(1)) > 0 else None


def parse_filename(text):
    t = (text or "").strip()
    m = _FILE_RE.search(t)
    if m:
        return m.group(1)
    if t and " " not in t and 2 <= len(t) <= 80:
        return t
    return None


def parse_base(text, data=None):
    n = norm(text)
    ons = n == "1" or _has(n, "ons", "par", "pel")
    epe = n == "2" or _has(n, "epe", "pde")
    small = n == "3" or _has(n, "pequeno", "propria", "rede propria", "rede")
    if sum((ons, epe, small)) == 1:
        return "ONS" if ons else "EPE" if epe else "PEQUENO"
    sug = (data or {}).get("base_suggested")
    if sug and not (ons or epe or small) and _has(n, *_YES):
        return sug
    return None


def _is_yes(n):
    return _has(n, *_YES)


def _is_done(n):
    return _has(n, *_DONE)


def parse_ran(text):
    """'ok' | 'error' | None for 'did it run without errors?'"""
    n = norm(text)
    if _has(n, "sem erro", "sem erros", "sem problema", "sem problemas", "nao deu erro",
            "nenhum erro", "nao teve erro"):
        return "ok"
    if _has(n, "erro", "erros", "falhou", "falha", "violacao", "nao rodou", "nao", "cdu", "cdus"):
        return "error"
    if _has(n, "rodou", "ok", "sim", "sucesso", "funcionou", "pronto", "certo"):
        return "ok"
    return None


def parse_where(text):
    n = norm(text)
    if _has(n, "nao esta", "nao", "eolica", "eolicas", "fv", "fotovoltaica", "solar", "elo",
            "cc", "hvdc", "outro", "outros"):
        return "outro"
    if _has(n, "dmaq", "sincrona", "esta", "sim", "maquina"):
        return "dmaq"
    return None


def parse_ctrl(text):
    n = norm(text)
    gov = _has(n, "gov", "velocidade", "regulador de velocidade", "potencia ativa")
    avr = _has(n, "avr", "pss", "tensao", "regulador de tensao", "reativo")
    if gov and not avr:
        return "gov"
    if avr and not gov:
        return "avr"
    return None


def parse_flat(text):
    n = norm(text)
    if _has(n, "erro", "erros", "falhou"):
        return "error"
    if _has(n, "variando", "varia", "variou", "oscilando", "oscila", "oscilacao", "mudando"):
        return "varying"
    if _has(n, "flat", "constante", "constantes", "reta", "plana", "estavel", "estaveis"):
        return "flat"
    return None


def parse_osc(text):
    t = (text or "").lower()
    n = norm(text)
    if _has(n, "maior", "grande", "acima", "mais que"):
        return "large"
    if ("≤" in t or "<=" in t or re.search(r"0[.,]001", t)
            or _has(n, "menor", "pequena", "pequeno", "triangular", "triangulares", "escadinha",
                    "numerica", "numerico", "integrador")):
        return "small"
    return None


def parse_buses(text):
    m = _BUSES_RE.search(text or "")
    if not m:
        return None, text
    buses = [str(int(b)) for b in re.findall(r"\d{1,5}", m.group(1))]
    return buses, (text[:m.start()] + " " + text[m.end():])


def parse_has_files(text):
    """ATS2 pre-question: 'yes' | 'no' | None."""
    n = norm(text)
    if _has(n, "nao", "exemplo", "nenhum", "falta", "faltam"):
        return "no"
    if _has(n, "sim", "s", "tenho", "ja tenho", "possuo", "ok"):
        return "yes"
    return None


def is_files_continue(text) -> bool:
    """After the example-case guidance: the user now has the .SAV and the .STB."""
    n = norm(text)
    return not _has(n, "nao") and _has(n, "continuar", "continua", "ja tenho", "tenho", "sim",
                                       "pronto", "consegui", "ok")


def parse_equipment_choice(text, data=None):
    """AT6/ATS3 (and the ✏️ edit): 'none' | 'include' | None. With a BESS/STATCOM bus
    carried from the ANAREDE study, 'sim'/'manter' keeps the default ('include')."""
    n = norm(text)
    conv = _has(n, "convencional", "nenhum", "sem equipamento", "sem equipamentos", "puramente",
                "eletromecanico", "nao")
    inc = _has(n, "incluir", "inclua", "bess", "statcom", "hvdc", "vsc", "acoplar", "novos equipamentos")
    if conv != inc:
        return "none" if conv else "include"
    if not conv and handoff_has_equipment_bus(data) and _is_yes(n):
        return "include"
    return None


def parse_event_type(text):
    """Event menu: a label of EVENT_TYPES by number (1–4), button text or name; None if unknown.
    Overlapping words ('curto no fim da linha') resolve in menu order."""
    n = norm(text)
    m = re.fullmatch(r"(?:opcao |evento )?([1-4])", n)
    if m:
        return EVENT_LABELS[int(m.group(1)) - 1]
    for label, _, _, _, words in EVENT_TYPES:
        if n == norm(label) or _has(n, *words):
            return label
    return None


_EVENT_DONE = {"evento inserido", "inserido", "inseri", "inseri o evento", "pronto", "feito", "ok",
               "sim", "confirmar", "confirmado", "concluido"}


def is_end(text) -> bool:
    """'encerrar', 'quero encerrar', 'pode finalizar o estudo' — never an event or file
    name that merely contains the word ('curto no fim da linha', 'fim.sav')."""
    toks = norm(text).split()
    while toks and toks[0] in _FILLERS:
        toks = toks[1:]
    return (bool(toks) and toks[0] in END_TOKENS
            and all(t in _END_TAIL for t in toks[1:]))


def is_help(text) -> bool:
    return norm(text) in ("ajuda", "help", "nao sei", "preciso de ajuda", "socorro")


def is_back(text) -> bool:
    return norm(text) in ("voltar", "volta", "anterior", "back", "voltar um passo")


def is_restart(text) -> bool:
    n = norm(text)
    return any(re.search(rf"\b{w}\b", n) for w in _RESTART_WORDS)


# ── summary (sidebar panel + closing message) ─────────────────────────────────

_EQUIP_LABELS = {"incluidos": "modelos incluídos", "ja_no_stb": "já no .stb", "nenhum": "nenhum"}
EQUIPMENT_NONE_TEXT = "nenhum (estudo convencional)"


def equipment_text(data):
    if data.get("equipment") == "none":
        return EQUIPMENT_NONE_TEXT
    h = data.get("handoff") or {}
    parts = []
    if h.get("equipment_type"):
        parts.append(h["equipment_type"] + (f" (barra {h['equipment_bus']})" if h.get("equipment_bus") else ""))
    if data.get("equip") in _EQUIP_LABELS:
        parts.append(_EQUIP_LABELS[data["equip"]])
    elif data.get("equipment") == "include":
        parts.append("BESS/STATCOM/HVDC a incluir")
    return " · ".join(parts) or None


# ── ✏️ edit of the equipment choice (v6.6.1, P2) ──────────────────────────────

EQUIPMENT_EDIT_QUESTION = _EQUIP_BRANCH_Q


def equipment_editable(step, data) -> bool:
    """✏️ on 'Equipamentos' once the choice was made; not at AT6/ATS3 themselves,
    where the question (with its buttons) is already on screen."""
    return (data or {}).get("equipment") in ("none", "include") and step not in ("AT6", "ATS3")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def apply_equipment_edit(data, text):
    """Answer to the ✏️ equipment question: the confirmation, or None (not understood)."""
    choice = parse_equipment_choice(text, data)
    if choice is None:
        return None
    data["equipment"] = choice
    data.pop("equip", None)
    msg = f"Equipamentos alterado(a) para **{equipment_text(data)}**."
    if choice == "include":
        how = ("Inclua os blocos dos modelos diretamente no **.stb**, usando **DFNT** ou outros "
               "códigos." if data.get("base") == "PEQUENO" else
               "Inclua no **.stb** as chamadas aos arquivos dos modelos (**DCDU**, **DARQ** ou "
               "outros), associados às barras dos equipamentos.")
        msg += " " + how
    return msg


def study_params(data):
    """[(label, value)] for the 'Estudo atual' panel (read-only)."""
    data = data or {}
    out = []
    if data.get("base"):
        out.append(("Base", BASE_SHORT[data["base"]]))
    if data.get("sav_name"):
        out.append(("Arquivo .sav", data["sav_name"]))
    if data.get("case_number"):
        out.append(("Caso", data["case_number"]))
    if data.get("dmaq_name"):
        out.append(("DMAQ", data["dmaq_name"]))
    if data.get("gen_buses"):
        out.append(("Barras de geração", ", ".join(data["gen_buses"])))
    if data.get("small_case_no_files"):   # v6.6.1 (P1): chose "Não tenho" at ATS2
        out.append(("Arquivos .SAV/.STB", "sem arquivos próprios (orientação do caso de exemplo)"))
    eq = equipment_text(data)
    if eq:
        out.append(("Equipamentos", eq))
    if data.get("events"):
        out.append(("Eventos", len(data["events"])))
    return out


def closing_summary(data) -> str:
    rows = [("Base", BASE_LABELS.get(data.get("base"), "—")),
            ("Arquivo .sav", data.get("sav_name") or "—"),
            ("Caso", data.get("case_number") or "—")]
    if data.get("base") != "PEQUENO":
        rows.append(("DMAQ", data.get("dmaq_name") or "—"))
    else:
        rows.append(("Barras de geração", ", ".join(data.get("gen_buses") or []) or "—"))
    rows.append(("Equipamentos", equipment_text(data) or "—"))
    events = data.get("events") or []
    body = "\n".join(f"- {k}: **{v}**" for k, v in rows)
    body += "\n- Eventos: " + ("nenhum informado" if not events else "")
    body += "".join(f"\n  - {event_text(e)}" for e in events)
    return (
        "✅ **Simulação registrada.**\n\n**Resumo do estudo:**\n" + body + "\n\n"
        "Para uma nova simulação, use os botões **⚡ Iniciar simulação ANAREDE** ou "
        "**🌀 Iniciar simulação ANATEM** na barra lateral, ou me diga o que quer simular. "
        "Também pode fazer perguntas livres sobre o SIN."
    )


ENDED_TEXT = ("Sessão de simulação encerrada. Os resultados ficam registrados no histórico acima.\n\n"
              "Se precisar retomar ou tiver dúvidas sobre o SIN, é só perguntar.")


# ── state machine ─────────────────────────────────────────────────────────────

_BACK = {"AT2": "AT1", "AT3": "AT2", "AT4": "AT3", "AT5": "AT4", "AT6": "AT5", "AT7": "AT6",
         "AT8": "AT7", "AT10": "AT8", "AT11": "AT10",
         "ATS2": "AT1", "ATS3": "ATS2", "ATS4": "ATS3", "ATS5": "ATS4"}


def _retry(step, data, head):
    return step, f"{head}\n\n{question(step, data)}"


def _cdu_finish(data, advice, passo_d=True):
    """End of the CDU troubleshooting: advice (+ Passo D), then back to the run step."""
    ret = data.pop("cdu_return", None) or "AT8"
    if passo_d:
        advice += "\n\n" + (_PASSO_D_SMALL if ret == "ATS4" else _PASSO_D_SIN)
    return _enter(ret, data, advice + "\n\n---\n\n")


def _to_cdu(data, ret, prefix=""):
    data["cdu_return"] = ret
    return _enter("AT9", data, prefix)


def _flat_step(step, data, text):
    """AT10 (main) and ATS4 (small case): flat / varying (≤ 0.001 pu rule) / error."""
    nxt, ret = ("AT11", "AT8") if step == "AT10" else ("ATS5", "ATS4")
    if data.get("osc_pending"):
        osc = parse_osc(text)
        if osc == "small":
            return _enter(nxt, data, _OSC_SMALL + "\n\n---\n\n")
        if osc == "large":
            return _to_cdu(data, ret, _OSC_LARGE + "\n\n---\n\n")
        return _retry(step, data, "Não identifiquei o tamanho da oscilação.")
    r = parse_flat(text)
    if r == "flat":
        return _enter(nxt, data, "Variáveis constantes: o caso está **inicializado corretamente**.\n\n---\n\n")
    if r == "varying":
        data["osc_pending"] = True
        return step, _OSC_QUESTION
    if r == "error":
        return _to_cdu(data, ret)
    return _retry(step, data, "Não identifiquei o resultado.")


def _events_step(step, data, text):
    """AT11 / ATS5 (v6.6.1): menu → reminder → 'Evento inserido' or a description.
    Each event is stored as {"type": label, "note": free text or ""}."""
    n = norm(text)
    if is_end(text):
        data.pop("event_pending", None)
        data.pop("event_menu", None)
        return "IDLE", closing_summary(data)
    pending = data.get("event_pending")
    if pending:
        note = "" if n in _EVENT_DONE else re.sub(r"\s+", " ", text or "").strip()[:300]
        if n not in _EVENT_DONE and len(note) < 3:
            return _retry(step, data, "Não identifiquei a resposta.")
        events = data.setdefault("events", [])
        events.append({"type": pending, "note": note})
        data.pop("event_pending", None)
        data.pop("event_menu", None)
        return step, (f"Evento {len(events)} registrado: **{event_text(events[-1])}**.\n\n"
                      "Deseja adicionar outro evento ou encerrar?")
    if n in ("adicionar outro evento", "adicionar", "outro evento", "adicionar evento",
             "mais um evento", "outro"):
        data["event_menu"] = True
        return step, question(step, data)
    label = parse_event_type(text)
    if label is None:
        return _retry(step, data, "Não identifiquei o tipo de evento. Escolha uma opção de 1 a 4 "
                                  "(pelo botão, pelo número ou pelo nome).")
    data["event_pending"] = label
    return step, _event_reminder(label)


def handle(step, data, text):
    """(new_step, reply) for a message at an ANATEM step. 'IDLE' = simulation ended."""
    text = text or ""
    n = norm(text)

    if step not in EVENT_STEPS and is_end(text):
        return "IDLE", ENDED_TEXT
    if is_help(text):
        details = _STEP_DETAILS.get(step)
        return step, (f"**Ajuda — {STEP_LABELS.get(step, step)}**\n\n{question(step, data)}"
                      + (f"\n\n{details}" if details else ""))
    if is_back(text):
        if step == "AT1":
            return step, "Este já é o primeiro passo.\n\n" + question(step, data)
        prev = data.pop("cdu_return", "AT8") if step == "AT9" else _BACK[step]
        return _enter(prev, data, "Voltando um passo.\n\n")

    if step == "AT1":
        base = parse_base(text, data)
        if base is None:
            return _retry("AT1", data, "Não identifiquei a escolha.")
        data["base"] = base
        data.pop("base_suggested", None)
        prefix = f"Base: **{BASE_LABELS[base]}**.\n\n"
        return _enter("ATS2" if base == "PEQUENO" else "AT2", data, prefix)

    if step == "AT2":
        if data.get("at2_confirm") and _is_yes(n) and not parse_sav(text):
            return _enter("AT3", data, f"Arquivo **{data['sav_name']}**, caso **{data['case_number']}**.\n\n")
        sav = parse_sav(text)
        case = parse_case(text, sav)
        if not sav and not case:
            return _retry("AT2", data, "Não identifiquei o arquivo .sav nem o número do caso.")
        data.pop("at2_confirm", None)
        if sav:
            data["sav_name"] = sav
        if case:
            data["case_number"] = case
        if data.get("sav_name") and data.get("case_number"):
            return _enter("AT3", data, f"Arquivo **{data['sav_name']}**, caso **{data['case_number']}** registrados.\n\n")
        return "AT2", question("AT2", data)

    if step == "AT3":
        r = parse_ran(text)
        if r == "ok":
            data.pop("anat0_error", None)
            return _enter("AT4", data, "ANAT0 concluído.\n\n")
        if r == "error":
            data["anat0_error"] = True
            return "AT3", _AT3_ERROR
        return _retry("AT3", data, f"Responda **{T_RAN_OK}** ou **{T_RAN_ERR}**.")

    if step == "AT4":
        name = parse_filename(text)
        if not name:
            return _retry("AT4", data, "Não identifiquei o nome do arquivo.")
        data["dmaq_name"] = name
        return _enter("AT5", data, f"Arquivo DMAQ: **{name}**.\n\n")

    if step == "AT5":
        if _is_done(n):
            return _enter("AT6", data, "Arquivo .stb configurado.\n\n")
        return _retry("AT5", data, f"Quando terminar os três ajustes, responda **{T_CONFIGURED}**.")

    if step == "AT6":
        if data.get("equip") == "pendente":
            if _is_done(n):
                data["equip"] = "incluidos"
                return _enter("AT7", data, "Modelos incluídos no .stb.\n\n")
            return _retry("AT6", data, f"Quando terminar, responda **{T_MODELS_DONE}**.")
        if data.get("equipment") != "include" and not _has(n, "ja incluidos", "ja estao"):
            choice = parse_equipment_choice(text, data)
            if choice is None:
                return _retry("AT6", data, f"Responda **{T_CONVENTIONAL}** ou **{T_INCLUDE_EQUIP_LABEL}**.")
            data["equipment"] = choice
            if choice == "none":
                return _enter("AT7", data, f"Equipamentos: **{EQUIPMENT_NONE_TEXT}**.\n\n")
            return "AT6", _at6_main(data)
        data["equipment"] = "include"   # 'já incluídos' typed at the first question
        if _has(n, "ja", "ja incluidos", "ja estao"):
            data["equip"] = "ja_no_stb"
            return _enter("AT7", data, "Modelos já incluídos no .stb.\n\n")
        if _has(n, "nao", "nenhum", "sem"):
            data["equip"] = "nenhum"
            return _enter("AT7", data, "Sem modelos de equipamentos.\n\n")
        if _has(n, "sim", "incluir", "quero", "s"):
            data["equip"] = "pendente"
            return "AT6", _at6_include(data)
        return _retry("AT6", data, f"Responda **{T_YES}** ou **{T_ALREADY}**.")

    if step == "AT7":
        if _is_done(n):
            return _enter("AT8", data, "Simulação de verificação preparada.\n\n")
        return _retry("AT7", data, f"Quando terminar, responda **{T_READY}**.")

    if step == "AT8":
        r = parse_ran(text)
        if r == "ok":
            return _enter("AT10", data, "Execução sem erros.\n\n")
        if r == "error":
            return _to_cdu(data, "AT8")
        return _retry("AT8", data, f"Responda **{T_RAN_OK}** ou **{T_RUN_CDU_ERR}**.")

    if step == "AT9":
        cdu = data.setdefault("cdu", {})
        if not cdu.get("number"):
            num = parse_cdu(text)
            if not num:
                return _retry("AT9", data, "Não identifiquei o número do CDU.")
            cdu["number"] = num
            return "AT9", _at9_where(num)
        if not cdu.get("where"):
            w = parse_where(text)
            if w is None:
                return _retry("AT9", data, "Não identifiquei a resposta.")
            cdu["where"] = w
            if w == "dmaq":
                return "AT9", _at9_branch_a(data, cdu["number"])
            return _cdu_finish(data, _at9_branch_b(cdu["number"]), passo_d=False)
        ctrl = parse_ctrl(text)
        if ctrl is None:
            return _retry("AT9", data, f"Responda **{T_GOV}** ou **{T_AVR}**.")
        cdu["ctrl"] = ctrl
        return _cdu_finish(data, _GOV_ADVICE if ctrl == "gov" else _AVR_ADVICE)

    if step in ("AT10", "ATS4"):
        return _flat_step(step, data, text)

    if step in EVENT_STEPS:
        return _events_step(step, data, text)

    if step == "ATS2":
        if data.get("ats2_files") == "guide":
            if is_files_continue(text):
                data["ats2_files"] = "yes"
                return "ATS2", question("ATS2", data)
            return _retry("ATS2", data, f"Quando tiver os dois arquivos, clique em **{T_FILES_CONTINUE}**.")
        if ats2_files_question(data) and not parse_sav(text):
            has = parse_has_files(text)
            if has == "no":
                data["ats2_files"] = "guide"
                data["small_case_no_files"] = True
                return "ATS2", ATS2_EXAMPLE_GUIDE
            if has == "yes":
                data["ats2_files"] = "yes"
                return "ATS2", question("ATS2", data)
            return _retry("ATS2", data, f"Responda **{T_HAS_FILES}** ou **{T_NO_FILES}**.")
        data["ats2_files"] = "yes"   # the .sav typed straight away also answers 'yes'
        sav = parse_sav(text)
        rest = text.replace(sav, " ") if sav else text
        buses, rest = parse_buses(rest)
        m = _CASE_KW_RE.search(rest)
        case = str(int(m.group(1))) if m else None
        if m:
            rest = rest[:m.start()] + " " + rest[m.end():]
        nums = [str(int(x)) for x in _INT_RE.findall(rest)]
        if not case and not data.get("case_number") and len(nums) == 1 and not buses:
            case, nums = nums[0], []
        if not buses and nums and (case or data.get("case_number")):
            buses = nums
        if not (sav or case or buses):
            return _retry("ATS2", data, "Não identifiquei os dados.")
        if sav:
            data["sav_name"] = sav
        if case:
            data["case_number"] = case
        if buses:
            data["gen_buses"] = buses
        if data.get("sav_name") and data.get("case_number") and data.get("gen_buses"):
            return _enter("ATS3", data, _ats2_done(data) + "\n\n---\n\n")
        return "ATS2", question("ATS2", data)

    if step == "ATS3":
        if data.get("equipment") != "include":
            choice = parse_equipment_choice(text, data)
            if choice is None:
                return _retry("ATS3", data, f"Responda **{T_CONVENTIONAL}** ou **{T_INCLUDE_EQUIP_LABEL}**.")
            data["equipment"] = choice
            if choice == "none":
                return _enter("ATS4", data, f"Equipamentos: **{EQUIPMENT_NONE_TEXT}**.\n\n")
            return "ATS3", _ats3_main(data)
        if _has(n, "sem", "nao", "nenhum"):
            data["equip"] = "nenhum"
            return _enter("ATS4", data, "Sem modelos de equipamentos.\n\n")
        if _is_done(n) or _has(n, "confirmo", "inclusao"):
            data["equip"] = "incluidos"
            return _enter("ATS4", data, "Modelos incluídos no .stb.\n\n")
        return _retry("ATS3", data, f"Quando terminar, clique em **{T_CONFIRM_MODELS}**.")

    return step, question(step, data)
