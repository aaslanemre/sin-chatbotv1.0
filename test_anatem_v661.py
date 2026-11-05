"""
v6.6.1 — ANATEM flow fixes from the revised Word guide + expert feedback (P1–P5):
P1 small case without .SAV/.STB, P2 optional equipment step, P3 DARQ (not ULOG)
instructions, P4 menu/F5 to run, P5 event menu. Real app (runpy) on the shared
harness; only the LLM chain is faked.

Run from repo root:  python3 test_anatem_v661.py
"""
import copy
import glob
import re

import _harness_v650 as H
from _harness_v650 import (ss, EV, svc, check, section, fresh, run, events,
                           last_assistant, assistants, StreamChain, scores)
from agents import anatem_flow as AT
from agents import structured_input as SI
from config.glossary import GLOSSARY, GLOSSARY_ANATEM
from config.version import APP_VERSION, RELEASE_NOTES

H.st.warning = lambda body="", **kw: EV.append(("warning", body))

ONS = {"sim_type": "BESS", "db": "ONS", "years": [2028], "year_idx": 0, "year": 2028,
       "scenario": "Inverno Máxima Diurna"}
BESS_FULL = dict(ONS, bess_bus="1001", bess_mode="PV", bess_mva="100", bess_p_mw="80",
                 bess_bus_number="9001")
NET = {"title": "Meu Caso", "base_mva": 100.0,
       "buses": [{"number": 1, "name": "REF", "kv": 230.0, "tipo": 2, "v_pu": 1.05, "angle_deg": 0.0,
                  "p_gen_mw": 0.0, "q_min_mvar": 0.0, "q_max_mvar": 0.0, "p_load_mw": 0.0, "q_load_mvar": 0.0},
                 {"number": 2, "name": "CARGA", "kv": 230.0, "tipo": 0, "v_pu": 1.0, "angle_deg": 0.0,
                  "p_gen_mw": 0.0, "q_min_mvar": 0.0, "q_max_mvar": 0.0, "p_load_mw": 100.0, "q_load_mvar": 30.0}],
       "lines": [{"id": 1, "from_bus": 1, "to_bus": 2, "circuit": 1, "r_pct": 0.5, "x_pct": 5.0, "q_mvar": 10.0}]}
AT5D = {"base": "ONS", "sav_name": "caso_estudo.sav", "case_number": "5", "dmaq_name": "dmaq_anat0.dma"}
SMALL = {"base": "PEQUENO", "sav_name": "rede.sav", "case_number": "1", "gen_buses": ["10"]}


# ── helpers (same as test_anatem_v660.py) ─────────────────────────────────────

def chain():
    return StreamChain(["Resposta livre."], scores(("manual.pdf", 0.8)))


def start(ch=None):
    fresh(ch or chain())
    run()


def at_state(step, data=None):
    d = {"sim_type": "ANATEM"}
    d.update(copy.deepcopy(data or {}))
    fresh(chain(), step=step, data=d, status="active")
    env = run()
    env["_append_system_assistant_message"](env["_current_step_question"]())
    run()


def step():
    return ss["sim_step"]


def data():
    return ss["sim_data"]


def reply():
    return last_assistant()["content"]


def option_buttons():
    return [e for e in events("button") if e[2] and e[2].startswith("opt_")]


def option_texts():
    return [e[4][0][0] for e in option_buttons()]


def click(text):
    b = next(e for e in option_buttons() if e[4][0][0] == text or e[1] == text)
    b[3](*b[4])
    run()


def press_key(key_prefix):
    b = next(e for e in events("button") if e[2] and e[2].startswith(key_prefix))
    b[3](*b[4])
    run()


def has_key(key_prefix):
    return any(e[2] and str(e[2]).startswith(key_prefix) for e in events("button"))


def submit(form_id, values):
    sub = next(e for e in events("submit") if e[4][0]["id"] == form_id)
    spec, base, sel = sub[4]
    for f in SI.form_fields(spec, sel):
        ss[f"fld_{base}_{f['key']}"] = values.get(f["key"], "")
    sub[3](*sub[4])
    run()


def forms():
    return [e[4][0]["id"] for e in events("submit")]


def panel():
    """Study panel after the last input (the sidebar renders before the input is processed)."""
    run()
    return [e[1] for e in EV if e[0] == "markdown"]


def handoff_from(step_, d):
    fresh(chain(), step=step_, data=copy.deepcopy(d), status="active")
    env = run()
    env["_append_system_assistant_message"](env["_current_step_question"]() or "Próximos passos.")
    run()
    press_key("handoff_")


def strip_md(t):
    return t.replace("**", "").replace("`", "")


# Every text the guide can show: each step × sub-state (entry message with Detalhes and
# the bare question), the help texts, the fixed blocks, the glossary and the release notes.
SUBSTATES = [{}, {"anat0_error": True}, {"equipment": "include"}, {"equip": "pendente"},
             {"cdu": {"number": "7"}}, {"cdu": {"number": "7", "where": "dmaq"}}, {"osc_pending": True},
             {"events": ["x"]}, {"events": [{"type": "Curto-circuito", "note": ""}], "event_menu": True},
             {"ats2_files": "guide"}, {"ats2_files": "yes"}, {"handoff": {"equipment_type": "BESS",
                                                                         "equipment_bus": "9001"}}]
SUBSTATES += [{"event_pending": label} for label in AT.EVENT_LABELS]


def all_texts():
    out = []
    for s in AT.ALL_STEPS:
        for sub in SUBSTATES:
            d = dict(AT5D, **sub)
            out += [AT.question(s, d), AT._entry(s, copy.deepcopy(d)), AT.handle(s, copy.deepcopy(d), "ajuda")[1]]
    d = dict(SMALL)
    out += [AT._ats2_done(d), AT.STB_CODES, AT.ATS2_EXAMPLE_GUIDE, AT.CDU_NOTE, AT._AT3_ERROR,
            AT._GOV_ADVICE, AT._AVR_ADVICE, AT._PASSO_D_SIN, AT._PASSO_D_SMALL, AT._at9_branch_b("7"),
            AT.EVENT_CODES_NOTE, AT.EQUIPMENT_EDIT_QUESTION, AT.INTRO_FULL, AT.INTRO_SHORT,
            AT.closing_summary(dict(AT5D, events=[{"type": "Curto-circuito", "note": "n"}]))]
    out += list(GLOSSARY.values()) + list(GLOSSARY_ANATEM.values())
    notes = RELEASE_NOTES[APP_VERSION]
    out += notes["novidades"] + notes["o_que_testar"]
    for s in AT.ALL_STEPS:
        for sub in SUBSTATES:
            for spec in SI.controls_for(s, dict(AT5D, **sub)):
                out += [o["label"] + " " + o["text"] for o in spec.get("options", [])]
    return out


def sentences(text):
    """Split into sentences: line breaks, list items, and . ! ? ; followed by a space
    (so '.SAV' / '.DMA/.DAT' inside a sentence do not split it)."""
    return [s for s in re.split(r"\n+|(?<=[.!?;])\s+", text) if s.strip()]


# ═════════════════════════════════════════════════════════════════════════════
section("1. P1 — small case: 'Você já tem um .SAV e um .STB?'")
# ═════════════════════════════════════════════════════════════════════════════
def to_small():
    start()
    run("quero simular no anatem")
    click(AT.T_SMALL)


to_small()
check("option 3 → ATS2 asks first whether the user has a .SAV and a .STB (two buttons)",
      step() == "ATS2" and "Você já tem um arquivo .SAV e um .STB para o seu caso?" in reply()
      and option_texts() == [AT.T_HAS_FILES, AT.T_NO_FILES] and "ats_case" not in forms(), option_texts())


def t_no_files():
    to_small()
    click(AT.T_NO_FILES)
    guide = reply()
    ok = (step() == "ATS2" and "9BARRAS.PWF" in guide and "9_barras.lst" in guide
          and "Arquivo > Salvar Caso Histórico" in guide and data().get("small_case_no_files") is True
          and option_texts() == [AT.T_FILES_CONTINUE])
    # a .stb FILE NAME (anything.stb) is never invented — only the extension is named
    no_stb_name = not re.search(r"[\w-]+\.stb\b", guide, re.I)
    return ok, no_stb_name, guide


ok, no_stb_name, guide = t_no_files()
check("'Não tenho' → example-case guidance (9BARRAS.PWF, .LST, Arquivo > Salvar Caso Histórico), "
      "flag small_case_no_files, only the [continuar] button", ok, guide)
check("the guidance never invents a .STB file name or path", no_stb_name, guide)
check("the guidance says the guide cannot create the .STB and where to get one",
      "não consegue criar o .STB" in guide and "instalação do ANATEM" in guide and "colega" in guide)
check("panel shows the 'no own files' flag",
      "Arquivos .SAV/.STB: **sem arquivos próprios (orientação do caso de exemplo)**" in panel())
run("rede.sav, caso 1, barras 10")
check("guidance does NOT advance on other input (no .sav stored, same step)",
      step() == "ATS2" and "sav_name" not in data() and AT.T_FILES_CONTINUE in reply())
click(AT.T_FILES_CONTINUE)
check("[continuar] → the normal ATS2 questions (.sav, case, generator buses) with the form",
      step() == "ATS2" and "Informe o nome do arquivo **.sav**" in reply() and "ats_case" in forms())
submit("ats_case", {"sav": "9barras.sav", "case": "1", "buses": "1, 2, 3"})
check("…and the form then goes on to ATS3", step() == "ATS3" and data()["sav_name"] == "9barras.sav")

to_small()
click(AT.T_HAS_FILES)
check("'Sim, já tenho' → straight to the v6.6.0 ATS2 question, no flag",
      step() == "ATS2" and reply().startswith(AT._ATS2_ASK) and "ats_case" in forms()
      and "small_case_no_files" not in data())
to_small()
run("rede.sav, caso 1, barras 10, 20")
check("typing the .sav data straight away also works (answers 'yes')", step() == "ATS3")

handoff_from("NET7_RESULTS", {"sim_type": "NETWORK", "network": copy.deepcopy(NET), "net7_color": "green"})
run("sim")
check("handoff from the ANAREDE network (no .sav captured) → the same pre-question",
      step() == "ATS2" and "Você já tem um arquivo .SAV e um .STB" in reply())
at_state("ATS3", SMALL)
run("voltar")
check("back to ATS2 with a .sav already known → no pre-question", step() == "ATS2"
      and "Você já tem" not in reply())


# ═════════════════════════════════════════════════════════════════════════════
section("2. P2 — equipment step is optional (AT6 and ATS3)")
# ═════════════════════════════════════════════════════════════════════════════
BRANCH_Q = ("Seu estudo é puramente eletromecânico convencional (apenas máquinas síncronas e reguladores "
            "básicos) ou você pretende acoplar novos equipamentos de eletrônica de potência/armazenamento "
            "(BESS, STATCOM, elo VSC-HVDC)?")


def t_conventional(step_="AT6", base=AT5D, nxt="AT7"):
    at_state(step_, base)
    asked = BRANCH_Q in reply() and option_texts() == [AT.T_CONVENTIONAL, AT.T_INCLUDE_EQUIP]
    click(AT.T_CONVENTIONAL)
    return (asked and step() == nxt and data().get("equipment") == "none"
            and "Equipamentos: **nenhum (estudo convencional)**" in panel())


check("AT6: branching question with [Estudo convencional] [Incluir BESS/STATCOM/HVDC]; "
      "conventional → AT7, equipment='none', panel 'nenhum (estudo convencional)'", t_conventional())
check("ATS3: conventional → ATS4 (flat run), equipment='none'", t_conventional("ATS3", SMALL, "ATS4"))
labels = [e[1] for e in option_buttons()]
at_state("AT6", AT5D)
check("button labels as specified", [e[1] for e in option_buttons()] == [AT.T_CONVENTIONAL, "Incluir BESS/STATCOM/HVDC"])
click(AT.T_INCLUDE_EQUIP)
check("'Incluir' at AT6 → the v6.6.0 question with [Sim] [Já incluídos no .stb] (not the ANAREDE notice)",
      step() == "AT6" and data().get("equipment") == "include" and option_texts() == [AT.T_YES, AT.T_ALREADY])
click(AT.T_YES)
check("…[Sim] → the v6.6.0 instructions (DCDU/DARQ) and [Modelos incluídos]",
      step() == "AT6" and "DCDU" in reply() and option_texts() == [AT.T_MODELS_DONE])
click(AT.T_MODELS_DONE)
check("…→ AT7, equip 'incluidos'", step() == "AT7" and data().get("equip") == "incluidos")
at_state("AT6", AT5D); click(AT.T_INCLUDE_EQUIP); click(AT.T_ALREADY)
check("'Incluir' → [Já incluídos no .stb] → AT7", step() == "AT7" and data().get("equip") == "ja_no_stb")
at_state("ATS3", SMALL); click(AT.T_INCLUDE_EQUIP)
check("'Incluir' at ATS3 → the v6.6.0 instruction (DFNT) with its buttons",
      step() == "ATS3" and "DFNT" in reply() and option_texts() == [AT.T_CONFIRM_MODELS, AT.T_NO_MODELS])
at_state("AT6", AT5D); run("estudo convencional")
check("typed 'estudo convencional' works too", step() == "AT7" and data()["equipment"] == "none")
at_state("AT6", AT5D); run("sim")
check("'sim' without a handoff is ambiguous → re-asks", step() == "AT6" and "equipment" not in data())

at_state("AT6", AT5D)
check("no handoff: no default button", not any(e[6].get("type") == "primary" for e in option_buttons()))


def t_handoff_default():
    handoff_from("STEP12", BESS_FULL)
    run("sim")
    for t in ["c.sav, caso 3", "rodou sem erros", "d.dma", "configurado"]:
        run(t)
    btns = option_buttons()
    inc = [e for e in btns if e[4][0][0] == AT.T_INCLUDE_EQUIP]
    conv = [e for e in btns if e[4][0][0] == AT.T_CONVENTIONAL]
    return (step() == "AT6" and len(btns) == 2 and inc and conv
            and inc[0][6].get("type") == "primary" and conv[0][6].get("type") != "primary"
            and "(sugerido)" in inc[0][1] and "BESS** na barra **9001**" in reply()
            and "Sugestão: **Incluir BESS/STATCOM/HVDC**" in reply())


check("handoff with a BESS bus: both buttons, 'Incluir' is the default (highlighted, sugerido), bus mentioned",
      t_handoff_default(), reply())
run("sim")
check("…and 'sim' keeps the default (include)", step() == "AT6" and data().get("equipment") == "include")


def t_edit():
    at_state("AT8", dict(AT5D, equipment="none"))
    if not has_key("edit_at_equipment"):
        return False
    press_key("edit_at_equipment")
    both = option_texts() == [AT.T_CONVENTIONAL, AT.T_INCLUDE_EQUIP] and BRANCH_Q in reply()
    click(AT.T_INCLUDE_EQUIP)
    to_inc = data()["equipment"] == "include" and step() == "AT8" and "✏️" in reply() and "DARQ" in reply()
    press_key("edit_at_equipment")
    click(AT.T_CONVENTIONAL)
    to_none = data()["equipment"] == "none" and "nenhum (estudo convencional)" in reply() and step() == "AT8"
    return both and to_inc and to_none


check("✏️ on 'Equipamentos' offers both values and switches none ⇄ include (step kept)", t_edit())
at_state("AT6", dict(AT5D, equipment="include"))
check("no ✏️ at AT6 itself (the question is on screen) nor before the choice",
      not has_key("edit_at_equipment"))
at_state("AT5", AT5D)
check("v6.6.0 panel stays read-only before the choice (no ✏️ at all)", not has_key("edit_"))
check("closing summary: 'Equipamentos: nenhum (estudo convencional)'",
      "Equipamentos: **nenhum (estudo convencional)**" in AT.closing_summary(dict(AT5D, equipment="none")))
check("'voltar' from AT7 asks the equipment question again from the start",
      (at_state("AT7", dict(AT5D, equipment="none")) or True) and (run("voltar") or True)
      and step() == "AT6" and "equipment" not in data() and BRANCH_Q in reply())


# ═════════════════════════════════════════════════════════════════════════════
section("3. P3 — DARQ, not ULOG")
# ═════════════════════════════════════════════════════════════════════════════
WORD_ACTIONS = [
    "No cartão DARQ, localize a declaração de arquivo associada à rede de fluxo de potência e atualize "
    "para o nome do seu arquivo .SAV convergido",
    "Na linha de leitura do .SAV, confirme se o número do caso especificado corresponde exatamente ao "
    "número do caso convergido no ANAREDE e processado no ANAT0",
    "No cartão DARQ, substitua a referência do arquivo DMAQ original pelo caminho do novo arquivo gerado "
    "pelo ANAT0",
]


def t_no_ulog_darq():
    texts = all_texts()
    return not any("ULOG/DARQ" in t or "ULOG ou DARQ" in t for t in texts)


def t_at5_word():
    t5 = strip_md(AT.question("AT5", AT5D))
    t5_empty = strip_md(AT.question("AT5", {}))
    return (all(a in t5 for a in WORD_ACTIONS) and all(a in t5_empty for a in WORD_ACTIONS)
            and "ULOG" not in t5 and "caso_estudo.sav" in t5 and "dmaq_anat0.dma" in t5
            and t5.index("Substituir o arquivo .SAV") < t5.index("Conferir o número do caso")
            < t5.index("Substituir o arquivo DMAQ"))


def t_ulog_only_in_codes():
    """ULOG only in the separate code entry / optional sentence (STB_CODES) and the glossary."""
    texts = [t.replace(AT.STB_CODES, "") for t in all_texts()
             if t not in GLOSSARY_ANATEM.values()]
    gl = [k for k, v in {**GLOSSARY, **GLOSSARY_ANATEM}.items() if "ULOG" in v or k == "ULOG"]
    return not any("ULOG" in t for t in texts) and gl == ["ULOG"]


def t_same_sentence():
    """Grep: no sentence anywhere (bot texts + source string lines) has ULOG and DARQ together."""
    bad = [s for t in all_texts() for s in sentences(t) if "ULOG" in s and "DARQ" in s]
    for path in ["app.py"] + glob.glob("agents/*.py") + glob.glob("config/*.py") + glob.glob("prompts/*.py"):
        for line in open(path, encoding="utf-8"):
            bad += [f"{path}: {s}" for s in sentences(line) if "ULOG" in s and "DARQ" in s]
    return bad


check("no bot text contains 'ULOG/DARQ' or 'ULOG ou DARQ'", t_no_ulog_darq())
check("AT5: the three DARQ actions with the Word-file wording, in order (with and without known values)",
      t_at5_word(), AT.question("AT5", AT5D))
ats2 = strip_md(AT._ats2_done(dict(SMALL)))
check("ATS2 (small case): the same DARQ wording for the .SAV and the case number, no ULOG, no ANAT0",
      WORD_ACTIONS[0] in ats2 and "Na linha de leitura do .SAV, confirme se o número do caso especificado "
      "corresponde exatamente ao número do caso convergido no ANAREDE" in ats2
      and "ULOG" not in ats2 and "ANAT0" not in ats2, ats2)
codes = AT._entry("AT5", dict(AT5D))
check("AT5 'Detalhes' lists ULOG and DARQ as separate entries (Word-file wording)",
      "- **ULOG:** Define a atribuição explícita de unidades lógicas computacionais de leitura/gravação." in codes
      and "- **DARQ:** Declara o nome e o caminho dos arquivos externos utilizados na simulação dinâmica "
          "(arquivo .SAV de fluxo, arquivo de máquinas .DMA/.DAT, arquivos de controladores .CDU)." in codes)
check("'ajuda' at AT5 shows the code list too", "**ULOG:**" in AT.handle("AT5", dict(AT5D), "ajuda")[1])
check("ULOG appears only in the code list / optional sentence and in its glossary entry", t_ulog_only_in_codes())
bad = t_same_sentence()
check("grep: no sentence contains ULOG together with DARQ (bot texts + app/agents/config/prompts)", not bad, bad)
check("glossary: DARQ and ULOG as in the Word file",
      GLOSSARY_ANATEM["DARQ"].startswith("Declara o nome e o caminho dos arquivos externos")
      and GLOSSARY_ANATEM["ULOG"] == "Define a atribuição explícita de unidades lógicas computacionais de "
                                     "leitura/gravação.")
at4 = AT.question("AT4", {})
check("AT4 example is neutral (dmaq_anat0 + the user's extension), form placeholder too",
      "dmaq_anat0.dma" not in at4 and "`dmaq_anat0`" in at4 and "extensão que você escolheu" in at4
      and SI.F_AT_DMAQ["placeholder"] == "ex: dmaq_anat0")
check("instructions say 'arquivo DMAQ gerado pelo ANAT0'; '.DMA/.DAT' only in the DARQ definition",
      "arquivo DMAQ original pelo caminho do novo arquivo gerado pelo ANAT0" in strip_md(AT.question("AT5", {}))
      and [t for t in set(all_texts()) if ".DMA/.DAT" in t and AT.STB_CODES not in t
           and t != GLOSSARY_ANATEM["DARQ"]] == [])
check("DMAQ.STB kept only as the ANAT0 input file at AT3 (BNT1.DAT, BNT2.DAT, DMAQ.STB)",
      "**BNT1.DAT**, **BNT2.DAT** e **DMAQ.STB**" in AT.question("AT3", {})
      and all("DMAQ.STB" not in t for t in all_texts() if "BNT1.DAT" not in t))


# ═════════════════════════════════════════════════════════════════════════════
section("4. P4 — Simulação > Executar / F5")
# ═════════════════════════════════════════════════════════════════════════════
def t_run_texts():
    at_state("AT7", AT5D)
    click(AT.T_READY)
    at8 = reply()
    at_state("AT9", dict(AT5D, cdu_return="AT8"))
    run("CDU 1042"); click(AT.T_IN_DMAQ); click(AT.T_GOV)
    back = reply()
    at_state("ATS3", SMALL)
    click(AT.T_CONVENTIONAL)
    ats4 = reply()
    has = lambda t: "Simulação > Executar" in t and "F5" in t
    return (step() == "ATS4" and has(at8) and has(back) and has(ats4)
            and "1. Menu superior: **Simulação > Executar**;" in at8
            and "2. Ou use o atalho de teclado: **F5** para iniciar a simulação dinâmica." in at8
            and "janela de mensagens" in at8), (at8, back, ats4)


ok, txts = t_run_texts()
check("AT8, the AT9→AT8 return (Passo D) and ATS4 all name 'Simulação > Executar' and 'F5'", ok, txts)
at_state("AT8", AT5D)
check("AT8 answer buttons unchanged", option_texts() == [AT.T_RAN_OK, AT.T_RUN_CDU_ERR])
check("the not-in-DMAQ branch and the small-case Passo D name them too",
      "F5" in AT._at9_branch_b("7") and "F5" in AT._PASSO_D_SMALL)


# ═════════════════════════════════════════════════════════════════════════════
section("5. P5 — event menu")
# ═════════════════════════════════════════════════════════════════════════════
at_state("AT10", AT5D)
click(AT.T_FLAT)
menu = reply()
check("entering AT11: the four event types with descriptions and codes, plus the 'Detalhes' note",
      all(l in menu for l in AT.EVENT_LABELS) and "(códigos: APCB, APCC, APCL)" in menu
      and "(código: ABCI)" in menu and "(código: RMGR)" in menu and "(códigos: MDLP e MDLQ)" in menu
      and AT.EVENT_CODES_NOTE in menu)
check("menu buttons: 1–4 + Encerrar", option_texts() == AT.EVENT_LABELS + [AT.T_END]
      and [e[1] for e in option_buttons()][:4] == [f"{i} — {l}" for i, l in enumerate(AT.EVENT_LABELS, 1)])


def reach(how):
    bad = []
    for i, label in enumerate(AT.EVENT_LABELS, 1):
        at_state("AT11", AT5D)
        if how == "button":
            click(label)
        else:
            run({"number": str(i), "name": ["curto-circuito", "perda de linha", "desligamento de unidade geradora",
                                            "rejeição de carga"][i - 1]}[how])
        if not (data().get("event_pending") == label and option_texts() == [AT.T_EVENT_DONE]
                and f"**{label}.**" in reply()):
            bad.append((how, label))
    return bad


for how in ("button", "number", "name"):
    bad = reach(how)
    check(f"all four options reachable by {how}", not bad, bad)
at_state("ATS5", SMALL); run("RMGR")
check("by code and at ATS5 too", data().get("event_pending") == "Desligamento de unidade geradora")
at_state("AT11", AT5D); run("explosão")
check("unknown type → re-asks, nothing stored", step() == "AT11" and not data().get("event_pending")
      and not data().get("events"))

at_state("AT11", AT5D)
click("Curto-circuito")
rem = reply()
check("reminder: when it starts, where, when it ends; DEVT + F5; no DEVT line generated",
      "quando** ele começa" in rem and "quando** termina" in rem and "onde** é o defeito" in rem
      and "F5" in rem and "```" not in rem)
click(AT.T_EVENT_DONE)
c1 = data().get("events") == [{"type": "Curto-circuito", "note": ""}]
click(AT.T_ADD_EVENT)
c2 = option_texts() == AT.EVENT_LABELS + [AT.T_END]
run("4"); run("barra 500, 30% em t = 2 s")
c3 = data()["events"][-1] == {"type": "Rejeição de carga", "note": "barra 500, 30% em t = 2 s"}
check("events stored as dicts {type, note} ('Evento inserido' → note '', a description → note)", c1 and c2 and c3,
      data().get("events"))
check("panel counts the events", "Eventos: **2**" in panel())
click(AT.T_END)
summary = reply()
check("closing summary lists the events by type",
      step() == "IDLE" and "  - Curto-circuito\n" in summary
      and "  - Rejeição de carga — barra 500, 30% em t = 2 s" in summary, summary)

at_state("AT11", dict(AT5D, events=["curto antigo v6.6.0"]))
check("v6.6.0 string events: panel renders", "Eventos: **1**" in panel())
run("encerrar")
check("…and the summary renders them", "  - curto antigo v6.6.0" in reply())
mixed = AT.closing_summary({"events": ["antigo", {"type": "Curto-circuito", "note": "x"}]})
check("mixed old/new events render as text", "  - antigo" in mixed and "  - Curto-circuito — x" in mixed)
fresh(chain(), step="AT11", data=dict(AT5D, sim_type="ANATEM", events=[{"type": "Curto-circuito", "note": ""}]),
      status="active")
run()
SCRIPT = H.SCRIPT
SCRIPT["press"] = {"⏸️ Pausar simulação"}; run(); SCRIPT["press"] = set()
ps = svc.load_paused_state("userA")
check("pause persists dict events (JSON)", ps and ps["sim_data"]["events"] == [{"type": "Curto-circuito", "note": ""}])

LAYOUT_RE = re.compile(r"\b(?:APCB|APCC|APCL|ABCI|RMGR|MDLP|MDLQ|DEVT)\b[ \t]+\d|colunas?\s+\d|\(\s*\d+\s*-\s*\d+\s*\)",
                       re.I)
bad = [t[:80] for t in all_texts() if LAYOUT_RE.search(t)]
check("no text contains a DEVT line or a column layout", not bad, bad)
check("glossary: event codes added, pending review",
      {"APCB", "APCC", "APCL", "ABCI", "RMGR", "MDLP", "MDLQ"} <= set(GLOSSARY_ANATEM))
check("no code block in any guide message", not any("```" in t for t in all_texts()))


# ═════════════════════════════════════════════════════════════════════════════
section("6. Version, markers")
# ═════════════════════════════════════════════════════════════════════════════
check("APP_VERSION v6.6.1 with DRAFT PT-BR notes (5 novidades, 5 o que testar)",
      APP_VERSION == "v6.6.1" and "DRAFT" in RELEASE_NOTES["v6.6.1"]["status"]
      and len(RELEASE_NOTES["v6.6.1"]["novidades"]) == 5 and len(RELEASE_NOTES["v6.6.1"]["o_que_testar"]) == 5)
src = open("agents/anatem_flow.py", encoding="utf-8").read()
check("new text blocks marked PENDING REVIEW (≥ 30 markers in anatem_flow.py)",
      src.count("PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)") >= 30)
for name in ("STB_CODES", "_EQUIP_BRANCH_Q", "EVENT_TYPES", "ATS2_EXAMPLE_GUIDE", "_AT8_MAIN", "RUN_SHORT",
             "EVENT_CODES_NOTE", "_ATS2_FILES_Q", "def _event_reminder", "def apply_equipment_edit"):
    i = src.index(name if name.startswith("def ") else f"\n{name} =")
    head = src[max(0, i - 400):i]
    check(f"{name.replace('def ', '')} is marked PENDING REVIEW", "PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)" in head)


# ═════════════════════════════════════════════════════════════════════════════
section("7. The tests are not trivial: ULOG/DARQ back, F5 removed, conventional broken")
# ═════════════════════════════════════════════════════════════════════════════
saved = (AT._at5_main, AT._AT8_MAIN, AT.parse_equipment_choice)
AT._at5_main = lambda d: saved[0](d).replace("No cartão **DARQ**, localize", "No bloco **ULOG/DARQ**, localize")
check("re-introduced 'ULOG/DARQ' in AT5 → the P3 tests FAIL",
      not t_no_ulog_darq() and not t_at5_word() and t_same_sentence())
AT._at5_main = saved[0]
AT._AT8_MAIN = saved[1].replace("**F5**", "a tecla de atalho")
check("removed 'F5' from AT8 → the P4 test FAILS", not t_run_texts()[0])
AT._AT8_MAIN = saved[1]
AT.parse_equipment_choice = lambda text, data=None: "include" if saved[2](text, data) == "none" else saved[2](text, data)
check("broken conventional branch → the P2 tests FAIL", not t_conventional() and not t_conventional("ATS3", SMALL, "ATS4"))
AT.parse_equipment_choice = saved[2]
check("restored: the same tests pass again",
      t_no_ulog_darq() and t_at5_word() and not t_same_sentence() and t_run_texts()[0] and t_conventional()
      and t_conventional("ATS3", SMALL, "ATS4"))

H.finish()
