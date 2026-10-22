"""
v6.5.1 COMMIT 3 — suggestion chips for commonly used values.

Run from repo root:  python3 test_suggestions_v651.py
"""
import copy
import re

import _harness_v650 as H
from _harness_v650 import ss, EV, check, section, fresh, run, events, sim_state, USER
from agents import structured_input as SI
from config.suggestions import SUGGESTIONS, STATUSES

NET = {"title": "Meu Caso", "base_mva": 100.0, "lines": [],
       "buses": [{"number": 1, "name": "REF", "kv": 230.0, "tipo": 2, "v_pu": 1.05},
                 {"number": 2, "name": "CARGA", "kv": 230.0, "tipo": 0, "p_load_mw": 100.0, "q_load_mvar": 30.0},
                 {"number": 3, "name": "SE500", "kv": 500.0, "tipo": 0, "p_load_mw": 10.0, "q_load_mvar": 3.0}]}
LOADED = {"sim_type": "BESS", "db": "ONS", "years": [2028], "year_idx": 0, "year": 2028,
          "scenario": "Inverno Máxima Diurna"}


def netdata(**kw):
    d = {"sim_type": "NETWORK", "network": copy.deepcopy(NET)}
    d.update(kw)
    return d


def setup(step, data, user=None):
    fresh(None, step=step, data=data, status="active", user=user)
    env = run()
    env["_append_system_assistant_message"](env["_current_step_question"]() or "Pergunta do passo.")
    run()
    return env


def chips():
    return [e for e in events("button") if e[2] and e[2].startswith("chip_")]


def chip(label_part):
    return next(e for e in chips() if label_part in e[1])


def submits():
    return events("submit")


def submit(which=0, values=None):
    """Submit the form; `values` overrides fields (None keeps what is in session_state)."""
    sub = submits()[which]
    spec, base, sel = sub[4]
    for f in SI.form_fields(spec, sel):
        k = f"fld_{base}_{f['key']}"
        if values is not None:
            ss[k] = values.get(f["key"], "")
        else:
            ss.setdefault(k, "")
    sub[3](*sub[4])
    run()
    return base


def outcome():
    return sim_state(), ss.messages[-2]["content"], ss.messages[-1]["content"]


# ═════════════════════════════════════════════════════════════════════════════
section("table: only app examples, ≤ 4 decimals, status set")
# ═════════════════════════════════════════════════════════════════════════════


def all_entries(table):
    for key, v in table.items():
        if isinstance(v, dict):
            for sub, entries in v.items():
                for e in entries:
                    yield f"{key}[{sub}]", e
        else:
            for e in v:
                yield key, e


app_src = open("app.py", encoding="utf-8").read() + open("agents/structured_input.py", encoding="utf-8").read()
entries = list(all_entries(SUGGESTIONS))
check("table has entries", len(entries) >= 10, len(entries))
bad = []
for key, e in entries:
    if set(e) != {"value", "label", "source", "status"} or e["status"] not in STATUSES:
        bad.append((key, "shape"))
    nums = e["value"].values() if isinstance(e["value"], dict) else [e["value"]]
    for n in nums:
        txt = SI.fmt_num(n)
        if "." in txt and len(txt.split(".")[1]) > 4:
            bad.append((key, txt, "decimals"))
        if not re.search(rf"(?<![\d.]){re.escape(txt)}(?![\d])", app_src):
            bad.append((key, txt, "not an app example"))
check("every entry well formed, ≤ 4 decimals, and its numbers already appear as examples in the app", not bad, bad)
check("per-km line parameters only for the 230 kV example (other kV left to the experts)",
      list(SUGGESTIONS["line_params_per_km_by_kv"]) == [230])
check("BESS ratings and loads left empty (expert TODO)",
      SUGGESTIONS["bess_mva"] == [] and SUGGESTIONS["bess_p_mw"] == [] and SUGGESTIONS["net_bus_load"] == [])
check("no chip when the table has no entry", SI.suggestion_chips(
    SI._form("net_setup", "x", [SI.F_TITLE, SI.F_BASE]), table={}) == [])

# ═════════════════════════════════════════════════════════════════════════════
section("chip fills the field; no submit, no state change")
# ═════════════════════════════════════════════════════════════════════════════
setup("NET1_SETUP", netdata())
c = chip("100 MVA")
check("chip label shows the value and '(sugestão)'", c[1] == "100 MVA (sugestão)", c[1])
check("tooltip shows source and status", c[6].get("help", "").startswith("Fonte: ") and "Status: exemplo" in c[6]["help"])
before, n_msgs = sim_state(), len(ss.messages)
c[3](*c[4]); run()
base = submits()[0][4][1]
check("click fills the field's session_state key", ss.get(f"fld_{base}_base") == "100", ss.get(f"fld_{base}_base"))
check("click does not submit, advance or change the simulation",
      sim_state() == before and len(ss.messages) == n_msgs and "_input_queue" not in ss)
check("chips are outside the form (rendered before it)",
      EV.index(next(e for e in EV if e[0] == "button" and e[2] == c[2]))
      < EV.index(next(e for e in EV if e[0] == "form")))
ss[f"fld_{base}_base"] = "120"   # the user edits the suggested value before submitting
submit()
check("the user can still edit the filled value before submitting",
      ss["sim_data"]["network"]["base_mva"] == 120.0, ss["sim_data"]["network"])

# chip-filled form == form typed by hand == typed chat text
setup("NET1_SETUP", netdata()); snap = copy.deepcopy(dict(ss))
chip("100 MVA")[3](*chip("100 MVA")[4]); run(); submit()
by_chip = outcome()
ss.clear(); ss.update(copy.deepcopy(snap)); run()
submit(values={"title": "", "base": "100"})
by_hand = outcome()
ss.clear(); ss.update(copy.deepcopy(snap)); run()
run("100 MVA")
check("chip-filled form == same value typed in the form", by_chip == by_hand, (by_chip[0], by_hand[0]))
check("…== same value typed in the chat", by_chip[0] == sim_state() and by_chip[2] == ss.messages[-1]["content"])

# ═════════════════════════════════════════════════════════════════════════════
section("chips per step")
# ═════════════════════════════════════════════════════════════════════════════
net2 = {"total": 4, "idx": 3, "field": "number", "current": {}}
setup("NET2_BUSES", netdata(net2=net2))
labels = [e[1] for e in chips()]
check("bus form (type PQ by default): kV chips only", labels and all("kV" in l for l in labels), labels)
SEL = next(e[3] for e in events("input") if e[1] in ("segmented_control", "radio"))
ss[SEL] = "1"; run()
labels = [e[1] for e in chips()]
check("bus form, PV: kV + V setpoint 1.02 + Q limits chips",
      any("1.02 pu" in l for l in labels) and any("Qmin" in l for l in labels), labels)
qc = chip("Qmin"); qc[3](*qc[4]); run()
b = submits()[0][4][1]
check("Q-limits chip fills both Qmin and Qmax", ss.get(f"fld_{b}_qmin") == "-100" and ss.get(f"fld_{b}_qmax") == "100")

line_mode = {"total": 1, "idx": 0, "field": "mode", "current": {"from_bus": 1, "to_bus": 2, "circuit": 1}}
setup("NET3_LINES", netdata(net3=copy.deepcopy(line_mode)))
labels = [e[1] for e in chips()]
check("line from a 230 kV bus, per km: the 230 kV / 180 km example chip", any("230 kV, 180 km" in l for l in labels), labels)
snap = copy.deepcopy(dict(ss))
chip("230 kV")[3](*chip("230 kV")[4]); run(); submit()
by_chip = outcome()
ss.clear(); ss.update(copy.deepcopy(snap)); run()
run("1"); run("R=0.0257 X=0.2995 B=5.4542 L=180")
check("line chip + submit == typing the same values", by_chip[0] == sim_state(), (by_chip[0], sim_state()))

setup("NET3_LINES", netdata(net3=dict(copy.deepcopy(line_mode), current={"from_bus": 3, "to_bus": 2, "circuit": 1})))
check("line from a 500 kV bus, per km: NO chip (no entry for 500 kV)", not chips(), [e[1] for e in chips()])

setup("NET3_LINES", netdata(net3=dict(copy.deepcopy(line_mode), field="circuit")))
check("circuit: chip '1 (sugestão)'", [e[1] for e in chips()] == ["1 (sugestão)"])

setup("STATCOM_STEP_Q", dict(LOADED, sim_type="STATCOM", statcom_bus="1500"))
check("STATCOM Q: one chip −100 / 100", [e[1] for e in chips()] == ["Qmin −100 / Qmax 100 Mvar (sugestão)"])
snap = copy.deepcopy(dict(ss))
chip("Qmin")[3](*chip("Qmin")[4]); run(); submit()
by_chip = outcome()
ss.clear(); ss.update(copy.deepcopy(snap)); run()
run("Qmin -100 Mvar, Qmax 100 Mvar")
check("STATCOM chip + submit == typing the same text", by_chip[0] == sim_state() and by_chip[2] == ss.messages[-1]["content"])

for step, data in [("STEP8", dict(LOADED, bess_bus="1001", bess_mode="PV")), ("STEP7", LOADED), ("STEP2", LOADED)]:
    setup(step, data)
    check(f"{step}: no chip (no entry)", not chips(), [e[1] for e in chips()])

# ═════════════════════════════════════════════════════════════════════════════
section("Modo especialista hides chips")
# ═════════════════════════════════════════════════════════════════════════════
expert = dict(USER, id="userX", email="x@t", ui_mode="especialista")
setup("NET1_SETUP", netdata(), user=expert)
check("especialista: form shown, no chips", submits() and not chips())
setup("STATCOM_STEP_Q", dict(LOADED, sim_type="STATCOM", statcom_bus="1500"), user=expert)
check("especialista: STATCOM form without chips", submits() and not chips())

H.finish()
