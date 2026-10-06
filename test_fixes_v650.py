"""
v6.5.0 fixes — PV/PQ tipo labels, contingency-exit handling, consistent year
change at STEP12, negative active power deferred.

Run from repo root:  python3 test_fixes_v650.py
"""
import ast
import copy
import glob
import re

import _harness_v650 as H
from _harness_v650 import ss, EV, check, section, fresh, run, events, last_assistant, sim_state
from agents import structured_input as SI
from agents.pwf_agent import generate_dbar_block
from config.glossary import GLOSSARY

ONS = {"sim_type": "BESS", "db": "ONS", "years": [2028], "year_idx": 0}
LOADED = dict(ONS, year=2028, scenario="Inverno Máxima Diurna")
BESS_FULL = dict(LOADED, bess_bus="1001", bess_mode="PV", bess_mva="100", bess_p_mw="80",
                 bess_bus_number="9999")
STATCOM_FULL = {"sim_type": "STATCOM", "db": "ONS", "years": [2028], "year_idx": 0, "year": 2028,
                "scenario": "Inverno Máxima Diurna", "statcom_bus": "1500",
                "statcom_q_min": -100.0, "statcom_q_max": 100.0}


def setup(step, data, status="active"):
    fresh(None, step=step, data=data, status=status)
    env = run()
    env["_append_system_assistant_message"](env["_current_step_question"]() or "Pergunta do passo.")
    run()
    return env


def option_buttons():
    return [e for e in events("button") if e[2] and e[2].startswith("opt_")]


def click(e):
    e[3](*e[4])
    run()


def reply():
    return ss.messages[-1]["content"]


# ═════════════════════════════════════════════════════════════════════════════
section("1. PV/PQ labels use the DBAR codes (PQ=0, PV=1, Referência=2)")
# ═════════════════════════════════════════════════════════════════════════════
DBAR_CODE = {"PQ": "0", "PV": "1"}
# Every way the code ties a tipo number to PV/PQ in user-visible text.
_PAIR_PATS = [
    (re.compile(r"\b(PV|PQ)\s*[—–:,(-]\s*tipo\s*(\d)"), 0, 1),      # "PV — tipo 1"
    (re.compile(r"\btipo\s*(\d)\s*[(—–:-]\s*(PV|PQ)\b"), 1, 0),     # "tipo 0 (PQ)"
    (re.compile(r"(?<![\w.])(\d)\s*[—–=-]\s*(PV|PQ)\b"), 1, 0),     # "0 — PQ", "0 = PQ"
    (re.compile(r"\b(PV|PQ)\s*\((\d)\)"), 0, 1),                    # "PQ (0)"
]


def wrong_pairs(text):
    """[(label, code, snippet)] for every PV/PQ ↔ tipo pairing that disagrees with the DBAR."""
    text = text.replace("*", "")
    bad, found = [], 0
    for pat, li, ci in _PAIR_PATS:
        for m in pat.finditer(text):
            found += 1
            lbl, code = m.group(li + 1), m.group(ci + 1)
            if DBAR_CODE[lbl] != code:
                bad.append((lbl, code, m.group(0)))
    return bad, found


def string_literals(path):
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):   # f-strings: literal parts only
            out.append((node.lineno, "".join(v.value for v in node.values
                                             if isinstance(v, ast.Constant) and isinstance(v.value, str))))
    return out


# Self-test: the checker must flag the labels reported by the tester.
bad_old, _ = wrong_pairs("1. **Controle de tensão (barra PV — tipo 2)**\n\n2. **Despacho fixo (barra PQ — tipo 1)**")
check("checker flags the old labels 'PV — tipo 2' / 'PQ — tipo 1'", len(bad_old) == 2, bad_old)
check("checker accepts 'tipo 0 (PQ) ou tipo 1 (PV)' and '**0** — PQ (carga)'",
      wrong_pairs("Mude para tipo 0 (PQ) ou tipo 1 (PV). **0** — PQ (carga) **1** — PV (geração)") == ([], 4))

files = ["app.py"] + sorted(glob.glob("agents/*.py") + glob.glob("config/*.py") + glob.glob("prompts/*.py"))
violations, total = [], 0
for path in files:
    for lineno, s in string_literals(path):
        bad, found = wrong_pairs(s)
        total += found
        violations += [(path, lineno, b) for b in bad]
check("no user-visible PV/PQ label uses the wrong tipo code (app.py, agents/, config/, prompts/)",
      not violations, violations)
check(f"the scan actually sees PV/PQ ↔ tipo pairings ({total} found)", total >= 10, total)

check("glossary: PV is tipo 1, PQ is tipo 0, Referência is tipo 2",
      "tipo 1" in GLOSSARY["PV"] and "tipo 0" in GLOSSARY["PQ"] and "tipo 2" in GLOSSARY["Referência"])

setup("STEP7", dict(LOADED, bess_bus="1001"))
q = last_assistant()["content"]
check("STEP7 mode question shows 'PV — tipo 1' and 'PQ — tipo 0'",
      "barra PV — tipo 1" in q and "barra PQ — tipo 0" in q and not wrong_pairs(q)[0], q)
btn_text = " ".join(b[1] + " " + b[4][0][0] for b in option_buttons())
check("STEP7 mode buttons carry no wrong tipo code", option_buttons() and not wrong_pairs(btn_text)[0], btn_text)
run()
check("the full STEP7 message (incl. Detalhes) has no wrong code", not wrong_pairs(last_assistant()["content"]
                                                                                 + last_assistant().get("details", ""))[0])

setup("STEP7", dict(LOADED, bess_bus="1001"))
run("tipo 0")
check("typing the DBAR code 'tipo 0' selects PQ", ss["sim_data"].get("bess_mode") == "PQ" and ss["sim_step"] == "STEP8",
      sim_state())
setup("STEP7", dict(LOADED, bess_bus="1001"))
run("tipo 1")
check("typing 'tipo 1' selects PV", ss["sim_data"].get("bess_mode") == "PV")
setup("STEP7", dict(LOADED, bess_bus="1001"))
run("2")
check("option number '2' still selects PQ", ss["sim_data"].get("bess_mode") == "PQ")

# ═════════════════════════════════════════════════════════════════════════════
section("2. 'encerrar contingências' at STEP11B ends only the contingency sub-flow")
# ═════════════════════════════════════════════════════════════════════════════
setup("STEP11B", dict(BESS_FULL, contingency_stage="done"))
snap = copy.deepcopy(dict(ss))
btn = next(b for b in option_buttons() if b[1] == "Seguir para os próximos passos")
click(btn)
s_button, r_button = sim_state(), reply()
ss.clear(); ss.update(copy.deepcopy(snap))
run("encerrar contingências")
check("typed 'encerrar contingências' → STEP12, simulation still active",
      ss["sim_step"] == "STEP12" and ss["simulation_mode"] and ss["sim_status"] == "active", sim_state())
check("…same state and reply as the 'Seguir para os próximos passos' button",
      sim_state() == s_button and reply() == r_button, (sim_state(), s_button))
check("…device parameters kept", all(ss["sim_data"].get(k) == v for k, v in BESS_FULL.items()))

for stage in (None, "guide", "awaiting_results"):
    for phrase in ("encerrar contingências", "Encerrar as contingências", "finalizar contingencia"):
        data = dict(BESS_FULL, contingency_stage=stage) if stage else dict(BESS_FULL)
        setup("STEP11B", data)
        run(phrase)
        ok = (ss["sim_step"] == "STEP12" and ss["simulation_mode"]
              and "contingency_stage" not in ss["sim_data"] and "Próximos passos" in reply())
        check(f"stage={stage}: '{phrase}' → STEP12, simulation kept", ok, sim_state())

for stage in (None, "guide", "done", "awaiting_results"):
    data = dict(BESS_FULL, contingency_stage=stage) if stage else dict(BESS_FULL)
    setup("STEP11B", data)
    run("encerrar")
    check(f"stage={stage}: plain 'encerrar' still ends the whole simulation",
          ss["sim_step"] == "IDLE" and not ss["simulation_mode"] and ss["sim_data"] == {}
          and "encerrada" in reply(), sim_state())

setup("STEP12", BESS_FULL)
run("encerrar")
check("STEP12: plain 'encerrar' ends the simulation", ss["sim_step"] == "IDLE" and not ss["simulation_mode"])
setup("STEP8", dict(LOADED, bess_bus="1001", bess_mode="PV"))
run("finalizar")
check("other steps: 'finalizar' still ends the simulation", ss["sim_step"] == "IDLE")

# ═════════════════════════════════════════════════════════════════════════════
section("3. STEP12 new year keeps scenario and device (like the ✏️ year edit)")
# ═════════════════════════════════════════════════════════════════════════════
setup("STEP12", BESS_FULL)
run("2030")
d, r = ss["sim_data"], reply()
check("year updated, scenario kept, case for the new year is loaded (STEP4)",
      d["years"] == [2030] and d["year"] == 2030 and d["scenario"] == "Inverno Máxima Diurna"
      and ss["sim_step"] == "STEP4" and "2030.SAV" in r, (sim_state(), r))
check("device parameters kept",
      all(d.get(k) == BESS_FULL[k] for k in ("bess_bus", "bess_mode", "bess_mva", "bess_p_mw", "bess_bus_number")), d)
lines = [ln for ln in r.splitlines() if ln.startswith("Mantendo")]
check("exactly one confirmation line with the kept values",
      len(lines) == 1 and lines[0] == "Mantendo barra **1001**, modo **PV**, **100 MVA**, P = **80 MW** "
                                       "— confirme ou use ✏️ para editar.", lines)

# Same data as the ✏️ year edit from the study panel.
setup("STEP12", BESS_FULL)
e = next(e for e in events("button") if e[2] == "edit_years"); e[3](*e[4]); run()
run("2030")
panel = {k: v for k, v in ss["sim_data"].items() if k not in ("contingency_stage", "divergence_color")}
check("kept values match the ✏️ year edit", panel == d, (panel, d))

ss.clear(); setup("STEP12", BESS_FULL); run("2030")
run("convergido")
exp = generate_dbar_block(bus_number="1001", bess_bus_number="9999", bus_type="1", S_mva=100.0, P_mw=80.0)
check("after confirming the new case: block regenerated with the kept values, no re-asking (STEP9)",
      ss["sim_step"] == "STEP9" and f"```\n{exp}\n```" in reply(), (sim_state(), reply()[:300]))

setup("STEP12", BESS_FULL); run("2030")
e = next(e for e in events("button") if e[2] == "edit_bess_mva"); e[3](*e[4]); run()
run("150 MVA")
check("✏️ after the year change edits the kept value and stays at STEP4",
      ss["sim_step"] == "STEP4" and ss["sim_data"]["bess_mva"] == "150", sim_state())
run("convergido")
exp = generate_dbar_block(bus_number="1001", bess_bus_number="9999", bus_type="1", S_mva=150.0, P_mw=80.0)
check("…and the regenerated block uses the edited value", f"```\n{exp}\n```" in reply())

setup("STEP12", STATCOM_FULL)
run("2031")
lines = [ln for ln in reply().splitlines() if ln.startswith("Mantendo")]
check("STATCOM: one confirmation line (bus, Qmin, Qmax), STEP4",
      ss["sim_step"] == "STEP4" and len(lines) == 1 and "barra **1500**" in lines[0]
      and "-100 Mvar" in lines[0] and "100 Mvar" in lines[0], (sim_state(), lines))
run("convergido")
check("STATCOM: after the new case converges → control-bus question (block regenerated next)",
      ss["sim_step"] == "STATCOM_STEP_CBUS" and ss["sim_data"]["statcom_bus"] == "1500", sim_state())

setup("STEP12", BESS_FULL)
run("Verão Máxima Noturna")
check("scenario change in STEP12 unchanged (device cleared, STEP4)",
      ss["sim_step"] == "STEP4" and "bess_bus" not in ss["sim_data"])

# ═════════════════════════════════════════════════════════════════════════════
section("4. negative active power deferred")
# ═════════════════════════════════════════════════════════════════════════════
setup("STEP7", dict(LOADED, bess_bus="1001"))
run("1")
m = last_assistant()
full = m["content"] + m.get("details", "")
check("STEP8 recommendation no longer suggests -100% (carga)",
      "+100%" in full and "-100%" not in full and "(carga)" not in full, full)
app_src = open("app.py", encoding="utf-8").read()
prompt_src = open("prompts/system_prompt.py", encoding="utf-8").read()
check("no '-100% (carga)' suggestion left in app.py strings or the system prompt",
      not any("-100% (carga)" in s for _, s in string_literals("app.py")) and "-100% (carga)" not in prompt_src)
check("PENDING EXPERT DECISION comment present",
      "PENDING EXPERT DECISION: charging BESS as negative Pg or as load (Pl)" in app_src)
check("form still 0 ≤ P (min 0)", SI.F_P["min"] == 0)
spec = SI._form("bess_p", "Potência ativa da BESS", [SI.F_P])
check("form still rejects P > S", bool(SI.compose(spec, {"p": "120"}, data={"bess_mva": "100"})[0]))
check("form still rejects P < 0", bool(SI.compose(spec, {"p": "-50"}, data={"bess_mva": "100"})[0]))

H.finish()
