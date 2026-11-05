"""
v6.6.0 — ANATEM guided flow (guide only), keyword router for ANAREDE/ANATEM,
"ANAREDE ou ANATEM?" question, sidebar start buttons and the ANAREDE → ANATEM
handoff. Real app (runpy), real auth_service SQL on sqlite, real PWF generators;
only the LLM chain is faked (shared harness).

Run from repo root:  python3 test_anatem_v660.py
"""
import copy
import os
import re
import runpy
import subprocess
import sys
import tempfile

import _harness_v650 as H
from _harness_v650 import (ss, EV, SCRIPT, svc, check, section, fresh, run, events,
                           last_assistant, assistants, sim_state, rows, StreamChain, scores)
from agents import anatem_flow as AT
from agents import structured_input as SI
from agents import session_analysis as SA
from config.glossary import ALL_TERMS, GLOSSARY_ANATEM, find_terms
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


# ── helpers ───────────────────────────────────────────────────────────────────

def chain():
    return StreamChain(["Resposta livre."], scores(("manual.pdf", 0.8)))


def start(step="IDLE", data=None, status=None, ch=None):
    fresh(ch or chain(), step=step, data=data, status=status)
    run()


def at_state(step, data=None, extra_status="active", ch=None):
    """State at an ANATEM step with its guide message as the latest one (controls render)."""
    d = {"sim_type": "ANATEM"}
    d.update(data or {})
    fresh(ch or chain(), step=step, data=d, status=extra_status)
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


def click(text):
    """Click the option button whose canonical text (or label) is `text`."""
    b = next(e for e in option_buttons() if e[4][0][0] == text or e[1] == text)
    b[3](*b[4])
    run()


def button(key_prefix):
    return next(e for e in events("button") if e[2] and e[2].startswith(key_prefix))


def press_key(key_prefix):
    b = button(key_prefix)
    b[3](*b[4])
    run()


def submit(form_id, values):
    sub = next(e for e in events("submit") if e[4][0]["id"] == form_id)
    spec, base, sel = sub[4]
    for f in SI.form_fields(spec, sel):
        ss[f"fld_{base}_{f['key']}"] = values.get(f["key"], "")
    sub[3](*sub[4])
    run()


def last_user_row():
    return rows("SELECT * FROM chat_logs WHERE role='user' ORDER BY id DESC LIMIT 1")[0]


def llm_called(ch):
    return ch.retrieve_calls > 0 or ch.generate_calls > 0


def anatem_messages():
    return [m for m in assistants() if m.get("sim_type") == "ANATEM"]


# ═════════════════════════════════════════════════════════════════════════════
section("1. Main flow, SIN ONS: AT1 → AT11 with buttons/forms, then typed")
# ═════════════════════════════════════════════════════════════════════════════
def main_flow_buttons():
    ch = chain()
    start(ch=ch)
    press_key("start_anatem")                                   # sidebar button
    seen = [step()]
    srcs = [last_user_row()["input_source"]]
    click(AT.T_ONS); seen.append(step())
    submit("at_case", {"sav": "caso_estudo.sav", "case": "5"}); seen.append(step())
    srcs.append(last_user_row()["input_source"])
    click(AT.T_RAN_OK); seen.append(step())
    submit("at_dmaq", {"dmaq": "dmaq_anat0.dma"}); seen.append(step())
    click(AT.T_CONFIGURED); seen.append(step())
    click(AT.T_INCLUDE_EQUIP); seen.append(step())              # v6.6.1: equipment branch first
    click(AT.T_YES); seen.append(step())
    click(AT.T_MODELS_DONE); seen.append(step())
    click(AT.T_READY); seen.append(step())
    click(AT.T_RUN_CDU_ERR); seen.append(step())
    submit("at_cdu", {"cdu": "1042"}); seen.append(step())
    click(AT.T_IN_DMAQ); seen.append(step())
    click(AT.T_GOV); seen.append(step())
    click(AT.T_RAN_OK); seen.append(step())
    click(AT.T_FLAT); seen.append(step())
    click("Curto-circuito"); seen.append(step())                # v6.6.1: event menu
    run("trifásico na barra 1001 em t = 1 s"); seen.append(step())
    click(AT.T_ADD_EVENT)
    click("Perda de linha de transmissão"); seen.append(step())
    run("LT 1001-1002 aberta no fim da linha"); seen.append(step())
    final_data = copy.deepcopy(data())
    srcs.append(last_user_row()["input_source"])
    click(AT.T_END); seen.append(step())
    return ch, seen, srcs, final_data


ch, seen, srcs, fd = main_flow_buttons()
check("sidebar button starts the ANATEM flow at AT1 (logged as button)", seen[0] == "AT1" and srcs[0] == "button")
check("buttons/forms walk AT1→AT2→AT3→AT4→AT5→AT6(Incluir, Sim, models)→AT7→AT8→AT9→AT8→AT10→AT11",
      seen == ["AT1", "AT2", "AT3", "AT4", "AT5", "AT6", "AT6", "AT6", "AT7", "AT8", "AT9", "AT9", "AT9", "AT8",
               "AT10", "AT11", "AT11", "AT11", "AT11", "AT11", "IDLE"], seen)
check("form answers logged with input_source='form'", srcs[1] == "form" and srcs[2] == "typed", srcs)
check("captured data: base, .sav, case, DMAQ, equipment, events",
      fd.get("base") == "ONS" and fd.get("sav_name") == "caso_estudo.sav" and fd.get("case_number") == "5"
      and fd.get("dmaq_name") == "dmaq_anat0.dma" and fd.get("equip") == "incluidos"
      and fd.get("equipment") == "include"
      and fd.get("events") == [{"type": "Curto-circuito", "note": "trifásico na barra 1001 em t = 1 s"},
                               {"type": "Perda de linha de transmissão", "note": "LT 1001-1002 aberta no fim da linha"}], fd)
summary = reply()
check("closing message: simulation recorded + study summary + continuation options",
      "Simulação registrada" in summary and "caso_estudo.sav" in summary and "dmaq_anat0.dma" in summary
      and "SIN — base ONS" in summary and "Perda de linha de transmissão" in summary and "Iniciar simulação ANATEM" in summary
      and "perguntas livres" in summary, summary)
check("after closing: IDLE, no simulation active", sim_state()["sim_status"] is None and step() == "IDLE")
check("the LLM never ran during the guided flow", not llm_called(ch))
check("no ANATEM file content generated (no code blocks, no .pwf download)",
      not any("```" in m["content"] for m in anatem_messages()) and not events("download"))
check("chat_logs carry sim_type ANATEM and AT* steps",
      {r["sim_step"] for r in rows("SELECT sim_step FROM chat_logs WHERE sim_type='ANATEM'")}
      >= {"AT1", "AT2", "AT3", "AT9", "AT11"})


def main_flow_typed():
    ch = chain()
    start(ch=ch)
    seen = []
    for t in ["quero passar meu caso para o anatem", "1", "caso_estudo.sav, caso 5", "rodou sem erros",
              "dmaq_anat0.dma", "configurado", "já incluídos", "pronto", "deu erro no CDU",
              "CDU 1042", "está no DMAQ", "regulador de tensão (AVR)", "sem erros", "constante",
              "curto-circuito na barra 1001", "evento inserido", "encerrar"]:
        run(t)
        seen.append(step())
    return ch, seen


ch2, seen2 = main_flow_typed()
check("typed answers reach the same steps as the buttons",
      seen2 == ["AT1", "AT2", "AT3", "AT4", "AT5", "AT6", "AT7", "AT8", "AT9", "AT9", "AT9", "AT8",
                "AT10", "AT11", "AT11", "AT11", "IDLE"], seen2)
check("typed flow: LLM never ran", not llm_called(ch2))


# ═════════════════════════════════════════════════════════════════════════════
section("2. EPE option and the small-case flow (option 3, no ANAT0)")
# ═════════════════════════════════════════════════════════════════════════════
start()
run("iniciar simulação dinâmica"); run("SIN EPE"); run("estudo.sav caso 12")
check("EPE: base EPE, ANAT0 step points to the EPE folder",
      data().get("base") == "EPE" and step() == "AT3" and "base da EPE" in reply(), reply()[:300])

start()
run("quero simular no anatem")
click(AT.T_SMALL)
s1 = step()
run("rede.sav, caso 1, barras 10, 20")
s2, ats2_reply = step(), reply()
click(AT.T_INCLUDE_EQUIP); click(AT.T_CONFIRM_MODELS); s3 = step()
click(AT.T_ERROR); s4 = step()
run("1042"); run(AT.T_NOT_DMAQ); s5 = step()
click(AT.T_VARYING); click(AT.T_SMALL_OSC); s6 = step()
run("curto na barra 10"); run("encerrar"); s7 = step()
check("option 3 → ATS2 → ATS3 → ATS4 → (CDU) → ATS4 → ATS5 → end",
      (s1, s2, s3, s4, s5, s6, s7) == ("ATS2", "ATS3", "ATS4", "AT9", "ATS4", "ATS5", "IDLE"),
      (s1, s2, s3, s4, s5, s6, s7))
check("ATS2 parsed .sav, case and generator buses; .stb instructions use them",
      "rede.sav" in ats2_reply and "**1**" in ats2_reply and "10, 20" in ats2_reply)
small_msgs = [m for m in anatem_messages() if (m.get("sim_step_after") or "").startswith("ATS")
              or m.get("sim_step_before", "").startswith("ATS")]
check("small-case path never visits AT2–AT8 nor mentions ANAT0 after AT1",
      not any(r["sim_step"] in ("AT2", "AT3", "AT4") for r in rows(
          "SELECT sim_step FROM chat_logs WHERE session_id='sessA' AND sim_type='ANATEM' AND id > "
          "(SELECT MAX(id) FROM chat_logs WHERE message LIKE 'quero simular no anatem')"))
      and not any("ANAT0" in m["content"] for m in small_msgs[1:]))

start()
run("quero simular no anatem"); run("3"); run("rede.sav"); a = step(); run("caso 2"); b = step()
run("barras 5"); c = step()
check("ATS2 asks for missing pieces one at a time", (a, b, c) == ("ATS2", "ATS2", "ATS3")
      and data()["gen_buses"] == ["5"])


# ═════════════════════════════════════════════════════════════════════════════
section("3. ANAT0 error branch")
# ═════════════════════════════════════════════════════════════════════════════
at_state("AT3", {"base": "ONS", "sav_name": "x.sav", "case_number": "1"})
click(AT.T_RAN_ERR)
err = reply()
check("'Deu erro' → troubleshooting, stays at AT3",
      step() == "AT3" and "violação de limite de potência ativa ou reativa" in err
      and "salve o **.sav** novamente" in err.replace("Salve", "salve") and "Rodou sem erros" not in err[:20])
check("troubleshooting asks again 'rodou sem erros?' with the same buttons",
      "rodou sem erros?" in err.lower() and {e[4][0][0] for e in option_buttons()} == {AT.T_RAN_OK, AT.T_RAN_ERR})
click(AT.T_RAN_OK)
check("'Rodou sem erros' after the error advances to AT4", step() == "AT4" and "anat0_error" not in data())


# ═════════════════════════════════════════════════════════════════════════════
section("4. AT9 — CDU parsing and the three branches (each back at AT8)")
# ═════════════════════════════════════════════════════════════════════════════
check("'CDU 1042' and '1042' parse; '0.1042' and '0,1042' do not",
      AT.parse_cdu("CDU 1042") == "1042" and AT.parse_cdu("1042") == "1042"
      and AT.parse_cdu("0.1042") is None and AT.parse_cdu("cdu 0,1042") is None)

AT9 = {"base": "ONS", "sav_name": "x.sav", "case_number": "1", "dmaq_name": "d.dma", "cdu_return": "AT8"}


def cdu_branch(where, ctrl=None):
    at_state("AT9", AT9)
    run("CDU 1042")
    s_num = step() == "AT9" and data()["cdu"]["number"] == "1042"
    click(where)
    if ctrl:
        s_mid = step() == "AT9" and "Ctrl+F" in reply() and "**d.dma**" in reply()
        click(ctrl)
    else:
        s_mid = True
    return s_num and s_mid, step(), reply()


def t_gov_branch():
    ok, st_, txt = cdu_branch(AT.T_IN_DMAQ, AT.T_GOV)
    return (ok and st_ == "AT8" and "potência ativa" in txt and "reduza levemente o **Pg**" in txt
            and "Passo D" in txt and "ANAT0" in txt and "Rodou sem erros?" in txt)


def t_avr_branch():
    ok, st_, txt = cdu_branch(AT.T_IN_DMAQ, AT.T_AVR)
    return (ok and st_ == "AT8" and "tensão/reativo" in txt and "1,0 pu" in txt
            and "taps ou compensadores" in txt and "Passo D" in txt)


check("GOV branch: Passos A–C, active-power advice + Passo D, back at AT8", t_gov_branch())
check("AVR/PSS branch: voltage/reactive advice + Passo D, back at AT8", t_avr_branch())
ok, st_, txt = cdu_branch(AT.T_NOT_DMAQ)
check("not-in-DMAQ branch: DFNT for wind/PV, DCNV/DCNE for DC links, back at AT8",
      ok and st_ == "AT8" and "DFNT" in txt and "DCNV" in txt and "DCNE" in txt and "EOL_NE.dat" in txt)
at_state("AT8", AT9)
click(AT.T_RUN_CDU_ERR)
check("entering AT9 always shows the 'CDUs validados, ajuste do ponto de operação' note",
      step() == "AT9" and "não devem ser" in reply() and "ajuste fino do ponto de operação" in reply())
run("o log não mostra")
check("unparseable CDU answer re-asks (state unchanged)", step() == "AT9" and not data().get("cdu", {}).get("number"))


# ═════════════════════════════════════════════════════════════════════════════
section("5. AT10 — flat / varying ≤ 0.001 pu / varying larger")
# ═════════════════════════════════════════════════════════════════════════════
at_state("AT10", AT9)
check("AT10 tells to look at the Y-axis scale first", "escala do eixo Y" in last_assistant()["content"])
click(AT.T_FLAT)
check("flat → AT11", step() == "AT11")
at_state("AT10", AT9)
click(AT.T_VARYING)
check("varying → asks the oscillation size (buttons)", step() == "AT10" and data().get("osc_pending")
      and {e[4][0][0] for e in option_buttons()} == {AT.T_SMALL_OSC, AT.T_LARGE_OSC})
click(AT.T_SMALL_OSC)
check("≤ 0.001 pu → numerical precision, AT11", step() == "AT11" and "precisão numérica" in reply())
at_state("AT10", AT9)
click(AT.T_VARYING); click(AT.T_LARGE_OSC)
check("larger → not numerical, AT9 path (CDU number asked)", step() == "AT9" and "não** é efeito numérico" in reply()
      and data().get("cdu_return") == "AT8")
run("CDU 77"); click(AT.T_NOT_DMAQ)
check("…then back at AT8", step() == "AT8")


# ═════════════════════════════════════════════════════════════════════════════
section("6. Router: ANATEM triggers, free questions, ambiguity, precedence")
# ═════════════════════════════════════════════════════════════════════════════
def routes_to(text, st0="IDLE"):
    ch = chain()
    start(ch=ch)
    run(text)
    return step(), (data() or {}).get("sim_type"), llm_called(ch)


def t_trigger(phrase):
    s, t, llm = routes_to(phrase)
    return s == "AT1" and t == "ANATEM" and not llm


# The spec's phrases, copied here on purpose: removing one from the app must fail this test.
SPEC_TRIGGERS = [
    "quero passar meu caso para o anatem", "passar meu caso para o anatem", "iniciar simulação dinâmica",
    "iniciar simulacao dinamica", "quero iniciar uma simulação no anatem", "simulação no anatem",
    "quero simular no anatem", "rodar no anatem", "simulação dinâmica", "simulação de estabilidade",
    "estudo de estabilidade", "estabilidade eletromecânica", "análise transitória", "rodar o anat0",
    "usar o anat0", "preciso do anat0", "migrar para o anatem", "handoff anatem",
]
check("_ANATEM_INTENT_TRIGGERS is exactly the spec list", AT._ANATEM_INTENT_TRIGGERS == SPEC_TRIGGERS)
bad = [p for p in SPEC_TRIGGERS if not t_trigger(p)]
check(f"each of the {len(SPEC_TRIGGERS)} trigger phrases starts the ANATEM flow", not bad, bad)
bad = [p for p in ["QUERO SIMULAR NO ANATEM", "simulacao dinamica", "Estabilidade Eletromecanica",
                   "analise transitoria"] if not t_trigger(p)]
check("triggers are accent- and case-insensitive", not bad, bad)
bad = [p for p in ["quero rodar o anatem", "preciso usar o ANAT0", "vamos fazer a análise dinâmica",
                   "quero simular o transitório", "começar no anatem"] if not t_trigger(p)]
check("single-word cues + a verb of intent start the flow", not bad, bad)
for q in ["O que é o ANATEM?", "Como funciona o ANAT0?", "anatem", "estabilidade",
          "o ANATEM usa o mesmo caso do ANAREDE"]:
    s, t, llm = routes_to(q)
    check(f"'{q}' stays a free question (LLM, no state change)", s == "IDLE" and t is None and llm, (s, t, llm))
for q in ["quero fazer uma simulação", "simulação dinâmica de um BESS",
          "quero passar meu caso do anarede para o anatem", "quero simular no ANAREDE e depois no ANATEM"]:
    s, t, llm = routes_to(q)
    check(f"'{q}' → IDLE_PROGRAM_CHOICE", s == "IDLE_PROGRAM_CHOICE" and not llm
          and AT.PROGRAM_CHOICE_QUESTION in reply(), (s, t))
for q in ["quero fazer uma simulação dinâmica no anarede", "quero fazer uma simulação no anarede"]:
    s, t, llm = routes_to(q)
    check(f"explicit ANAREDE wins: '{q}' → STEP1", s == "STEP1" and t == "BESS", (s, t))

# Every existing ANAREDE trigger, the network triggers and the routing-suite messages.
start()
_env = run()
SIM_TRIGGERS, NET_TRIGGERS = _env["_SIMULATION_INTENT_TRIGGERS"], _env["_NETWORK_INTENT_TRIGGERS"]
bad = [p for p in SIM_TRIGGERS if routes_to(p)[:2] not in (("STEP1", "BESS"), ("STEP1", "STATCOM"))]
check(f"all {len(SIM_TRIGGERS)} existing ANAREDE triggers still start the ANAREDE flow (STEP1)", not bad, bad)
bad = [p for p in NET_TRIGGERS if routes_to(p)[:2] != ("NET1_SETUP", "NETWORK")]
check(f"all {len(NET_TRIGGERS)} network triggers still start NET1", not bad, bad)
ROUTING_V62 = {
    "quero simular um BESS no SIN": "STEP1", "quero inserir um BESS na rede": "STEP1",
    "preciso de uma simulação": "STEP1", "iniciar simulação": "STEP1",
    "gostaria de fazer um estudo": "STEP1", "quero modelar uma bess": "STEP1", "modelar bess": "STEP1",
    ("Tenho uma linha de transmissão de 230 kV, 180 km, com R = 0,0257 ohms/km, X = 0,2995 ohms/km "
     "e B = 5,4542 μS/km. Como eu integro isso no ANAREDE?"): "IDLE_LT_CONFIRM",
    "Tenho uma LT de 230 kV com R=0.0257 ohms/km, X=0.2995 ohms/km, B=5.4542 μS/km, 180 km": "IDLE_LT_CONFIRM",
    ("Preciso modelar uma LT: tensão 500 kV, comprimento 250 km, R = 0,05 ohm/km, X = 0,35 ohm/km, "
     "B = 3,2 μS/km. Quero inserir no DLIN do ANAREDE."): "IDLE_LT_CONFIRM",
    ("Quero simular uma BESS. Tenho uma LT de 230 kV com R=0.0257 ohms/km, X=0.2995 ohms/km, "
     "B=5.4542 μS/km, 180 km."): "STEP1",
    "Como modelar uma BESS no ANAREDE?": "IDLE", "O que é o DLIN?": "IDLE",
    "como rodar o fluxo de potência com ctrl+r?": "IDLE", "onde fica o SAV do PAR/PEL?": "IDLE",
}
bad = [(m[:40], routes_to(m)[0], exp) for m, exp in ROUTING_V62.items() if routes_to(m)[0] != exp]
check("routing-suite / ANAREDE-only messages keep today's routing", not bad, bad)
r = subprocess.run([sys.executable, "test_routing_v62.py"], capture_output=True, text=True)
check("test_routing_v62.py passes unchanged (57/57)", r.returncode == 0 and "57/57 checks passed" in r.stdout,
      r.stdout[-300:])


# Differential check: the v6.5.1 app (git) and this app give the same state for
# ANAREDE inputs, at IDLE and mid-flow.
def _baseline_app():
    try:
        src = subprocess.run(["git", "show", "9e6dc29:app.py"], capture_output=True, text=True, check=True).stdout
    except Exception:
        return None
    path = os.path.join(tempfile.mkdtemp(prefix="v651_"), "app_v651.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(src)
    return path


def _state_with(path, prompt, step_="IDLE", data_=None, status=None):
    ch = chain()
    fresh(ch, step=step_, data=data_, status=status)
    for p in (None, prompt):
        EV.clear()
        SCRIPT["prompt"] = p
        try:
            runpy.run_path(path, run_name="app_under_test")
        except H.StopRun:
            pass
        finally:
            SCRIPT["prompt"] = None
    st_ = sim_state()
    return (st_["sim_step"], st_["sim_status"], st_["sim_data"], llm_called(ch))


BASE = _baseline_app()
DIFF_CASES = ([("IDLE", None, None, m) for m in list(SIM_TRIGGERS) + list(NET_TRIGGERS) + list(ROUTING_V62)]
              + [("STEP1", {"sim_type": "BESS"}, "active", m) for m in ("1", "2", "3", "ONS", "quero simular")]
              + [("STEP3", dict(ONS, scenario=None), "active", "4"),
                 ("STEP4", ONS, "active", "verde, convergiu"), ("STEP6", ONS, "active", "opção A"),
                 ("STEP7", ONS, "active", "1001"), ("STEP7", dict(ONS, bess_bus="1001"), "active", "1"),
                 ("STEP9", BESS_FULL, "active", "pronto"), ("STEP10", BESS_FULL, "active", "convergiu"),
                 ("STEP12", BESS_FULL, "active", "encerrar"), ("STEP12", BESS_FULL, "active", "outro cenário"),
                 ("STEP12", BESS_FULL, "active", "2029"), ("STEP7", ONS, "active", "O que é uma barra PV?"),
                 ("NET7_RESULTS", {"sim_type": "NETWORK", "network": NET, "net7_color": "green"}, "active", "n-1"),
                 ("IDLE_LT_CONFIRM", {"pending_lt": {"voltage_kv": 230.0}, "pending_question": "LT"}, None, "sim")])
if BASE:
    diffs = []
    for st0, d0, s0, msg in DIFF_CASES:
        old = _state_with(BASE, msg, st0, d0, s0)
        new = _state_with("app.py", msg, st0, d0, s0)
        if old != new:
            diffs.append((st0, msg[:40], old[:2], new[:2]))
    check(f"differential vs v6.5.1 app.py: {len(DIFF_CASES)} ANAREDE inputs give identical state", not diffs, diffs)
else:
    print("  (differential check skipped: git history not available)")


# ═════════════════════════════════════════════════════════════════════════════
section("7. IDLE_PROGRAM_CHOICE")
# ═════════════════════════════════════════════════════════════════════════════
def to_choice(text="quero fazer uma simulação", ch=None):
    start(ch=ch)
    run(text)
    assert step() == "IDLE_PROGRAM_CHOICE", step()


to_choice()
check("two large buttons (ANAREDE / ANATEM)",
      [e[4][0][0] for e in option_buttons()] == ["ANAREDE", "ANATEM"]
      and all(e[6].get("use_container_width") for e in option_buttons()))
click("ANAREDE")
check("ANAREDE button → ANAREDE intro (STEP1, BESS)", step() == "STEP1" and data()["sim_type"] == "BESS"
      and last_user_row()["input_source"] == "button")
to_choice(); click("ANATEM")
check("ANATEM button → ANATEM intro (AT1)", step() == "AT1" and "Antes de começar" in reply())
for txt, exp in [("anarede", "STEP1"), ("1", "STEP1"), ("anatem", "AT1"), ("2", "AT1")]:
    to_choice(); run(txt)
    check(f"text fallback '{txt}' → {exp}", step() == exp)
to_choice("simulação dinâmica de um STATCOM"); run("anarede")
check("ANAREDE choice keeps the STATCOM of the original request", data().get("sim_type") == "STATCOM")
ch = chain()
to_choice(ch=ch); run("O que é o ANATEM?")
check("free question → LLM, state kept (IDLE_PROGRAM_CHOICE)", llm_called(ch) and step() == "IDLE_PROGRAM_CHOICE")
run("2")
check("…and the choice still works afterwards", step() == "AT1")
to_choice(); run("banana")
check("unrecognised answer re-asks", step() == "IDLE_PROGRAM_CHOICE" and "Não identifiquei o programa" in reply())
to_choice(); run("cancelar")
check("'cancelar' → IDLE, no simulation", step() == "IDLE" and sim_state()["sim_status"] is None)


# ═════════════════════════════════════════════════════════════════════════════
section("8. Sidebar start buttons")
# ═════════════════════════════════════════════════════════════════════════════
start()
check("both buttons always visible, full width, bold label, above the study panel",
      button("start_anarede")[1] == "**⚡ Iniciar simulação ANAREDE**"
      and button("start_anatem")[1] == "**🌀 Iniciar simulação ANATEM**"
      and button("start_anarede")[6].get("use_container_width") and button("start_anatem")[6].get("use_container_width"))
press_key("start_anarede")
check("no simulation: ANAREDE button → current ANAREDE intro (STEP1), logged as button",
      step() == "STEP1" and "Vou te guiar pelo processo de simulação" in reply()
      and last_user_row()["input_source"] == "button" and last_user_row()["message"] == "Iniciar simulação ANAREDE")
start(); run("quero fazer uma simulação"); press_key("start_anatem")
check("from the program question (no simulation) → starts directly", step() == "AT1")

fresh(chain(), step="STEP7", data=copy.deepcopy(ONS), status="active"); run()
before = sim_state()
press_key("start_anatem")
check("active simulation: first click only asks for confirmation (state unchanged)",
      sim_state() == before and ss.get("_start_confirm") == "ANATEM"
      and any(e[0] == "warning" and "Encerrar e iniciar uma nova?" in e[1] for e in EV))
press_key("start_confirm_no")
check("'Cancelar' keeps the simulation", sim_state() == before and "_start_confirm" not in ss)
press_key("start_anatem"); press_key("start_confirm_yes")
notices = [m for m in ss.messages if m.get("notice") and m["content"] == "Simulação encerrada."]
check("'Sim, iniciar nova' closes the old one (logged notice) and starts ANATEM",
      step() == "AT1" and data() == {"sim_type": "ANATEM"} and notices
      and rows("SELECT 1 FROM chat_logs WHERE message='Simulação encerrada.' AND role='assistant'"))

fresh(chain(), step="AT5", data={"sim_type": "ANATEM", "base": "ONS", "sav_name": "a.sav"}, status="paused")
svc.save_paused_state("sessA", "AT5", ss["sim_data"])
run()
press_key("start_anarede")
check("paused simulation: confirmation asked too", ss.get("_start_confirm") == "ANAREDE" and step() == "AT5")
press_key("start_confirm_yes")
check("confirm: paused state cleared in the DB, ANAREDE started",
      step() == "STEP1" and rows("SELECT paused_state FROM sessions WHERE id='sessA'")[0]["paused_state"] is None)


# ═════════════════════════════════════════════════════════════════════════════
section("9. Handoff ANAREDE → ANATEM")
# ═════════════════════════════════════════════════════════════════════════════
def handoff_from(step_, d):
    fresh(chain(), step=step_, data=copy.deepcopy(d), status="active")
    env = run()
    env["_append_system_assistant_message"](env["_current_step_question"]() or "Próximos passos.")
    run()
    b = [e for e in events("button") if e[2] and e[2].startswith("handoff_")]
    if b:
        b[0][3](*b[0][4])
        run()
    return bool(b)


def t_handoff_bess():
    has_btn = handoff_from("STEP12", BESS_FULL)
    h = data().get("handoff") or {}
    return (has_btn and step() == "AT1" and data()["sim_type"] == "ANATEM"
            and h == {"sim_type": "BESS", "sav_name": None, "case_number": None, "equipment_type": "BESS",
                      "equipment_bus": "9001", "mva": "100", "year": 2028,
                      "scenario": "Inverno Máxima Diurna", "base": "ONS"}
            and data().get("base_suggested") == "ONS" and "Vamos manter a base **ONS**" in reply()
            and "concluído" in reply() and last_user_row()["input_source"] == "button")


check("BESS (STEP12): button → ANAREDE closed, ANATEM AT1 with copied data, base ONS pre-selected",
      t_handoff_bess(), data())
check("…the ANAREDE study is logged as completed (user row at STEP12/BESS, reply at AT1/ANATEM)",
      rows("SELECT sim_step, sim_type FROM chat_logs WHERE role='user' ORDER BY id DESC LIMIT 1")[0]
      == {"sim_step": "STEP12", "sim_type": "BESS"}
      and rows("SELECT sim_step, sim_type FROM chat_logs WHERE role='assistant' ORDER BY id DESC LIMIT 1")[0]
      == {"sim_step": "AT1", "sim_type": "ANATEM"})
run("sim")
check("AT1 'sim' keeps ONS; AT2 asks normally (no .sav was captured — nothing invented)",
      step() == "AT2" and not data().get("at2_confirm") and "sav_name" not in data()
      and "Qual o nome do arquivo **.sav**" in reply())
for t in ["c.sav, caso 3", "rodou sem erros", "d.dma", "configurado"]:
    run(t)
check("AT6 mentions the BESS bus from the ANAREDE study", step() == "AT6" and "BESS** na barra **9001**" in reply())

two = dict(BESS_FULL, bess_extra=[{"bess_bus": "1002", "bess_mode": "PQ", "bess_mva": "50", "bess_p_mw": "10",
                                   "bess_bus_number": "9002"}])
handoff_from("STEP12", two)
check("several BESS: every new bus and rating carried", data()["handoff"]["equipment_bus"] == "9002, 9001"
      and data()["handoff"]["mva"] == "50, 100")

handoff_from("STEP12", {"sim_type": "STATCOM", "db": "EPE", "years": [2030], "year": 2030,
                        "scenario": "Máxima Diurna Seco", "statcom_bus": "1500",
                        "statcom_q_min": -100.0, "statcom_q_max": 100.0})
h = data().get("handoff") or {}
check("STATCOM: base EPE pre-selected, STATCOM bus carried, no MVA invented",
      step() == "AT1" and data().get("base_suggested") == "EPE" and h.get("equipment_type") == "STATCOM"
      and h.get("equipment_bus") == "1500" and h.get("mva") is None)

net_green = {"sim_type": "NETWORK", "network": copy.deepcopy(NET), "net7_color": "green"}
handoff_from("NET7_RESULTS", net_green)
check("NETWORK (NET7 converged): button offered → base 'caso pequeno' pre-selected",
      step() == "AT1" and data().get("base_suggested") == "PEQUENO" and data()["handoff"]["base"] == "NETWORK")
run("sim")
check("…keeping it goes to the small-case path (ANAT0 skipped)", step() == "ATS2")
fresh(chain(), step="NET7_RESULTS", data=copy.deepcopy(net_green), status="active"); run(); run("anatem")
check("text alternative 'anatem' at NET7 works too", step() == "AT1")
has_btn = handoff_from("NET7_RESULTS", dict(net_green, net7_color="red"))
fresh(chain(), step="NET7_RESULTS", data=dict(copy.deepcopy(net_green), net7_color="red"), status="active")
run(); run("anatem")
check("NET7 not converged: no button, and 'anatem' explains the case must converge first",
      not has_btn and step() == "NET7_RESULTS" and "convergido" in reply())


def t_handoff_no_data():
    handoff_from("STEP12", {"sim_type": "BESS"})
    h = data().get("handoff") or {}
    return (step() == "AT1" and h.get("sim_type") == "BESS"
            and all(h.get(k) is None for k in ("sav_name", "case_number", "equipment_bus", "mva", "year",
                                               "scenario", "base"))
            and "base_suggested" not in data() and "Qual caso você vai simular?" in reply())


check("no data captured: nothing pre-filled, AT1 asked normally", t_handoff_no_data(), data())
run("1")
check("no data captured: AT2 asks for the .sav and case (no confirmation)",
      step() == "AT2" and not data().get("at2_confirm") and "Qual o nome do arquivo **.sav**" in reply())
check("build_handoff never invents values (unit)",
      AT.build_handoff({}) == {"sim_type": "BESS", "sav_name": None, "case_number": None,
                               "equipment_type": "BESS", "equipment_bus": None, "mva": None,
                               "year": None, "scenario": None, "base": None}
      and AT.build_handoff({"sim_type": "NETWORK"})["equipment_type"] is None)
d0 = AT.initial_data({"sim_type": "BESS", "sav_name": "s.sav", "case_number": 4, "base": "ONS"})
at_state("AT1", d0); run("sim")
check("if a .sav/case WERE captured, AT2 shows them as a confirmation with a Confirmar button",
      step() == "AT2" and data().get("at2_confirm") and "**s.sav**" in reply()
      and AT.T_CONFIRM in [e[4][0][0] for e in option_buttons()])
click(AT.T_CONFIRM)
check("…'Confirmar' advances to ANAT0", step() == "AT3")
fresh(chain(), step="STEP12", data=copy.deepcopy(BESS_FULL), status="active"); run(); run("O que é o ANATEM?")
check("STEP12: a question about the ANATEM is not a handoff", step() == "STEP12")
fresh(chain(), step="STEP7", data=copy.deepcopy(ONS), status="active"); run(); run("quero simular no anatem")
check("mid-ANAREDE: an ANATEM request never starts the flow (notice, state unchanged)",
      step() == "STEP7" and "Já existe uma simulação em andamento" in reply())


# ═════════════════════════════════════════════════════════════════════════════
section("10. Pause/resume, voltar, ajuda, free questions, panel, encerrar")
# ═════════════════════════════════════════════════════════════════════════════
AT5D = {"base": "ONS", "sav_name": "caso_estudo.sav", "case_number": "5", "dmaq_name": "dmaq_anat0.dma"}
at_state("AT5", AT5D)
panel = [e[1] for e in EV if e[0] == "markdown"]
check("'Estudo atual' panel: base, .sav, case, DMAQ (read-only, no ✏️)",
      all(x in panel for x in ["Base: **ONS**", "Arquivo .sav: **caso_estudo.sav**", "Caso: **5**",
                               "DMAQ: **dmaq_anat0.dma**"])
      and not any(e[2] and str(e[2]).startswith("edit_") for e in events("button")))
check("progress 'Passo 5 de 11 · ANATEM 5: Edição do .stb'",
      ("progress", 5 / 11, "Passo 5 de 11 · ANATEM 5: Edição do .stb") in EV)
SCRIPT["press"] = {"⏸️ Pausar simulação"}; run(); SCRIPT["press"] = set()
ps = svc.load_paused_state("userA")
check("pause: status paused, step/data persisted like the other flows",
      sim_state()["sim_status"] == "paused" and ps and ps["sim_step"] == "AT5"
      and ps["sim_data"]["sim_type"] == "ANATEM" and ps["sim_data"]["dmaq_name"] == "dmaq_anat0.dma")
run("retomar")
check("'retomar': active again, AT5 question repeated", sim_state()["sim_status"] == "active"
      and "Edição do .stb" in reply() and step() == "AT5")
run("voltar")
check("'voltar' at AT5 → AT4 (DMAQ question)", step() == "AT4" and "Voltando um passo" in reply())
at_state("AT9", dict(AT9, cdu={"number": "5"}))
run("voltar")
check("'voltar' at AT9 → back to the run step (AT8)", step() == "AT8")
at_state("AT1"); run("voltar")
check("'voltar' at AT1 stays", step() == "AT1" and "primeiro passo" in reply())
at_state("AT3", AT5D); run("ajuda")
check("'ajuda' at AT3: help with the step details, state unchanged",
      step() == "AT3" and "Ajuda" in reply() and "Etapa 2" in reply())
ch = chain()
at_state("AT3", AT5D, ch=ch); run("O que é o arquivo BNT1.DAT?")
ctx = (ch.last_inputs or {}).get("study_context", "")
check("free question mid-flow → LLM with the current ANATEM step as context, state unchanged",
      llm_called(ch) and step() == "AT3" and "Current step: ANATEM 3: ANAT0" in ctx and "BNT1.DAT" in ctx)
check("…and the ↩️ nudge names the ANATEM step", "o resultado do ANAT0" in reply())
ch = chain()
at_state("AT11", AT5D, ch=ch); run("Como insiro um curto no DEVT?")
check("free question at AT11 → LLM (not stored as an event)", llm_called(ch) and not data().get("events"))
run("evento no fim da linha 1001")
check("event text containing 'fim' is an event, not 'encerrar'",
      step() == "AT11" and data().get("event_pending") == "Perda de linha de transmissão")
at_state("AT6", AT5D); run("encerrar")
check("'encerrar' mid-flow ends the ANATEM simulation", step() == "IDLE" and "encerrada" in reply())
at_state("AT2", {"base": "ONS"}); run("fim.sav, caso 2")
check("a file named 'fim.sav' is not 'encerrar'", step() == "AT3" and data()["sav_name"] == "fim.sav")
at_state("AT4", AT5D); run("nova simulação")
check("'nova simulação' inside ANATEM restarts the ANATEM flow at AT1", step() == "AT1" and data() == {"sim_type": "ANATEM"})
at_state("AT4", AT5D); run("quero inserir um bess no anarede")
check("ANAREDE request inside ANATEM: notice, state unchanged", step() == "AT4" and "Já existe" in reply())
at_state("AT3", AT5D); run("rodei o ANAT0 no ANAREDE e rodou sem erros")
check("an answer that merely mentions the ANAREDE is processed by the step (AT3 → AT4)", step() == "AT4")
fresh(chain(), step="IDLE_LT_CONFIRM", data={"pending_lt": {"voltage_kv": 230.0}, "pending_question": "LT"})
run(); run("quero simular no anatem")
check("IDLE_LT_CONFIRM (no simulation yet) + ANATEM request → ANATEM starts", step() == "AT1")
bad = [s for s in AT.ALL_STEPS if not (fresh(chain(), step=s, data={"sim_type": "ANATEM", "base": "ONS"},
                                             status="active") or run()["_current_step_question"]())]
check("every AT*/ATS* step has a question (resume / LLM context)", not bad, bad)
bad = [s for s in AT.ALL_STEPS if not SI.controls_for(s, {"sim_type": "ANATEM"})]
check("every AT*/ATS* step has buttons or a form", not bad, bad)


# ═════════════════════════════════════════════════════════════════════════════
section("10b. Stuck analysis, admin, DB, glossary, version, welcome")
# ═════════════════════════════════════════════════════════════════════════════
U = lambda t, s: {"role": "user", "message": t, "sim_step": s, "sim_type": "ANATEM"}
A = lambda t, s: {"role": "assistant", "message": t, "sim_step": s, "sim_type": "ANATEM"}
a = SA.analyze_session([U("x", "AT6"), A("r", "AT6"), U("y", "AT6"), A("r", "AT6"), U("z", "AT6"), A("r", "AT6")])
check("not-advancing rule applies to ANATEM steps (none exempt)", a["not_advancing"] == ["AT6"])
a2 = SA.analyze_session([U("x", "AT11"), A("r", "AT11"), U("y", "AT11"), A("r", "AT11"),
                         U("z", "AT11"), A("r", "AT11")])
check("…including the multi-turn event step AT11", a2["not_advancing"] == ["AT11"])
check("infer_sim_type: AT*/ATS* → ANATEM", SA.infer_sim_type("AT3") == "ANATEM" and SA.infer_sim_type("ATS4") == "ANATEM")
a3 = SA.analyze_session([{"role": "user", "message": "x", "sim_step": "AT10"},
                         {"role": "assistant", "message": "r", "sim_step": "AT11"}])
check("AT11 is terminal (finished); timeline shows short labels",
      a3["outcome"] == "finished" and SA.timeline_text(a3).startswith("AT10 (PLOTCEPEL) → AT11 (eventos)"))
check("step order AT1 … AT9 < AT10 < AT11 < ATS2 (stuck report sort)",
      sorted(["AT10", "ATS2", "AT9", "AT11", "AT1"], key=SA._step_sort_key) == ["AT1", "AT9", "AT10", "AT11", "ATS2"])
panel_src = open("admin/panel.py", encoding="utf-8").read()
check("admin: sim_type filter (sessions, feedback, export) includes ANATEM",
      '"ANATEM"' in panel_src and panel_src.count("SIM_TYPE_FILTER, key=") == 3)
check("DB: sessions.sim_type stores 'ANATEM' and the filter finds it (no schema change)",
      any(s["sim_type"] == "ANATEM" for s in svc.list_sessions(sim_type="ANATEM")))
check("glossary: the 13 ANATEM terms + v6.6.1 DARQ/ULOG and DEVT event codes, pending expert review",
      set(GLOSSARY_ANATEM) == {"ANAT0", "ANATEM", "STB", "DMAQ", "CDU", "DEVT", "DPLT", "DFNT", "flat run",
                               "PLOTCEPEL", "AVR", "GOV", "PSS", "DARQ", "ULOG", "APCB", "APCC", "APCL",
                               "ABCI", "RMGR", "MDLP", "MDLQ"} and set(GLOSSARY_ANATEM) <= set(ALL_TERMS))
check("glossary matching: ANAT0, DMAQ and '.stb' found in a step message",
      {"ANAT0", "DMAQ", "STB"} <= set(find_terms(AT.question("AT3", {}) + " " + AT.question("AT5", {}))))
check("APP_VERSION v6.6.1, v6.6.0 DRAFT PT-BR notes kept", APP_VERSION == "v6.6.1"
      and "DRAFT" in RELEASE_NOTES["v6.6.0"]["status"] and len(RELEASE_NOTES["v6.6.0"]["o_que_testar"]) == 5)
start()
check("welcome message mentions the ANATEM, the rest kept",
      "Para estabilidade dinâmica, também te guio no ANATEM." in ss.messages[0]["content"]
      and "Se quiser realizar um estudo de simulação com o Anarede" in ss.messages[0]["content"])
src = open("agents/anatem_flow.py", encoding="utf-8").read()
check("technical text blocks marked PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)",
      src.count("PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)") >= 20)


# ═════════════════════════════════════════════════════════════════════════════
section("12. The tests are not trivial: break a trigger, a CDU branch, the pre-fill")
# ═════════════════════════════════════════════════════════════════════════════
saved = (AT._TRIGGERS_NORM, AT.parse_ctrl, AT.HANDOFF_BASE)
AT._TRIGGERS_NORM = [t for t in saved[0] if t != AT.norm("estudo de estabilidade")]
check("broken trigger ('estudo de estabilidade' removed) → its router test FAILS",
      not t_trigger("estudo de estabilidade"))
AT._TRIGGERS_NORM = saved[0]
AT.parse_ctrl = lambda text: {"gov": "avr", "avr": "gov"}.get(saved[1](text))
check("broken CDU branch (GOV/AVR swapped) → the GOV and AVR tests FAIL", not t_gov_branch() and not t_avr_branch())
AT.parse_ctrl = saved[1]
AT.HANDOFF_BASE = dict(saved[2], ONS="EPE")
check("broken handoff pre-fill (ONS → EPE) → the BESS handoff test FAILS", not t_handoff_bess())
AT.HANDOFF_BASE = saved[2]
check("restored: the same three tests pass again",
      t_trigger("estudo de estabilidade") and t_gov_branch() and t_avr_branch() and t_handoff_bess())

H.finish()
