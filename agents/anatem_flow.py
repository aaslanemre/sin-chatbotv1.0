"""
ANATEM guided flow (v6.6.0) — GUIDE ONLY.

Pure module: no Streamlit and no DB imports. A deterministic state machine
(regex + buttons/forms, the LLM never runs here) that tells the user what to do
in ANAREDE/ANATEM at each step of a dynamic (electromechanical stability) study.
It generates NO ANATEM text: no DEVT, STB, DMAQ, DFNT, TITU, DSIM/EXSI lines.

Main flow (SIN base, ONS or EPE):
  AT1 → AT2 → AT3 (ANAT0) → AT4 → AT5 → AT6 → AT7 → AT8 → (AT9 ⇄ AT8) → AT10 → AT11 → AT12 → end
  (v6.6.2: AT10 "Oscilação maior" → AT10B → AT8 or AT9)
Small case / own network (option 3 at AT1, no ANAT0):
  AT1 → ATS2 → ATS3 → ATS4 (→ AT9 → ATS4; → AT10B → ATS4 or AT9) → ATS5 → AT12 → end
  (v6.6.3: AT12 only when at least one event was registered; otherwise ATS5/AT11 → end)

v6.6.1 (revised Word guide + expert feedback P1–P5): ATS2 first asks whether the
user has a .SAV and a .STB (example-case guidance when not); AT6/ATS3 first ask
"conventional study or new equipment?"; AT5 uses the DARQ-only wording; AT8/ATS4
name the menu and F5; AT11/ATS5 offer a menu of event types (names only).

v6.6.2 (Thomas's feedback, 11–12 Nov): a pasted ANAT0 error is read at AT3; a typed
question about the DMAQ path at AT5 and "CDU … não está no DMAQ" at AT9 are answered
deterministically (intercept, before the app routes '?' questions to the LLM);
unmatched typed text of 4+ words at a button step goes to the free chat (reply None);
AT5/ATS2 explain DARQ by columns; AT9 Passo C has GOV/AVR/PSS; "Oscilação maior" goes
to the new step AT10B (controles atuando); events show the card names, the manual
link and a 5th option "Outro" answered by the free chat.

v6.6.3 (Thomas's answers + ONS Procedimentos de Rede, Submódulo 2.3): save path
"Histórico > Operações > Salvar"; the ANAT0 error is read by its description; a
short circuit (or a line loss with a single-phase fault) asks the operating voltage
and answers the indicative clearing times of Tabela 2 (config/ons_criteria.py);
"Encerrar" with at least one event goes to the new step AT12 (ONS criteria 2.4.3.7).

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

from agents.anatem_guard import MANUAL_URL as MANUAL_DEVT_URL, OTHER_EVENT_RULE
from agents.ux import with_details
from config.ons_criteria import (FAULT_TIME_CAVEAT, LINE_LOSS_TIP, NOT_IN_TABLE_TEXT, ONS_SOURCE,
                                  POST_DISTURBANCE_CRITERIA, SIMULATION_TIME_NOTE, TABLE_KV,
                                  TELEPROTECTION_KV, fault_clearing_times)

SIM_TYPE = "ANATEM"
PROGRAM_CHOICE_STEP = "IDLE_PROGRAM_CHOICE"

# v6.6.3: AT12 (ONS criteria) closes both paths.
MAIN_STEPS = ["AT1", "AT2", "AT3", "AT4", "AT5", "AT6", "AT7", "AT8", "AT9", "AT10", "AT11", "AT12"]
SMALL_STEPS = ["AT1", "ATS2", "ATS3", "ATS4", "ATS5", "AT12"]
# v6.6.2: AT10B (controles atuando) is a detour of AT10 and ATS4, reached only from
# "Oscilação maior"; it is outside the "Passo N de M" sequences.
ALL_STEPS = list(dict.fromkeys(MAIN_STEPS + SMALL_STEPS[1:] + ["AT10B"]))
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
    "AT10B": "ANATEM 10B: Controles atuando",
    "AT11": "ANATEM 11: Eventos (DEVT)",
    "AT12": "ANATEM 12: Critérios do ONS",
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
    "AT10B": "os controles atuando",
    "AT11": "os eventos (DEVT)",
    "AT12": "a verificação dos critérios do ONS",
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
T_AVR = "Regulador de tensão (AVR)"
T_PSS = "Estabilizador (PSS)"   # v6.6.2
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
# v6.6.2
T_CTRL_ADJUSTED, T_NO_CTRL = "Sim, ajustei e vou rodar de novo", "Não há controle atuando"
T_OTHER_EVENT = "Outro / descrever o que quero analisar"
# v6.6.3
T_KV_OTHER = "Outra"
T_TELEP_YES, T_TELEP_NO = "Com teleproteção", "Sem teleproteção"
T_NO_PRIOR_FAULT, T_SLG_FAULT = "Sem curto prévio", "Com curto monofásico"
T_CRIT_OK, T_CRIT_VIOLATED, T_CRIT_SKIP = "Todos atendidos", "Algum critério violado", "Pular verificação"
T_CRIT_DONE = "Concluir"


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
# v6.6.2 (3a): Thomas's procedure; ANAT0 runs inside the ANAREDE (no "volte ao ANAREDE").
_AT3_FIX_STEPS = (
    "1. Abra o **relatório de execução da Etapa 1** do ANAT0.\n"
    "2. Use **Localizar (Ctrl+F)** e busque a palavra **Erro**. Pode haver um ou mais erros.\n"
    "3. Analise cada erro e corrija alterando o **despacho das máquinas** ou ajustando melhor o caso.\n"
    "4. Rode o **fluxo de potência** novamente e confira se está **convergido**.\n"
    "5. Salve o **.SAV**.\n"
    "6. Execute o **ANAT0** novamente."
)
_AT3_RAN_Q = "**O ANAT0 rodou sem erros?**"
_AT3_ERROR = (
    "**Erro no ANAT0.** Como corrigir:\n" + _AT3_FIX_STEPS + "\n\n"
    "Se quiser, cole aqui o trecho do erro que eu te ajudo a interpretar.\n\n" + _AT3_RAN_Q
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# Kept in "Detalhes": why the ANAT0 fails (v6.6.0 explanation).
_AT3_ERROR_WHY = (
    "O ANAT0 indica **violação de limite de potência ativa ou reativa** ao dividir a geração da "
    "barra entre as máquinas: a barra, no ANAREDE, está num ponto de operação incompatível com a "
    "capacidade das máquinas cadastradas."
)


def at3_error_message() -> str:
    """'Deu erro' at AT3: Thomas's procedure + why the ANAT0 fails in Detalhes."""
    return with_details(_AT3_ERROR, _AT3_ERROR_WHY)


# ── 2a: an ANAT0 error pasted at AT3 ──────────────────────────────────────────
# v6.6.3 (Thomas: "error codes are not so important, the description is; usually related
# to active power or number of units on"): the error is read by its DESCRIPTION. The code
# (ANAT01-NNN), when present, is only a label.

_ANAT0_ERR_LINE_RE = re.compile(r"\*{3}\s*ERRO\b", re.I)
_ANAT0_CODE_RE = re.compile(r"\bANAT01-(\d+)", re.I)
_ANAT0_CUE_RE = re.compile(r"\b(?:potencia gerada|unidades|limite)\b")
_ANAT0_MW_RE = re.compile(r"\(\s*(\d+(?:[.,]\d+)?)\s*MW\s*\)", re.I)
_ANAT0_BARRA_RE = re.compile(r"\bbarra\s*(?:n(?:[ºo°.]|umero|úmero)?\s*)?(\d{1,5})(?![.,]?\d)", re.I)
MAX_ANAT0_ERRORS = 5


def _strip_accents(text) -> str:
    t = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in t if not unicodedata.combining(c))


def is_anat0_error_text(text) -> bool:
    """A '*** ERRO' line, or a cue ('potência gerada', 'unidades', 'limite') with a number."""
    if _ANAT0_ERR_LINE_RE.search(text or ""):
        return True
    return bool(_ANAT0_CUE_RE.search(norm(text)) and re.search(r"\d", text or ""))


def _anat0_blocks(text):
    """One list of lines per error. In the ANAT0 report the '*** ERRO' line CLOSES its
    block (record and description above it); if the paste starts with it, it OPENS it."""
    lines = [ln.strip() for ln in str(text or "").splitlines()]
    marks = [i for i, ln in enumerate(lines) if _ANAT0_ERR_LINE_RE.search(ln)]
    if not marks:
        return [lines]
    if not any(lines[:marks[0]]):
        bounds = marks + [len(lines)]
        return [lines[a:b] for a, b in zip(bounds, bounds[1:])]
    bounds = [-1] + marks
    blocks = [lines[a + 1:b + 1] for a, b in zip(bounds, bounds[1:])]
    tail = lines[marks[-1] + 1:]
    if _ANAT0_CUE_RE.search(norm(" ".join(tail))):   # a last error pasted without its ERRO line
        blocks.append(tail)
    return blocks


def _anat0_classify(desc):
    """('active' | 'reactive' | 'units' | None, 'down' | 'up' | None) from the description."""
    n = norm(desc)
    down = _has(n, "inferior", "abaixo", "minimo")
    up = _has(n, "superior", "acima", "maximo")
    direction = "down" if down and not up else "up" if up and not down else None
    if _has(n, "potencia") and _has(n, "mw", "ativa"):
        return "active", direction
    if _has(n, "mvar") or re.search(r"\breativ", n):
        return "reactive", direction
    if _has(n, "unidade", "unidades"):
        return "units", direction
    return None, direction


def _parse_anat0_block(lines) -> dict:
    err = {"code": None, "bus": None, "group": None, "name": None, "gen": None, "min": None,
           "max": None, "description": [], "kind": None, "direction": None}
    rec_i = None
    for i, ln in enumerate(lines):
        if not ln.startswith("(Nb"):
            continue
        rec_i = next((k for k in range(i + 1, len(lines)) if lines[k]), None)
        rec = lines[rec_i] if rec_i is not None else ""
        if not re.match(r"\d", rec):
            rec_i = None   # not a numeric record: it is part of the description
        toks = _strip_accents(rec).split()
        ints = []
        for tok in toks:
            if not re.fullmatch(r"\d+", tok):
                break
            ints.append(tok)
        name = next((tok for tok in toks[len(ints):] if re.fullmatch(r"\w+", tok)), None)
        if len(ints) >= 2 and name:
            err.update(bus=str(int(ints[0])), group=str(int(ints[1])), name=name)
        break
    block = "\n".join(lines)
    code = _ANAT0_CODE_RE.search(block)
    if code:
        err["code"] = f"ANAT01-{code.group(1)}"
    desc = [ln for i, ln in enumerate(lines)
            if ln and i != rec_i and not ln.startswith("(Nb") and not _ANAT0_ERR_LINE_RE.search(ln)]
    err["description"] = desc
    if not err["bus"]:
        m = _ANAT0_BARRA_RE.search(_strip_accents(" ".join(desc)))
        if m:
            err["bus"] = str(int(m.group(1)))
    err["kind"], err["direction"] = _anat0_classify(" ".join(desc))
    mw = _ANAT0_MW_RE.findall(_strip_accents(" ".join(desc)))
    if err["kind"] == "active" and len(mw) >= 2:
        err["gen"] = mw[0]
        if err["direction"] == "down":
            err["min"] = mw[1]
        elif err["direction"] == "up":
            err["max"] = mw[1]
    return err


def parse_anat0_errors(text) -> list:
    """Every error in a message typed/pasted at AT3 (see is_anat0_error_text); [] when the
    message is not an ANAT0 error. Blocks with neither a description nor a code are dropped."""
    if not is_anat0_error_text(text):
        return []
    errs = [_parse_anat0_block(b) for b in _anat0_blocks(text)]
    return [e for e in errs if e["description"] or e["code"]]


def parse_anat0_error(text):
    """v6.6.2 API: the first error as {'code', 'bus', 'group', 'name', 'gen', 'min'}, or None."""
    errs = parse_anat0_errors(text)
    if not errs:
        return None
    return {k: errs[0][k] for k in ("code", "bus", "group", "name", "gen", "min")}


def _num(value) -> float:
    return float(str(value).replace(",", "."))


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_ANAT0_TAIL = ("Depois: rode o fluxo de potência, confira se convergiu, salve o .SAV "
               "(**Histórico > Operações > Salvar**) e execute o ANAT0 novamente.")
_ANAT0_UNKNOWN = "Não reconheci o tipo desse erro."


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _anat0_advice(err) -> str:
    """Deterministic advice from the classified description (2d)."""
    bus = err.get("bus")
    bus_ref = bus or "indicada no erro"
    kind, x = err.get("kind"), err.get("gen")
    if kind == "active":
        y = err.get("min")
        if y and _num(y) > _num(x):
            return (f"A potência gerada (**{x} MW**) está abaixo do mínimo das máquinas (**{y} MW**). "
                    f"No ANAREDE, aumente a geração ativa da barra {bus_ref} para pelo menos **{y} MW** "
                    "(ou ajuste o despacho das máquinas).")
        y = err.get("max")
        if y and _num(y) < _num(x):
            return (f"A potência gerada (**{x} MW**) está acima do máximo das máquinas (**{y} MW**). "
                    f"No ANAREDE, reduza a geração ativa da barra {bus_ref} para no máximo **{y} MW** "
                    "(ou ajuste o despacho das máquinas).")
        return (f"O erro é de **potência ativa**. No ANAREDE, ajuste a geração ativa da barra {bus_ref} "
                "para ficar dentro dos limites das máquinas.")
    if kind == "reactive":
        return (f"O erro é de **potência reativa**. No ANAREDE, alivie a geração/absorção de reativo da "
                f"barra {bus_ref} (ajustando a tensão controlada, taps ou compensação próxima).")
    if kind == "units":
        # PENDING REVIEW: exact advice for unit-count errors.
        where = f" na barra {bus}" if bus else ""
        return (f"O erro está relacionado ao **número de unidades** em operação da usina{where}. O ANAT0 "
                "ajusta o número de unidades ao despacho do caso, com base nos limites e na quantidade de "
                "máquinas cadastradas no BNT1.DAT. Revise o despacho dessa usina no ANAREDE para que seja "
                "compatível com as unidades disponíveis.")
    return _ANAT0_UNKNOWN


def _anat0_item(err) -> str:
    label = f"Erro **{err['code']}**" if err.get("code") else "Erro do ANAT0"
    if err.get("bus"):
        label += f" na barra **{err['bus']}" + (f" ({err['name']})" if err.get("name") else "") + "**"
    desc = err.get("description") or []
    quoted = ("Descrição lida:\n" + "\n".join(f"> {ln}" for ln in desc) if desc
              else "Não encontrei a descrição do erro no trecho colado.")
    return f"{label}.\n\n{quoted}\n\n{_anat0_advice(err)}"


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def anat0_error_reply(errs) -> str:
    """One or several parsed errors (2e: max MAX_ANAT0_ERRORS listed) → advice per error,
    the short tail and the AT3 question. An unrecognised error adds the 6-step procedure."""
    if isinstance(errs, dict):
        errs = [errs]
    shown = errs[:MAX_ANAT0_ERRORS]
    if len(shown) == 1:
        body = _anat0_item(shown[0])
    else:
        head = f"**Encontrei {len(errs)} erros no trecho colado"
        head += f" (mostro os {MAX_ANAT0_ERRORS} primeiros)" if len(errs) > len(shown) else ""
        body = head + ":**\n\n" + "\n\n".join(f"**{i}.** {_anat0_item(e)}" for i, e in enumerate(shown, 1))
    if any(e.get("kind") is None for e in shown):
        body += f"\n\n**Como corrigir:**\n{_AT3_FIX_STEPS}"
    return f"{body}\n\n{_ANAT0_TAIL}\n\n{_AT3_RAN_Q}"


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
# v6.6.2 (3b): DARQ explained by columns (Thomas's text).
def _darq_sav_items(sav, case, anat0=True) -> str:
    processed = " e processado no ANAT0" if anat0 else ""
    return (
        "1. **Substituir o arquivo .SAV:** no cartão **DARQ**, identifique a linha cujo tipo de "
        "arquivo (primeira coluna) é **SAV**. A segunda coluna é o **número do caso** e a terceira "
        "é o **nome do arquivo com o caminho**. Altere a **terceira coluna** para o seu arquivo "
        f".SAV{_known(sav)}.\n"
        "2. **Conferir o número do caso:** na mesma linha, altere a **segunda coluna** para o número "
        f"do caso convergido no ANAREDE{processed}{_known(case)}."
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _at5_main(data) -> str:
    return (
        "**Passo 5 — Edição do .stb.** Abra o arquivo **.stb** da base em um editor de texto "
        "e faça três ajustes:\n"
        + _darq_sav_items(data.get("sav_name"), data.get("case_number")) + "\n"
        "3. **Substituir o arquivo DMAQ:** no cartão **DARQ**, na linha cujo tipo de arquivo "
        "(primeira coluna) é **DAT** e que aponta para o DMAQ original da base, troque o caminho "
        f"pelo do novo arquivo gerado pelo ANAT0{_known(data.get('dmaq_name'))}, incluindo a pasta "
        "onde ele foi salvo.\n\n"
        f"Responda **{T_CONFIGURED}** quando terminar."
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.2 (2b). Source: Thomas's own example line (type DAT + path).
def at5_dmaq_answer(data) -> str:
    return (
        "No cartão **DARQ**, procure a linha cujo tipo de arquivo (primeira coluna) é **DAT** e que "
        "aponta para o arquivo DMAQ original da base (por exemplo, um arquivo DMAQ_xxx.dat dentro da "
        "pasta da base). Troque o caminho dessa linha pelo caminho do novo arquivo gerado pelo ANAT0"
        f"{_known(data.get('dmaq_name'))}, incluindo a pasta onde ele foi salvo (por exemplo, a pasta "
        "ANAT0).\n\n"
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
        "**Passo C** — O CDU é de qual controle? Regulador de velocidade (GOV), regulador de "
        "tensão (AVR) ou estabilizador (PSS)?"
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_GOV_ADVICE = (
    "**Regulador de velocidade (GOV)** → problema de **potência ativa**. No ANAREDE, reduza "
    "levemente o **Pg** da máquina (ou aumente, se estiver abaixo do mínimo técnico)."
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.2 (3c): AVR and PSS share the voltage/reactive advice (Thomas's guide groups them).
_VOLTAGE_ADVICE = (
    "problema de **tensão/reativo**. Melhore o perfil de tensão nessa barra (mais perto de "
    "**1,0 pu**) ou alivie a injeção/absorção de reativo da máquina usando taps ou compensadores "
    "próximos."
)
_AVR_ADVICE = "**Regulador de tensão (AVR)** → " + _VOLTAGE_ADVICE
# PENDING REVIEW: PSS-specific advice in v6.6.3
_PSS_ADVICE = "**Estabilizador (PSS)** → " + _VOLTAGE_ADVICE
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


# v6.6.2 (2c): "CDU 1042 … não encontrei esse CDU no arquivo DMAQ" typed at AT9.
_NOT_IN_DMAQ_RE = re.compile(
    r"\bnao (?:esta|estava|encontrei|encontro|achei|acho|aparece)\b(?: \w+){0,5}? dmaq\b"
    r"|\bfora do dmaq\b")
_IN_DMAQ_RE = re.compile(r"\besta (?:\w+ ){0,3}?dmaq\b|\bmaquina sincrona\b")
_CDU_NUM_RE = re.compile(r"\bcdu\s*(?:n(?:[ºo°.]|umero|úmero)?\s*)?(\d{1,6})(?![.,]?\d)", re.I)


def parse_cdu_where(text):
    """(cdu number or None, 'outro' | 'dmaq' | None) from one typed sentence."""
    n = norm(text)
    m = _CDU_NUM_RE.search(text or "")
    num = str(int(m.group(1))) if m and int(m.group(1)) > 0 else parse_cdu(text)
    if _NOT_IN_DMAQ_RE.search(n):
        return num, "outro"
    if _IN_DMAQ_RE.search(n) and not re.search(r"\bnao esta\b", n):
        return num, "dmaq"
    return num, None


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
# v6.6.2 (3d): "Oscilação maior" → AT10B, controls acting (Thomas's text).
_AT10B_MAIN = (
    "Oscilações maiores que 0,001 pu não são efeito numérico.\n"
    "1. Olhe o **log/relatório do ANATEM** e procure **avisos de controles atuando**.\n"
    "2. Alguns controles atuam conforme o ponto de operação ou o nível de tensão do caso, por "
    "exemplo o **chaveamento de bancos de reatores/capacitores dos elos HVDC** para controle de "
    "tensão. É comum que atuem mesmo em regime permanente e causem oscilações.\n"
    "3. Se for isso, vá ao equipamento cujo controle está atuando e coloque o sistema num ponto de "
    "operação que evite a atuação, normalmente **adiantando a manobra** que o controle faria (ex.: "
    "se o controle liga um reator no ANATEM, ligue esse reator no ANAREDE, salve o caso e rode o "
    "ANATEM de novo).\n\n"
    "Encontrou algum controle atuando?"
)


def parse_ctrl_acting(text):
    """AT10B: 'adjusted' | 'none' | None."""
    n = norm(text)
    if _has(n, "nao", "nenhum", "nenhuma", "sem controle"):
        return "none"
    if _has(n, "sim", "ajustei", "encontrei", "achei", "vou rodar", "rodar de novo"):
        return "adjusted"
    return None


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
OTHER_EVENT = "Outro"   # v6.6.2 (4b): stored as {"type": "Outro", "note": <user text>}
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
EVENT_CODES_NOTE = ("Os códigos acima são os nomes dos cartões do bloco DEVT; a sintaxe exata e as "
                    "colunas devem ser conferidas na documentação do ANATEM.")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _events_main(step) -> str:
    n = "11" if step == "AT11" else "5"
    items = "\n".join(f"{i}. **{label}** — {desc} (código{'s' if ',' in codes or ' e ' in codes else ''}: "
                      f"{codes})" for i, (label, desc, codes, _, _) in enumerate(EVENT_TYPES, 1))
    items += f"\n{len(EVENT_TYPES) + 1}. **{T_OTHER_EVENT}**"
    return (
        f"**Passo {n} — Simulação de eventos (DEVT).** Qual evento você quer simular?\n\n"
        f"{items}\n\n"
        "Escolha pelo botão, pelo número ou pelo nome, ou digite **encerrar**."
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
MANUAL_LINE = f"Sintaxe e campos de cada cartão: manual do ANATEM (CEPEL) — {MANUAL_DEVT_URL}"


def event_cards(label) -> list:
    codes = next(e[2] for e in EVENT_TYPES if e[0] == label)
    return [c.strip() for c in re.split(r",| e ", codes) if c.strip()]


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _event_head(label) -> str:
    needs = next(e[3] for e in EVENT_TYPES if e[0] == label)
    cards = event_cards(label)
    noun = "cartões" if len(cards) > 1 else "cartão"
    return (f"**{label}** — {noun} do DEVT: **{', '.join(cards)}**\n\n"
            f"Para esse evento, defina: {needs}.")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_EVENT_TAIL = (
    f"Insira o evento no bloco **DEVT** do .stb, rode o ANATEM ({RUN_SHORT}) e salve os "
    "resultados.\n\n"
    f"{MANUAL_LINE}\n\n"
    f"Clique em **{T_EVENT_DONE}** quando terminar, ou descreva o evento "
    "(ex: barra, instantes de início e fim)."
)


def _event_reminder(label) -> str:
    return _event_head(label) + "\n\n" + _EVENT_TAIL


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_OTHER_EVENT_ASK = (
    f"**{T_OTHER_EVENT}.** Descreva em poucas palavras o que você quer analisar no ANATEM (por "
    "exemplo, o comportamento de uma usina depois da perda de uma linha). Eu sugiro o tipo de "
    "evento e o nome do cartão do DEVT.\n\n" + MANUAL_LINE
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
OTHER_EVENT_TAIL = (
    f"\n\n---\nClique em **{T_EVENT_DONE}** quando inserir o evento, em **{T_ADD_EVENT}** "
    f"ou em **{T_END}**."
)
# ── v6.6.3: fault clearing times (ONS Submódulo 2.3, Tabela 2) ───────────────
# Numbers come ONLY from config/ons_criteria.py; a voltage outside the table gets none.
FAULT_EVENT = "Curto-circuito"
LINE_EVENT = "Perda de linha de transmissão"
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
KV_QUESTION = ("Qual a **tensão de operação** no ponto do curto-circuito? Escolha pelo botão ou digite o "
               "valor (ex: `500` ou `500 kV`).")
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
TELEP_QUESTION = (f"Em **138 kV** a Tabela 2 tem dois valores. A proteção tem **teleproteção**? "
                  f"Responda **{T_TELEP_YES}** ou **{T_TELEP_NO}**.")
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel) — item 2.4.1.2
LINE_FAULT_QUESTION = (f"{LINE_LOSS_TIP}\n\nComo você vai simular a abertura? **{T_NO_PRIOR_FAULT}** ou "
                       f"**{T_SLG_FAULT}**?")
_KV_ANSWER_RE = re.compile(
    r"(?:(?:tensao|nivel)(?: de)?(?: operacao)?(?: de| e| em)? )?(\d{2,4})(?: 0+)? ?(?:kv)?")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def fault_times_text(kv, teleprotection=None) -> str:
    """Tabela 2 answer for `kv`, or the not-in-table sentence (kv None = 'Outra')."""
    times = fault_clearing_times(kv, teleprotection) if kv else None
    if not times:
        return NOT_IN_TABLE_TEXT
    t1, t2 = times
    telep = "" if teleprotection is None else f" ({'com' if teleprotection else 'sem'} teleproteção)"
    return (f"Tempo de eliminação indicativo para **{kv} kV**{telep}: **{t1} ms** (sem falha do disjuntor) "
            f"ou **{t2} ms** (com falha do disjuntor). {FAULT_TIME_CAVEAT} Fonte: {ONS_SOURCE}, Tabela 2.")


def parse_kv_answer(text):
    """Answer to KV_QUESTION: a voltage (int), 'outra', or None. Only a bare voltage
    ('500', '500kV', 'tensão de 500 kV'); a sentence with a number is not an answer."""
    n = norm(text)
    if n in ("outra", "outro", "outra tensao", "outro valor", "nenhuma"):
        return "outra"
    m = _KV_ANSWER_RE.fullmatch(n)
    return int(m.group(1)) if m else None


def parse_teleprotection(text):
    n = norm(text)
    if _has(n, "sem", "nao"):
        return False
    if _has(n, "com", "sim", "tem"):
        return True
    return None


def parse_line_fault(text):
    """'slg' (with a single-phase fault) | 'none' (no prior fault) | None."""
    n = norm(text)
    if _has(n, "monofasico", "com curto", "com curto monofasico"):
        return "slg"
    if _has(n, "sem curto", "sem curto previo", "sem"):
        return "none"
    return None
_FAULT_TIME_RE = re.compile(
    r"\b(?:tempos?|instantes?|duracao|quanto tempo)\b(?: \w+){0,4}? "
    r"(?:eliminacao|abertura|defeito|falta|curto)\b")


def asks_fault_times(text) -> bool:
    """'qual o tempo de eliminação do defeito?', 'quanto tempo dura o curto?'"""
    n = norm(text)
    asks = is_question(text) or _has(n, "qual", "quais", "quanto", "quantos", "sugere", "sugira",
                                     "recomenda", "usar", "uso", "devo")
    return asks and bool(_FAULT_TIME_RE.search(n))


def _fault_label(event) -> str:
    """' · com curto monofásico · 500 kV · 100/250 ms' from the v6.6.3 keys ('' without them)."""
    parts = []
    if event.get("curto_previo") == "monofasico":
        parts.append("com curto monofásico")
    elif event.get("curto_previo") == "sem":
        parts.append("sem curto prévio")
    if event.get("kv"):
        parts.append(f"{event['kv']} kV")
    if event.get("teleprotecao") is not None:
        parts.append("com teleproteção" if event["teleprotecao"] else "sem teleproteção")
    if event.get("t_sem_falha_ms") is not None:
        parts.append(f"{event['t_sem_falha_ms']}/{event['t_com_falha_ms']} ms (Tabela 2)")
    elif event.get("kv_fora_tabela"):
        parts.append("tensão fora da Tabela 2")
    return "".join(f" · {p}" for p in parts)


def event_text(event) -> str:
    """One event as readable text: v6.6.1 dict {'type', 'note'} (v6.6.3: + fault keys)
    or a v6.6.0 string."""
    if isinstance(event, dict):
        note = event.get("note") or ""
        return (event.get("type") or "Evento") + _fault_label(event) + (f" — {note}" if note else "")
    return str(event)


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.1 (P1): first ask whether the user has a .SAV and a .STB.
_ATS2_FILES_Q = ("**Passo 2 — Caso pequeno.** Você já tem um arquivo .SAV e um .STB para o seu caso?")
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.3: save path confirmed by Thomas: "Histórico > Operações > Salvar".
# OPEN: the exact location of the example .STB is unconfirmed: no file name or path given.
ATS2_EXAMPLE_GUIDE = (
    "**Caso de exemplo.**\n"
    "- A pasta de instalação padrão do ANAREDE traz uma biblioteca de casos didáticos em formato "
    "**.PWF**, por exemplo o sistema-teste IEEE de 9 barras (**9BARRAS.PWF**), com o diagrama "
    "unifilar (**.LST**, ex: `9_barras.lst`) e um arquivo **.STB** desse caso.\n"
    "- No ANAREDE: abra o **9BARRAS.PWF**, rode o fluxo de potência (regime permanente) e salve "
    "o caso convergido como arquivo histórico **.SAV** em **Histórico > Operações > Salvar**.\n"
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
        + _darq_sav_items(data["sav_name"], data["case_number"], anat0=False) + "\n"
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

# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# v6.6.3 (Part 4): ONS — Procedimentos de Rede, Submódulo 2.3, item 2.4.3.7.
_AT12_CRITERIA = (
    "Depois do distúrbio, confira no PLOTCEPEL:\n"
    "1. Tensão mínima na **primeira oscilação**: não pode ser inferior a **70%** da tensão nominal "
    "(**74%** para 500 kV).\n"
    "2. Tensão mínima nas **demais oscilações**: não pode ser inferior a **80%** (**84%** para 500 kV).\n"
    "3. Variação entre a tensão **inicial e final** da simulação: menor que **10%** da tensão nominal "
    "(Vfinal ≥ Vinicial − 10% Vnom).\n"
    "4. Oscilação de tensão eficaz **pico a pico** de no máximo **2%**, após **10 s** da eliminação do "
    "distúrbio.\n"
    f"Fonte: {ONS_SOURCE}, item 2.4.3.7."
)
_AT12_SMALL_PREFIX = "Como referência (critérios do SIN):"
_AT12_ASK = "Os critérios foram atendidos?"
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_AT12_WHICH = ("Qual critério foi violado? Clique em um ou mais (1 a 4) ou digite, por exemplo, `1 e 3`. "
               f"Se quiser, escreva uma observação. Depois clique em **{T_CRIT_DONE}**.")
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel) — no remedies: not in the source.
_AT12_RECORD = "Registre a violação no relatório do estudo."
ONS_CRITERIA_LABELS = {"atendidos": "atendidos", "violados": "violados", "nao_verificados": "não verificados"}


def _at12_main(data) -> str:
    if data.get("base") == "PEQUENO":
        return (f"{_AT12_SMALL_PREFIX}\n\n**Passo 6 — Verificação dos resultados (critérios do ONS).** "
                f"{_AT12_CRITERIA}\n\n{_AT12_ASK}")
    return (f"**Passo 12 — Verificação dos resultados (critérios do ONS).** {_AT12_CRITERIA}\n\n"
            f"{_AT12_ASK}")


def _at12_which(data) -> str:
    marked = data.get("ons_violated") or []
    head = f"Critérios marcados: **{', '.join(map(str, marked))}**.\n\n" if marked else ""
    return head + _AT12_WHICH


_STEP_DETAILS = {
    "AT1": _AT1_NOTE, "AT2": _AT2_NOTE, "AT3": _AT3_DETAILS, "AT4": _AT4_DETAILS,
    "AT5": STB_CODES, "AT7": _AT7_DETAILS, "AT9": CDU_NOTE, "ATS2": _ATS2_DETAILS,
    # v6.6.3 (3e): the usual simulation time, once, in the events "Detalhes"
    "AT11": EVENT_CODES_NOTE + "\n\n" + SIMULATION_TIME_NOTE,
    "ATS5": EVENT_CODES_NOTE + "\n\n" + SIMULATION_TIME_NOTE,
}


# ── step questions (resume, ajuda, LLM step context) ──────────────────────────

def question(step, data) -> str:
    """The question for the CURRENT step and sub-state (no 'Detalhes')."""
    data = data or {}
    if data.get("fault_stage"):   # v6.6.3: voltage / teleprotection / line-fault question
        return {"kv": KV_QUESTION, "telep": TELEP_QUESTION, "line": LINE_FAULT_QUESTION}[data["fault_stage"]]
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
    if step == "AT10B":
        return _AT10B_MAIN
    if step in EVENT_STEPS:
        if data.get("event_other"):
            return _OTHER_EVENT_ASK
        if data.get("event_pending") == OTHER_EVENT:
            return (f"**Evento: {event_text({'type': OTHER_EVENT, 'note': data.get('event_note')})}**."
                    + OTHER_EVENT_TAIL)
        if data.get("event_pending"):
            return _event_reminder(data["event_pending"])
        if data.get("events") and not data.get("event_menu"):
            return f"**{len(data['events'])} evento(s) registrado(s).** Deseja adicionar outro evento ou encerrar?"
        return _events_main(step)
    if step == "AT12":
        return _at12_which(data) if data.get("crit_stage") == "which" else _at12_main(data)
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
                  "event_pending", "event_menu", "event_other", "event_note", "event_llm",
                  "fault_stage", "fault", "fault_kv", "fault_free", "fault_resume",   # v6.6.3
                  "crit_stage", "ons_violated", "ons_note")


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
    """'gov' | 'avr' | 'pss' | None. 'AVR ou PSS' (v6.6.1 button) → 'avr' (same advice)."""
    n = norm(text)
    gov = _has(n, "gov", "velocidade", "regulador de velocidade", "potencia ativa")
    avr = _has(n, "avr", "tensao", "regulador de tensao", "reativo")
    pss = _has(n, "pss", "estabilizador")
    if gov and not (avr or pss):
        return "gov"
    if avr and not gov:
        return "avr"
    if pss and not gov:
        return "pss"
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
    """Event menu: a label of EVENT_TYPES by number (1–4), button text or name; OTHER_EVENT
    for 5 / the 'Outro / descrever…' button; None if unknown.
    Overlapping words ('curto no fim da linha') resolve in menu order."""
    n = norm(text)
    m = re.fullmatch(r"(?:opcao |evento )?([1-5])", n)
    if m:
        return (EVENT_LABELS + [OTHER_EVENT])[int(m.group(1)) - 1]
    if n == norm(T_OTHER_EVENT) or _has(n, "descrever", "outro tipo", "outro evento diferente"):
        return OTHER_EVENT
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
    crit = data.get("ons_criteria")
    if crit:   # v6.6.3 (4c): only when AT12 was reached
        value = ONS_CRITERIA_LABELS[crit]
        if crit == "violados":
            value += ": " + ", ".join(map(str, data.get("ons_violated") or []))
        body += f"\n- Critérios ONS (2.4.3.7): **{value}**"
        if crit == "violados" and data.get("ons_note"):
            body += f" — {data['ons_note']}"
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
         "AT8": "AT7", "AT10": "AT8", "AT10B": "AT10", "AT11": "AT10",
         "ATS2": "AT1", "ATS3": "ATS2", "ATS4": "ATS3", "ATS5": "ATS4"}


def _back_step(step, data):
    if step == "AT12":   # v6.6.3: back to the events step of the same path
        return "ATS5" if data.get("base") == "PEQUENO" else "AT11"
    return _BACK[step]


def _retry(step, data, head):
    return step, f"{head}\n\n{question(step, data)}"


FREE_CHAT_MIN_WORDS = 4


def _unmatched(step, data, head, text):
    """v6.6.2 (2d): typed text that matches no accepted answer. 4+ words → free chat
    (reply None: the app asks the LLM, keeps the step and appends the ↩️ nudge);
    shorter → today's clarification."""
    if len(norm(text).split()) >= FREE_CHAT_MIN_WORDS:
        return step, None
    return _retry(step, data, head)


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
    """AT10 (main) and ATS4 (small case): flat / varying (≤ 0.001 pu rule) / error.
    v6.6.2 (3d): a larger oscillation goes to AT10B (controls acting), not to AT9."""
    nxt, ret = ("AT11", "AT8") if step == "AT10" else ("ATS5", "ATS4")
    if data.get("osc_pending"):
        osc = parse_osc(text)
        if osc == "small":
            return _enter(nxt, data, _OSC_SMALL + "\n\n---\n\n")
        if osc == "large":
            data["ctrl_return"] = step
            return _enter("AT10B", data)
        return _unmatched(step, data, "Não identifiquei o tamanho da oscilação.", text)
    r = parse_flat(text)
    if r == "flat":
        return _enter(nxt, data, "Variáveis constantes: o caso está **inicializado corretamente**.\n\n---\n\n")
    if r == "varying":
        data["osc_pending"] = True
        return step, _OSC_QUESTION
    if r == "error":
        return _to_cdu(data, ret)
    return _unmatched(step, data, "Não identifiquei o resultado.", text)


def _ctrl_acting_step(data, text):
    """AT10B: adjusted → run again (AT8, or ATS4 in the small case); none → AT9 (CDU path)."""
    ret = data.get("ctrl_return") or "AT10"
    r = parse_ctrl_acting(text)
    if r == "adjusted":
        data.pop("ctrl_return", None)
        return _enter("AT8" if ret == "AT10" else "ATS4", data, "Controle ajustado no ANAREDE.\n\n")
    if r == "none":
        data.pop("ctrl_return", None)
        return _to_cdu(data, "AT8" if ret == "AT10" else "ATS4",
                       "Sem controles atuando: vamos verificar o ponto de operação pelo CDU.\n\n")
    return _unmatched("AT10B", data, f"Responda **{T_CTRL_ADJUSTED}** ou **{T_NO_CTRL}**.", text)


def _register_event(data, label, note):
    """Append {"type", "note"} (+ v6.6.3 fault keys: curto_previo, kv, teleprotecao,
    t_sem_falha_ms, t_com_falha_ms, kv_fora_tabela) and clear the fault sub-state."""
    event = {"type": label, "note": note}
    event.update(data.pop("fault", None) or {})
    data.pop("fault_stage", None)
    events = data.setdefault("events", [])
    events.append(event)
    return events


def _events_step(step, data, text):
    """AT11 / ATS5 (v6.6.1): menu → reminder → 'Evento inserido' or a description.
    Each event is stored as {"type": label, "note": free text or ""} (v6.6.3: + fault keys).
    v6.6.3: 'Encerrar' with at least one event goes to AT12 (ONS criteria)."""
    n = norm(text)
    if is_end(text):
        if data.get("event_pending") == OTHER_EVENT:   # described and answered: keep it
            _register_event(data, OTHER_EVENT, data.pop("event_note", "") or "")
        data.pop("event_pending", None)
        data.pop("event_menu", None)
        if data.get("events"):
            return _enter("AT12", data, f"**{len(data['events'])} evento(s) registrado(s).**\n\n")
        return "IDLE", closing_summary(data)
    pending = data.get("event_pending")
    if pending == OTHER_EVENT:
        add = n in ("adicionar outro evento", "adicionar", "outro evento", "adicionar evento",
                    "mais um evento")
        if n in _EVENT_DONE or add:
            events = _register_event(data, OTHER_EVENT, data.pop("event_note", "") or "")
            data.pop("event_pending", None)
            data.pop("event_menu", None)
            head = f"Evento {len(events)} registrado: **{event_text(events[-1])}**."
            if add:
                data["event_menu"] = True
                return step, f"{head}\n\n{question(step, data)}"
            return step, f"{head}\n\nDeseja adicionar outro evento ou encerrar?"
        if len(n.split()) >= FREE_CHAT_MIN_WORDS:   # a follow-up question: free chat again
            data["event_llm"] = True
            return step, None
        return _retry(step, data, "Não identifiquei a resposta.")
    if pending:
        note = "" if n in _EVENT_DONE else re.sub(r"\s+", " ", text or "").strip()[:300]
        if n not in _EVENT_DONE and len(note) < 3:
            return _retry(step, data, "Não identifiquei a resposta.")
        events = _register_event(data, pending, note)
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
        return _unmatched(step, data, "Não identifiquei o tipo de evento. Escolha uma opção de 1 a 5 "
                                      "(pelo botão, pelo número ou pelo nome).", text)
    if label == OTHER_EVENT:
        data["event_other"] = True
        return step, _OTHER_EVENT_ASK
    data["event_pending"] = label
    data.pop("fault", None)
    if label == FAULT_EVENT:   # v6.6.3 (3b): ask the operating voltage first
        data["fault_stage"] = "kv"
        return step, _event_head(label) + "\n\n" + KV_QUESTION
    if label == LINE_EVENT:    # v6.6.3 (3c): without / with a single-phase fault
        data["fault_stage"] = "line"
        return step, _event_head(label) + "\n\n" + LINE_FAULT_QUESTION
    return step, _event_reminder(label)


def _fault_done(step, data, kv, teleprotection=None):
    """Tabela 2 answer (kv None = 'Outra'). Bound to the pending event: stored in
    data['fault'], then the rest of the event reminder. A free question (3f): answered,
    then the step question again; nothing stored."""
    typed = data.pop("fault_kv", None) or kv
    text = fault_times_text(kv, teleprotection)
    times = fault_clearing_times(kv, teleprotection) if kv else None
    data.pop("fault_stage", None)
    if data.pop("fault_free", None):
        resume = data.pop("fault_resume", None)
        if resume:
            data["fault_stage"] = resume
        return step, f"{text}\n\n---\n\n{question(step, data)}"
    fault = data.setdefault("fault", {})
    for k in ("kv", "teleprotecao", "t_sem_falha_ms", "t_com_falha_ms", "kv_fora_tabela"):
        fault.pop(k, None)   # a new answer replaces the previous one
    if typed:
        fault["kv"] = typed
    if teleprotection is not None:
        fault["teleprotecao"] = teleprotection
    if times:
        fault["t_sem_falha_ms"], fault["t_com_falha_ms"] = times
    else:
        fault["kv_fora_tabela"] = True
    return step, f"{text}\n\n{_EVENT_TAIL}"


def _fault_step(step, data, text):
    """v6.6.3: an answer at the voltage / teleprotection / line-fault question, or None
    (not such an answer: the event goes on as before — 'Evento inserido' or a description;
    a free fault-time question at another step is dropped)."""
    stage = data["fault_stage"]
    hit = None
    if stage == "line":
        choice = parse_line_fault(text)
        if choice == "slg":
            data.setdefault("fault", {})["curto_previo"] = "monofasico"
            data["fault_stage"] = "kv"
            hit = step, f"Abertura **{T_SLG_FAULT.lower()}**.\n\n{KV_QUESTION}"
        elif choice == "none":
            data.setdefault("fault", {})["curto_previo"] = "sem"
            data.pop("fault_stage", None)
            hit = step, f"Abertura **{T_NO_PRIOR_FAULT.lower()}**.\n\n{_EVENT_TAIL}"
    elif stage == "kv":
        kv = parse_kv_answer(text)
        if kv == "outra":
            hit = _fault_done(step, data, None)
        elif kv in TELEPROTECTION_KV:
            data["fault_kv"] = kv
            data["fault_stage"] = "telep"
            hit = step, TELEP_QUESTION
        elif kv:
            data["fault_kv"] = kv   # kept as typed, even outside the table (no time given)
            hit = _fault_done(step, data, kv if kv in TABLE_KV else None)
    elif stage == "telep":
        telep = parse_teleprotection(text)
        if telep is not None:
            hit = _fault_done(step, data, data.get("fault_kv") or TELEPROTECTION_KV[0], telep)
    if hit is None and data.get("fault_free"):
        for k in ("fault_free", "fault_stage", "fault_kv"):
            data.pop(k, None)
        resume = data.pop("fault_resume", None)
        if resume:
            data["fault_stage"] = resume
    return hit


def _ask_fault_times(step, data):
    """3f: a typed question about fault times → the deterministic voltage question.
    Bound to a pending short circuit (or a line loss with a single-phase fault); free otherwise."""
    pending = data.get("event_pending")
    fault = data.get("fault") or {}
    bound = step in EVENT_STEPS and (pending == FAULT_EVENT or (
        pending == LINE_EVENT and fault.get("curto_previo") == "monofasico"))
    if not bound and not data.get("fault_free"):
        data["fault_free"] = True
        if data.get("fault_stage"):
            data["fault_resume"] = data["fault_stage"]
    data["fault_stage"] = "kv"
    return step, KV_QUESTION


# ── v6.6.3 (Part 4): AT12 — ONS criteria 2.4.3.7 ─────────────────────────────

_CRIT_NUM_RE = re.compile(r"(?<![\d.,])([1-4])(?![\d.,])")
_CRIT_FILLER = {"e", "o", "os", "a", "as", "criterio", "criterios", "violado", "violados", "foi", "foram",
                "ok"}


def parse_criteria(text):
    """'1 e 3' → ([1, 3], note or ''): numbers 1–4 plus the rest of the text as a note
    when it says more than the numbers."""
    nums = sorted({int(x) for x in _CRIT_NUM_RE.findall(text or "")})
    rest = [t for t in norm(_CRIT_NUM_RE.sub(" ", text or "")).split() if t not in _CRIT_FILLER]
    note = re.sub(r"\s+", " ", text or "").strip()[:300] if len(rest) >= 2 else ""
    return nums, note


def _at12_close(data, status):
    data["ons_criteria"] = status
    data.pop("crit_stage", None)
    head = f"{_AT12_RECORD}\n\n" if status == "violados" else ""
    return "IDLE", head + closing_summary(data)


def _at12_step(data, text):
    n = norm(text)
    if data.get("crit_stage") == "which":
        if n in ("concluir", "concluido", "pronto", "feito", "ok", "terminei"):
            if not data.get("ons_violated"):
                return _retry("AT12", data, "Marque pelo menos um critério (1 a 4).")
            return _at12_close(data, "violados")
        nums, note = parse_criteria(text)
        if not nums and is_question(text):
            return "AT12", None   # free chat, step kept
        if nums:
            data["ons_violated"] = sorted(set(data.get("ons_violated") or []) | set(nums))
        if note or (not nums and len(n) >= 3):
            data["ons_note"] = note or re.sub(r"\s+", " ", text).strip()[:300]
            return "AT12", "Observação registrada.\n\n" + _at12_which(data)
        if nums:
            return "AT12", _at12_which(data)
        return _retry("AT12", data, "Não identifiquei o critério.")
    nums, _ = parse_criteria(text)
    if n == norm(T_CRIT_SKIP) or _has(n, "pular", "pule", "nao verifiquei", "nao verificar"):
        return _at12_close(data, "nao_verificados")
    if n == norm(T_CRIT_VIOLATED) or _has(n, "violado", "violados", "violacao", "algum", "nao") or nums:
        data["crit_stage"] = "which"
        if nums:
            data["ons_violated"] = nums
        return "AT12", _at12_which(data)
    if n == norm(T_CRIT_OK) or _has(n, "atendidos", "atendido", "todos", "sim", "ok"):
        return _at12_close(data, "atendidos")
    return _unmatched("AT12", data, f"Responda **{T_CRIT_OK}**, **{T_CRIT_VIOLATED}** ou **{T_CRIT_SKIP}**.",
                      text)


def _other_event_note(step, data, text):
    """4b: the description typed after 'Outro' → free chat with OTHER_EVENT_RULE."""
    note = re.sub(r"\s+", " ", text or "").strip()[:300]
    if len(note) < 3:
        return _retry(step, data, "Descreva o que você quer analisar.")
    data.pop("event_other", None)
    data["event_pending"] = OTHER_EVENT
    data["event_note"] = note
    data["event_llm"] = True
    return step, None


def llm_extras(data):
    """(extra instruction, tail replacing the ↩️ nudge) for the free-chat answer of the
    'Outro' event; (None, None) otherwise. Pops the one-shot flag."""
    if data and data.pop("event_llm", None):
        return OTHER_EVENT_RULE, OTHER_EVENT_TAIL
    return None, None


_AT5_DMAQ_WORDS = ("dmaq", "dat", "caminho", "path", "pasta", "configurar")


def intercept(step, data, text):
    """v6.6.2: deterministic answers to TYPED text that must win over the free-chat
    routing of '?' questions (the app calls this first). (new_step, reply) or None.
      any step     → a question about fault times (v6.6.3: voltage question, Tabela 2)
      any step     → the answer to the voltage / teleprotection / line-fault question
      AT3          → a pasted ANAT0 error, read by its description (2a, v6.6.3)
      AT5          → a question about the DMAQ path / DAT line (2b)
      AT9          → 'CDU N … não está / está no DMAQ' (2c)
      AT11 / ATS5  → the description after 'Outro' (4b, answered by the free chat)"""
    if step not in ALL_STEPS:
        return None
    text = text or ""
    n = norm(text)
    if is_end(text) or is_help(text) or is_back(text):
        return None
    if asks_fault_times(text):   # v6.6.3 (3f): the voltage question, then Tabela 2
        return _ask_fault_times(step, data)
    if data.get("fault_stage"):
        hit = _fault_step(step, data, text)
        if hit is not None:
            return hit
    if step == "AT3":
        errs = parse_anat0_errors(text)
        if errs:
            data["anat0_error"] = True
            return "AT3", anat0_error_reply(errs)
    if step == "AT5" and _has(n, *_AT5_DMAQ_WORDS):
        if not _is_done(n) or is_question(text) or _has(n, "como"):
            return "AT5", at5_dmaq_answer(data)
    if step == "AT9":
        num, where = parse_cdu_where(text)
        cdu = data.get("cdu") or {}
        num = num or cdu.get("number")
        if num and where and (cdu.get("number") != num or not cdu.get("where")
                              or _CDU_NUM_RE.search(text)):
            data["cdu"] = {"number": num, "where": where}
            if where == "dmaq":
                return "AT9", _at9_branch_a(data, num)
            return _cdu_finish(data, _at9_branch_b(num), passo_d=False)
    if step in EVENT_STEPS and data.get("event_other"):
        return _other_event_note(step, data, text)
    return None


def handle(step, data, text):
    """(new_step, reply) for a message at an ANATEM step. 'IDLE' = simulation ended.
    reply None (v6.6.2) = answer through the free chat, step kept (2d / 4b)."""
    text = text or ""
    n = norm(text)

    if step == "AT12" and is_end(text):
        return _at12_close(data, "violados" if data.get("ons_violated") else "nao_verificados")
    if step not in EVENT_STEPS and is_end(text):
        return "IDLE", ENDED_TEXT
    if is_help(text):
        details = _STEP_DETAILS.get(step)
        return step, (f"**Ajuda — {STEP_LABELS.get(step, step)}**\n\n{question(step, data)}"
                      + (f"\n\n{details}" if details else ""))
    if is_back(text):
        if step == "AT1":
            return step, "Este já é o primeiro passo.\n\n" + question(step, data)
        if step == "AT9":
            prev = data.pop("cdu_return", "AT8")
        elif step == "AT10B":
            prev = data.pop("ctrl_return", "AT10")
        else:
            prev = _back_step(step, data)
        return _enter(prev, data, "Voltando um passo.\n\n")

    hit = intercept(step, data, text)
    if hit is not None:
        return hit

    if step == "AT1":
        base = parse_base(text, data)
        if base is None:
            return _unmatched("AT1", data, "Não identifiquei a escolha.", text)
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
            return "AT3", at3_error_message()
        return _unmatched("AT3", data, f"Responda **{T_RAN_OK}** ou **{T_RAN_ERR}**.", text)

    if step == "AT4":
        name = parse_filename(text)
        if not name:
            return _retry("AT4", data, "Não identifiquei o nome do arquivo.")
        data["dmaq_name"] = name
        return _enter("AT5", data, f"Arquivo DMAQ: **{name}**.\n\n")

    if step == "AT5":
        if _is_done(n):
            return _enter("AT6", data, "Arquivo .stb configurado.\n\n")
        return _unmatched("AT5", data, f"Quando terminar os três ajustes, responda **{T_CONFIGURED}**.", text)

    if step == "AT6":
        if data.get("equip") == "pendente":
            if _is_done(n):
                data["equip"] = "incluidos"
                return _enter("AT7", data, "Modelos incluídos no .stb.\n\n")
            return _unmatched("AT6", data, f"Quando terminar, responda **{T_MODELS_DONE}**.", text)
        if data.get("equipment") != "include" and not _has(n, "ja incluidos", "ja estao"):
            choice = parse_equipment_choice(text, data)
            if choice is None:
                return _unmatched("AT6", data, f"Responda **{T_CONVENTIONAL}** ou **{T_INCLUDE_EQUIP_LABEL}**.",
                                  text)
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
        return _unmatched("AT6", data, f"Responda **{T_YES}** ou **{T_ALREADY}**.", text)

    if step == "AT7":
        if _is_done(n):
            return _enter("AT8", data, "Simulação de verificação preparada.\n\n")
        return _unmatched("AT7", data, f"Quando terminar, responda **{T_READY}**.", text)

    if step == "AT8":
        r = parse_ran(text)
        if r == "ok":
            return _enter("AT10", data, "Execução sem erros.\n\n")
        if r == "error":
            return _to_cdu(data, "AT8")
        return _unmatched("AT8", data, f"Responda **{T_RAN_OK}** ou **{T_RUN_CDU_ERR}**.", text)

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
                return _unmatched("AT9", data, "Não identifiquei a resposta.", text)
            cdu["where"] = w
            if w == "dmaq":
                return "AT9", _at9_branch_a(data, cdu["number"])
            return _cdu_finish(data, _at9_branch_b(cdu["number"]), passo_d=False)
        ctrl = parse_ctrl(text)
        if ctrl is None:
            return _unmatched("AT9", data, f"Responda **{T_GOV}**, **{T_AVR}** ou **{T_PSS}**.", text)
        cdu["ctrl"] = ctrl
        return _cdu_finish(data, {"gov": _GOV_ADVICE, "avr": _AVR_ADVICE, "pss": _PSS_ADVICE}[ctrl])

    if step in ("AT10", "ATS4"):
        return _flat_step(step, data, text)

    if step == "AT10B":
        return _ctrl_acting_step(data, text)

    if step in EVENT_STEPS:
        return _events_step(step, data, text)

    if step == "AT12":
        return _at12_step(data, text)

    if step == "ATS2":
        if data.get("ats2_files") == "guide":
            if is_files_continue(text):
                data["ats2_files"] = "yes"
                return "ATS2", question("ATS2", data)
            return _unmatched("ATS2", data,
                              f"Quando tiver os dois arquivos, clique em **{T_FILES_CONTINUE}**.", text)
        if ats2_files_question(data) and not parse_sav(text):
            has = parse_has_files(text)
            if has == "no":
                data["ats2_files"] = "guide"
                data["small_case_no_files"] = True
                return "ATS2", ATS2_EXAMPLE_GUIDE
            if has == "yes":
                data["ats2_files"] = "yes"
                return "ATS2", question("ATS2", data)
            return _unmatched("ATS2", data, f"Responda **{T_HAS_FILES}** ou **{T_NO_FILES}**.", text)
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
                return _unmatched("ATS3", data, f"Responda **{T_CONVENTIONAL}** ou **{T_INCLUDE_EQUIP_LABEL}**.",
                                  text)
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
        return _unmatched("ATS3", data, f"Quando terminar, clique em **{T_CONFIRM_MODELS}**.", text)

    return step, question(step, data)
