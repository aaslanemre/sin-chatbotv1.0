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
_AT4_ASK = ("**Passo 4 — DMAQ ajustado.** Qual o nome do arquivo salvo pelo ANAT0? "
            "(ex: `dmaq_anat0.dma`)")
_AT4_DETAILS = ("Esse arquivo contém o bloco **DMAQ** com o número de unidades de cada máquina "
                "síncrona ajustado ao ponto de operação.")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _at5_main(data) -> str:
    sav = data.get("sav_name") or "o seu .sav"
    case = data.get("case_number") or "o mesmo do ANAT0"
    dmaq = data.get("dmaq_name") or "o arquivo gerado pelo ANAT0"
    return (
        "**Passo 5 — Edição do .stb.** Abra o arquivo **.stb** da base em um editor de texto "
        "e faça três ajustes:\n"
        f"1. No bloco **ULOG/DARQ**, troque o nome do .sav por **{sav}**.\n"
        f"2. Confira se o número do caso na linha de leitura do fluxo de potência é **{case}** "
        "(o mesmo usado no ANAT0).\n"
        f"3. No bloco **ULOG**, troque o arquivo DMAQ original por **{dmaq}** (gerado pelo ANAT0).\n\n"
        f"Responda **{T_CONFIGURED}** quando terminar."
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _at6_main(data) -> str:
    line = _handoff_equipment_line(data)
    return ("**Passo 6 — Equipamentos.** Deseja incluir os modelos do **BESS, STATCOM ou HVDC**?"
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
_AT8_MAIN = (
    "**Passo 8 — Primeira execução.** Carregue o **.stb** no ANATEM, execute a simulação e "
    "leia o relatório de saída.\n\n"
    "**Rodou sem erros?**"
)

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
    "grandes, rode o ANAT0 novamente ou atualize o DMAQ manualmente. Depois, rode o ANATEM de novo."
)
_PASSO_D_SMALL = ("**Passo D** — Depois de ajustar e convergir no ANAREDE, salve o **.sav** e "
                  "rode o ANATEM de novo.")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _at9_branch_b(cdu) -> str:
    return (
        f"Procure o CDU **{cdu}** nos outros arquivos do ANATEM:\n"
        "- **Usinas eólicas/fotovoltaicas** (os arquivos costumam ter nomes como `EOL_NE.dat` ou "
        "`UFV.DAT`, mas procure independentemente do nome): busque o código **DFNT**, que "
        "associa o CDU à barra do sistema.\n"
        "- **Elos CC**: busque **DCNV** ou **DCNE** (pode haver outros).\n\n"
        "Identifique o equipamento e a barra e ajuste o ponto de operação no ANAREDE como no "
        "caso da máquina síncrona: salve o **.sav** e rode o ANATEM de novo."
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
def _events_main(step) -> str:
    n = "11" if step == "AT11" else "5"
    return (
        f"**Passo {n} — Simulação de eventos (DEVT).**\n"
        "1. Insira as perturbações no bloco **DEVT** (ex: curto-circuito, abertura de linha, degrau).\n"
        "2. Rode o ANATEM.\n"
        "3. Salve os resultados.\n\n"
        f"Informe os eventos inseridos ou digite **encerrar**."
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
        f"1. Aponte para o .sav **{data['sav_name']}**.\n"
        f"2. Confirme o número do caso (**{data['case_number']}**).\n"
        f"3. Use o bloco **DMAQ** diretamente, com as máquinas das barras **{buses}**."
    )


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
def _ats3_main(data) -> str:
    line = _handoff_equipment_line(data)
    return ("**Passo 3 — Equipamentos (STATCOM, BESS, elo VSC).** Inclua os blocos dos modelos "
            "diretamente no **.stb**, usando **DFNT** ou outros códigos."
            + (f"\n\n{line}" if line else "")
            + f"\n\nClique em **{T_CONFIRM_MODELS}** quando terminar.")


# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
_ATS4_MAIN = (
    "**Passo 4 — Teste de inicialização sem eventos (flat run).** Desative os eventos do "
    "**DEVT**, rode o ANATEM e veja as variáveis no **PLOTCEPEL** (olhe primeiro a escala do "
    "eixo Y). As variáveis ficaram em linha reta, variando, ou deu erro?"
)

_STEP_DETAILS = {
    "AT1": _AT1_NOTE, "AT2": _AT2_NOTE, "AT3": _AT3_DETAILS, "AT4": _AT4_DETAILS,
    "AT7": _AT7_DETAILS, "AT9": CDU_NOTE, "ATS2": _ATS2_DETAILS,
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
        return _at6_include(data) if data.get("equip") == "pendente" else _at6_main(data)
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
        if data.get("events"):
            return f"**{len(data['events'])} evento(s) registrado(s).** Deseja adicionar outro evento ou encerrar?"
        return _events_main(step)
    if step == "ATS2":
        return _ats2_question(data)
    if step == "ATS3":
        return _ats3_main(data)
    return ""


def _entry(step, data) -> str:
    """Message shown when the flow ENTERS `step` (sub-state reset): main + Detalhes."""
    if step == "AT9":
        return _AT9_ASK + "\n\n" + "ℹ️ " + CDU_NOTE
    return with_details(question(step, data), _STEP_DETAILS.get(step, ""))


# Per-step sub-states; entering any step starts it clean.
_SUBSTATE_KEYS = ("at2_confirm", "anat0_error", "cdu", "osc_pending")


def _enter(step, data, prefix=""):
    for k in _SUBSTATE_KEYS:
        data.pop(k, None)
    if step == "AT2" and data.get("sav_name") and data.get("case_number"):
        data["at2_confirm"] = True
    if step == "AT6" and data.get("equip") == "pendente":
        data.pop("equip", None)
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


def equipment_text(data):
    h = data.get("handoff") or {}
    parts = []
    if h.get("equipment_type"):
        parts.append(h["equipment_type"] + (f" (barra {h['equipment_bus']})" if h.get("equipment_bus") else ""))
    if data.get("equip") in _EQUIP_LABELS:
        parts.append(_EQUIP_LABELS[data["equip"]])
    return " · ".join(parts) or None


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
    body += "".join(f"\n  - {e}" for e in events)
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
    n = norm(text)
    if is_end(text):
        return "IDLE", closing_summary(data)
    if n in ("adicionar outro evento", "adicionar", "outro evento", "adicionar evento",
             "mais um evento", "outro"):
        return step, "Descreva o próximo evento inserido no **DEVT** (ex: curto-circuito na barra 1001 em t = 1 s)."
    event = re.sub(r"\s+", " ", text or "").strip()
    if len(event) < 3:
        return _retry(step, data, "Não identifiquei o evento.")
    events = data.setdefault("events", [])
    events.append(event[:300])
    return step, (f"Evento {len(events)} registrado: **{event[:300]}**.\n\n"
                  "Deseja adicionar outro evento ou encerrar?")


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
        if _has(n, "sem", "nao", "nenhum"):
            data["equip"] = "nenhum"
            return _enter("ATS4", data, "Sem modelos de equipamentos.\n\n")
        if _is_done(n) or _has(n, "confirmo", "inclusao"):
            data["equip"] = "incluidos"
            return _enter("ATS4", data, "Modelos incluídos no .stb.\n\n")
        return _retry("ATS3", data, f"Quando terminar, clique em **{T_CONFIRM_MODELS}**.")

    return step, question(step, data)
