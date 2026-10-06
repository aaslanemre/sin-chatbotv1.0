"""
v6.5.0 PART B — buttons and forms for structured steps, study panel with edit,
conversation history ("Minhas conversas"), beginner/expert mode.

Run from repo root:  python3 test_structured_v650.py
"""
import copy
import importlib.util
import bcrypt

import _harness_v650 as H
from _harness_v650 import (ss, EV, SCRIPT, svc, check, section, fresh, run, events,
                           last_assistant, assistants, sim_state, rows, StreamChain, scores)
from agents import structured_input as SI
from agents import ux
from agents.pwf_agent import generate_dbar_block
from config.glossary import GLOSSARY, GLOSSARY_STATUS, find_terms

H.st.error = lambda body="", **kw: EV.append(("error", body))
H.st.info = lambda body="", **kw: EV.append(("info", body))

LT = {"voltage_kv": 230.0, "length_km": 180.0, "R_ohm_km": 0.0257, "X_ohm_km": 0.2995, "B_us_km": 5.4542}
ONS = {"sim_type": "BESS", "db": "ONS", "years": [2028], "year_idx": 0}
LOADED = dict(ONS, year=2028, scenario="Inverno Máxima Diurna")
BESS_FULL = dict(LOADED, bess_bus="1001", bess_mode="PV", bess_mva="100", bess_p_mw="80")
NET = {"title": "Meu Caso", "base_mva": 100.0, "lines": [],
       "buses": [{"number": 1, "name": "REF", "kv": 230.0, "tipo": 2, "v_pu": 1.05, "angle_deg": 0.0,
                  "p_gen_mw": 0.0, "q_min_mvar": 0.0, "q_max_mvar": 0.0, "p_load_mw": 0.0, "q_load_mvar": 0.0},
                 {"number": 2, "name": "CARGA", "kv": 230.0, "tipo": 0, "v_pu": 1.0, "angle_deg": 0.0,
                  "p_gen_mw": 0.0, "q_min_mvar": 0.0, "q_max_mvar": 0.0, "p_load_mw": 100.0, "q_load_mvar": 30.0}]}
NET_OK = dict(NET, lines=[{"id": 1, "from_bus": 1, "to_bus": 2, "circuit": 1, "r_pct": 0.5, "x_pct": 5.0, "q_mvar": 10.0}])


def netdata(**kw):
    d = {"sim_type": "NETWORK", "network": copy.deepcopy(NET)}
    d.update(kw)
    return d


def setup(step, data, status="active", chain=None):
    """State at `step` with an assistant message as the latest one (controls render under it)."""
    fresh(chain, step=step, data=data, status=status)
    env = run()
    env["_append_system_assistant_message"](env["_current_step_question"]() or "Pergunta do passo.")
    run()
    return env


def snapshot():
    return copy.deepcopy(dict(ss))


def restore(snap):
    ss.clear()
    ss.update(copy.deepcopy(snap))


def option_buttons():
    return [e for e in events("button") if e[2] and e[2].startswith("opt_")]


def click(e):
    e[3](*e[4])
    run()


def outcome():
    msgs = ss.messages
    return sim_state(), msgs[-2]["content"], msgs[-1]["content"]


def last_user_row():
    return rows("SELECT * FROM chat_logs WHERE role='user' ORDER BY id DESC LIMIT 1")[0]


# ═════════════════════════════════════════════════════════════════════════════
section("9. every choice step: button click == typing the canonical answer")
# ═════════════════════════════════════════════════════════════════════════════
CASES = [
    ("IDLE_LT_CONFIRM", "IDLE_LT_CONFIRM", {"pending_lt": LT, "pending_question": "Tenho uma LT de 230 kV"}, None, ["1", "2"]),
    ("IDLE_LT_NET_CHOICE", "IDLE_LT_NET_CHOICE", {"pending_lt": LT}, "active", ["1", "2"]),
    ("STEP1 database", "STEP1", {"sim_type": "BESS"}, "active", ["1", "2", "3"]),
    ("STEP3 scenario ONS", "STEP3", ONS, "active", [str(i) for i in range(1, 7)]),
    ("STEP3 scenario EPE", "STEP3", dict(ONS, db="EPE"), "active", [str(i) for i in range(1, 9)]),
    ("STEP4 convergence", "STEP4", LOADED, "active", ["convergido", "não convergido"]),
    ("STEP6 LST", "STEP6", LOADED, "active", ["opção A", "opção B"]),
    ("STEP7 PV/PQ", "STEP7", dict(LOADED, bess_bus="1001"), "active", ["1", "2"]),
    ("STATCOM local bus", "STATCOM_STEP_CBUS", {"sim_type": "STATCOM", "statcom_bus": "1500",
                                                "statcom_q_min": -100.0, "statcom_q_max": 100.0}, "active", ["1"]),
    ("STEP9 saved", "STEP9", BESS_FULL, "active", ["pronto"]),
    ("STEP10 convergence", "STEP10", BESS_FULL, "active", ["convergiu", "não convergiu"]),
    ("STEP10 color", "STEP10", dict(BESS_FULL, divergence_color="unknown"), "active", ["vermelho", "amarelo"]),
    ("STEP11B yes/no", "STEP11B", BESS_FULL, "active", ["sim", "não"]),
    ("STEP11B execute/add/end", "STEP11B", dict(BESS_FULL, contingency_stage="done"), "active",
     ["executar", "adicionar mais", "pode seguir"]),
    ("STEP12 continuation", "STEP12", BESS_FULL, "active", ["sim", "encerrar"]),
    ("NET1 confirm", "NET1_SETUP", netdata(), "active", ["ok"]),
    ("NET2 bus type", "NET2_BUSES", netdata(net2={"total": 3, "idx": 2, "field": "tipo",
                                                  "current": {"number": 3, "name": "B3", "kv": 230.0}}), "active", ["0", "1", "2"]),
    ("NET3 from bus", "NET3_LINES", netdata(net3={"total": 1, "idx": 0, "field": "from_bus", "current": {}}), "active", ["1", "2"]),
    ("NET3 to bus", "NET3_LINES", netdata(net3={"total": 1, "idx": 0, "field": "to_bus", "current": {"from_bus": 1}}), "active", ["2"]),
    ("NET4 review", "NET4_REVIEW", dict(netdata(), network=copy.deepcopy(NET_OK)), "active",
     ["ok", "adicionar barra", "adicionar linha"]),
    ("NET5 continue", "NET5_GENERATE", dict(netdata(), network=copy.deepcopy(NET_OK), net_pwf="X"), "active", ["ok"]),
    ("NET6 color", "NET6_RUN", dict(netdata(), network=copy.deepcopy(NET_OK)), "active", ["convergiu", "amarelo", "vermelho"]),
    ("NET7 converged", "NET7_RESULTS", dict(netdata(), network=copy.deepcopy(NET_OK), net7_color="green"), "active",
     ["n-1", "bess", "statcom", "encerrar"]),
    ("NET7 not converged", "NET7_RESULTS", dict(netdata(), network=copy.deepcopy(NET_OK), net7_color="red"), "active",
     ["editar", "fim"]),
]

for name, step, data, status, aliases in CASES:
    setup(step, data, status)
    btns = option_buttons()
    snap = snapshot()
    ok_all, alias_ok, details = bool(btns) and len(btns) == len(aliases), True, []
    for i, b in enumerate(btns):
        text = b[4][0][0]
        restore(snap); click(b)
        s_click = outcome()
        src = last_user_row()["input_source"]
        restore(snap); run(text)
        s_typed = outcome()
        same = s_click == s_typed and s_click[1] == text and src == "button"
        if not same:
            ok_all = False
            details.append((b[1], text, s_click[0], s_typed[0], src))
        if i < len(aliases):
            restore(snap); run(aliases[i])
            if sim_state() != s_click[0]:
                alias_ok = False
                details.append(("alias", aliases[i], sim_state(), s_click[0]))
    check(f"{name}: {len(btns)} buttons; click == typed canonical (state, user message, reply)", ok_all, details[:2])
    check(f"{name}: canonical answers reach the same state as the usual typed answers {aliases}", alias_ok, details[:2])

setup("STEP3", ONS)
btn_labels = [b[1] for b in option_buttons()]
run()
check("older messages show no buttons: one set of options, keyed to the LATEST message only",
      all(b[2].startswith(f"opt_{last_assistant()['message_id']}_") for b in option_buttons()))
setup("STEP7", dict(LOADED, bess_bus="1001"), status="paused")
check("paused simulation: no step buttons", not option_buttons())
fresh(None); run(); run("o que é o SIN?")
check("free conversation (no simulation): no buttons or forms", not option_buttons() and not events("form"))
setup("STEP3", ONS)
run("4")
check("typing still works next to the buttons", ss["sim_data"]["scenario"] == "Inverno Máxima Diurna" and ss["sim_step"] == "STEP4")
check("8 scenario options laid out 2 per row (stack on mobile)",
      SI.controls_for("STEP3", dict(ONS, db="EPE"), [], ["a"] * 8)[0]["options"].__len__() == 8)


# ═════════════════════════════════════════════════════════════════════════════
section("10. forms: invalid input blocked inline; valid input == equivalent typed text")
# ═════════════════════════════════════════════════════════════════════════════
def form_parts():
    subs = [e for e in events("submit")]
    inputs = [e for e in events("input") if e[1] == "text_input" and e[3] and e[3].startswith("fld_")]
    return subs, inputs


def fill_and_submit(values, which=0):
    subs, inputs = form_parts()
    sub = subs[which]
    spec, base, sel = sub[4]
    for f in SI.form_fields(spec, sel):
        k = f"fld_{base}_{f['key']}"
        ss[k] = values.get(f["key"], "")
    sub[3](*sub[4])
    return base


def select(value, prefix="sel_"):
    key = next(e[3] for e in events("input") if e[1] in ("segmented_control", "radio") and e[3].startswith(prefix))
    ss[key] = value
    run()


FORM_CASES = [
    # name, step, data, values, typed equivalent(s), invalid values, expected error fragment
    ("STEP2 years", "STEP2", {"sim_type": "BESS", "db": "ONS"}, {"years": "2027, 2028"}, ["2027, 2028"],
     {"years": "28"}, "4 dígitos"),
    ("STEP7 BESS bus", "STEP7", LOADED, {"bus": "1001"}, ["1001"], {"bus": "10a"}, "inteiro"),
    ("STEP7 STATCOM bus", "STEP7", dict(LOADED, sim_type="STATCOM"), {"bus": "1500"}, ["1500"], {"bus": ""}, "Informe"),
    ("STEP8 MVA + P", "STEP8", dict(LOADED, bess_bus="1001", bess_mode="PV"), {"mva": "100", "p": "80"},
     ["100 MVA, potência ativa 80 MW"], {"mva": "100", "p": "120"}, "maior que a potência nominal"),
    ("STEP8 MVA only", "STEP8", dict(LOADED, bess_bus="1001", bess_mode="PV"), {"mva": "100,5"}, ["100.5 MVA"],
     {"mva": "-5"}, "no mínimo"),
    ("STEP8 active power", "STEP8", dict(LOADED, bess_bus="1001", bess_mode="PV", bess_mva="100"), {"p": "80"},
     ["80"], {"p": "abc"}, "inválido"),
    ("STEP8 new bus", "STEP8", BESS_FULL, {"bus": "9999"}, ["9999"], {"bus": "99"}, "no mínimo"),
    ("STATCOM Q limits", "STATCOM_STEP_Q", {"sim_type": "STATCOM", "statcom_bus": "1500"},
     {"qmin": "-100", "qmax": "100"}, ["Qmin -100 Mvar, Qmax 100 Mvar"], {"qmin": "100", "qmax": "-100"}, "menor que Qmax"),
    ("NET1 title + base", "NET1_SETUP", netdata(), {"title": "Rede Teste", "base": "100"}, ["Rede Teste, 100 MVA"],
     {"title": "Rede do fim", "base": "100"}, "comando"),
    ("NET2 bus count", "NET2_BUSES", netdata(net2={"total": None, "idx": 0, "field": "count", "current": {}}),
     {"v": "3"}, ["3"], {"v": "25"}, "no máximo"),
    ("NET2 name", "NET2_BUSES", netdata(net2={"total": 3, "idx": 2, "field": "name", "current": {"number": 3}}),
     {"v": "B3"}, ["B3"], {"v": "Barra três"}, "letras"),
    ("NET2 kV", "NET2_BUSES", netdata(net2={"total": 3, "idx": 2, "field": "kv", "current": {"number": 3, "name": "B3"}}),
     {"v": "230"}, ["230"], {"v": "0"}, "no mínimo"),
    ("NET3 line count", "NET3_LINES", netdata(net3={"total": None, "idx": 0, "field": "count", "current": {}}),
     {"v": "1"}, ["1"], {"v": "1.5"}, "inteiro"),
    ("NET3 circuit", "NET3_LINES", netdata(net3={"total": 1, "idx": 0, "field": "circuit", "current": {"from_bus": 1, "to_bus": 2}}),
     {"v": "1"}, ["1"], {"v": "0"}, "no mínimo"),
    ("NET3 values (pu)", "NET3_LINES", netdata(net3={"total": 1, "idx": 0, "field": "values",
                                                     "current": {"from_bus": 1, "to_bus": 2, "circuit": 1, "param_mode": "pu"}}),
     {"r": "0.001", "x": "0.05", "b": "0.02"}, ["R=0.001 X=0.05 B=0.02"], {"r": "0.001", "x": "0", "b": "0.02"}, "no mínimo"),
]

for name, step, data, values, typed, bad, frag in FORM_CASES:
    setup(step, data)
    snap = snapshot()
    state0, n_before = sim_state(), len(ss.messages)
    fill_and_submit(bad)
    run()
    errs = [e[1] for e in events("error")]
    check(f"{name}: invalid input blocked inline (error shown, nothing sent, state unchanged)",
          any(frag in e for e in errs) and len(ss.messages) == n_before and sim_state() == state0, errs)
    restore(snap); run()
    fill_and_submit(values); run()
    s_form = sim_state()
    users = [m["content"] for m in ss.messages if m["role"] == "user"]
    src = last_user_row()["input_source"]
    restore(snap)
    for t in typed:
        run(t)
    check(f"{name}: valid form → same state as typing {typed!r}, logged as 'form'",
          s_form == sim_state() and src == "form", (s_form, sim_state(), users[-1:], src))

# bus form with the type selector: Ref / PQ (one compact record) and PV (field by field)
BUS_START = netdata(net2={"total": 3, "idx": 2, "field": "number", "current": {}})
for tipo, values, typed in [
    ("2", {"number": "3", "name": "REF2", "kv": "230", "v_pu": "1.02"}, ["3", "REF2", "230", "2", "1.02"]),
    ("0", {"number": "3", "name": "LOAD3", "kv": "230", "pl": "50", "ql": "10"}, ["3", "LOAD3", "230", "0", "50", "10"]),
    ("1", {"number": "3", "name": "GEN3", "kv": "230", "pg": "100", "v_pu": "1.01", "qmin": "-50", "qmax": "50"},
     ["3", "GEN3", "230", "1", "100", "1.01", "-50", "50"]),
]:
    setup("NET2_BUSES", BUS_START)
    snap = snapshot()
    select(tipo)
    fill_and_submit(values); run()
    s_form = sim_state()
    form_rows = rows("SELECT input_source FROM chat_logs WHERE role='user' ORDER BY id DESC LIMIT 5")
    restore(snap)
    for t in typed:
        run(t)
    check(f"bus form type {tipo}: same network as typing the fields one by one",
          s_form == sim_state() and s_form["sim_step"] == "NET3_LINES", (s_form["sim_data"].get("network", {}).get("buses", [])[-1:],
                                                                        sim_state()["sim_data"].get("network", {}).get("buses", [])[-1:]))
setup("NET2_BUSES", BUS_START)
select("1")
n0 = len(ss.messages)
fill_and_submit({"number": "2", "name": "DUP", "kv": "230", "pg": "1", "v_pu": "1", "qmin": "-1", "qmax": "1"}); run()
check("bus form: duplicate bus number blocked inline", len(ss.messages) == n0 and any("já existe" in e[1] for e in events("error")))
fill_and_submit({"number": "3", "name": "GEN3", "kv": "230", "pg": "1", "v_pu": "2", "qmin": "-1", "qmax": "1"}); run()
check("bus form: V outside 0.5–1.5 pu blocked inline", len(ss.messages) == n0 and any("no máximo 1.5" in e[1] for e in events("error")))

LINE_START = netdata(net3={"total": 1, "idx": 0, "field": "mode", "current": {"from_bus": 1, "to_bus": 2, "circuit": 1}})
for mode, values, typed in [
    ("1", {"r": "0.0257", "x": "0.2995", "b": "5.4542", "l": "180"}, ["1", "R=0.0257 X=0.2995 B=5.4542 L=180"]),
    ("2", {"r": "0.001", "x": "0.05", "b": "0.02"}, ["2", "R=0.001 X=0.05 B=0.02"]),
    ("3", {"r": "0.87", "x": "10.19", "q": "51.93"}, ["3", "R=0.87 X=10.19 Q=51.93"]),
]:
    setup("NET3_LINES", LINE_START)
    snap = snapshot()
    select(mode)
    labels = [e[2] for e in events("input") if e[1] == "text_input" and e[3] and e[3].startswith("fld_")]
    fill_and_submit(values); run()
    s_form = sim_state()
    restore(snap)
    for t in typed:
        run(t)
    check(f"line form mode {mode}: selector shows {labels}; same line as typing mode then values",
          s_form == sim_state() and s_form["sim_step"] == "NET4_REVIEW", (s_form["sim_step"], sim_state()["sim_step"]))
setup("NET3_LINES", LINE_START); select("1")
check("line mode selector 'por km' shows R/X/B per km + length",
      [e[2] for e in events("input") if e[1] == "text_input" and e[3].startswith("fld_")]
      == ["R (Ω/km)", "X (Ω/km)", "B (μS/km)", "Comprimento (km)"])

# a sequence stops if one answer is not accepted (never fed to another question)
setup("NET2_BUSES", BUS_START)
ss["sim_data"]["network"]["buses"].append({"number": 9, "name": "X", "kv": 230.0, "tipo": 0})
env = run()
n0 = len([m for m in ss.messages if m["role"] == "user"])
env["_queue_input"](["9, GEN3, 230 kV, PV", "100", "1.01"], "form")   # 9 already exists → re-ask
run()
check("form sequence aborts when the first answer is rejected (no stray values)",
      len([m for m in ss.messages if m["role"] == "user"]) == n0 + 1 and ss["sim_data"]["net2"]["field"] == "number")


# ═════════════════════════════════════════════════════════════════════════════
section("11. input_source logged for typed / button / form")
# ═════════════════════════════════════════════════════════════════════════════
fresh(None); run()
run("quero simular um BESS")
check("typed → 'typed'", last_user_row()["input_source"] == "typed")
click(next(b for b in option_buttons() if b[1] == "ONS (PAR/PEL)"))
check("button → 'button', shown text is the canonical answer",
      last_user_row()["input_source"] == "button" and last_user_row()["message"] == "ONS (PAR/PEL)")
fill_and_submit({"years": "2028"}); run()
check("form → 'form'", last_user_row()["input_source"] == "form" and last_user_row()["message"] == "2028")
check("assistant rows carry no input_source",
      all(r["input_source"] is None for r in rows("SELECT input_source FROM chat_logs WHERE role='assistant'")))
check("chat_logs.input_source values are only typed/button/form",
      {r["input_source"] for r in rows("SELECT input_source FROM chat_logs WHERE role='user'")} <= {"typed", "button", "form"})


# ═════════════════════════════════════════════════════════════════════════════
section("12. study panel: progress, edit (✏️), invalidation map")
# ═════════════════════════════════════════════════════════════════════════════
def edit_button(field):
    return next(e for e in events("button") if e[2] == f"edit_{field}")


fresh(None); run()
check("panel hidden when no simulation is active", not any(e[0] == "markdown" and "Estudo atual" in e[1] for e in EV))
setup("STEP8", BESS_FULL)
check("panel shown with 'Passo N de M' progress",
      any(e[0] == "progress" and e[2] and e[2].startswith("Passo 7 de 12") for e in EV))
shown = " ".join(e[1] for e in EV if e[0] == "markdown")
check("collected parameters listed (base, ano, cenário, barra, modo, S, P)",
      all(x in shown for x in ["PAR/PEL (ONS)", "2028", "Inverno Máxima Diurna", "1001", "PV (controle", "100 MVA", "80 MW"]))
check("✏️ next to each parameter", all(any(e[2] == f"edit_{f}" for e in events("button"))
                                      for f in ["db", "years", "scenario", "bess_bus", "bess_mode", "bess_mva", "bess_p_mw"]))
e = edit_button("bess_bus"); e[3](*e[4]); run()
check("✏️ re-asks only that question (and offers a form for it)",
      "Alterar barra" in last_assistant()["content"] and events("submit"))
fill_and_submit({"bus": "2002"}); run()
check("changing the bus mid-flow returns to the current step (STEP8, new bus question)",
      ss["sim_step"] == "STEP8" and ss["sim_data"]["bess_bus"] == "2002"
      and ss["sim_data"]["bess_mva"] == "100" and "nova barra da BESS" in last_assistant()["content"]
      and "_edit_pending" not in ss)

setup("STEP8", BESS_FULL)
e = edit_button("db"); e[3](*e[4]); run()
click(next(b for b in option_buttons() if b[1] == "EPE (PDE)"))
d = ss["sim_data"]
check("changing the database clears year and scenario (back to the year question)",
      d["db"] == "EPE" and not any(k in d for k in ("years", "year", "scenario")) and ss["sim_step"] == "STEP2")
check("…and the device parameters (bus numbers belong to the old base)", not any(k.startswith("bess_") for k in d))

setup("STEP7", dict(LOADED, bess_bus="1001"))
e = edit_button("years"); e[3](*e[4]); run()
run("2030")
check("changing the year keeps the scenario and the step",
      ss["sim_data"]["years"] == [2030] and ss["sim_data"]["year"] == 2030
      and ss["sim_data"]["scenario"] == "Inverno Máxima Diurna" and ss["sim_step"] == "STEP7"
      and "Carregue no ANAREDE o caso do ano **2030**" in last_assistant()["content"])
setup("STEP4", LOADED)
e = edit_button("scenario"); e[3](*e[4]); run()
click(next(b for b in option_buttons() if b[1] == "Verão Máxima Noturna"))
check("changing the scenario at STEP4 re-shows the SAV hint for the new case",
      ss["sim_data"]["scenario"] == "Verão Máxima Noturna" and ss["sim_step"] == "STEP4"
      and "Verão Máxima Noturna" in last_assistant()["content"] and "Restabelecer" in last_assistant()["content"])

setup("STEP10", dict(BESS_FULL, bess_bus_number="9999"))
e = edit_button("bess_mva"); e[3](*e[4]); run()
run("150 MVA")
exp = generate_dbar_block(bus_number="1001", bess_bus_number="9999", bus_type="1", S_mva=150.0, P_mw=80.0)
check("device change after the PWF was generated: block regenerated, back to STEP9 (save)",
      ss["sim_step"] == "STEP9" and f"```\n{exp}\n```" in last_assistant()["content"]
      and any(e[0] == "download" and e[3] == exp.replace("\n", "\r\n").encode() for e in EV))
setup("STEP11", {"sim_type": "STATCOM", "db": "ONS", "years": [2028], "year": 2028, "scenario": "x",
                 "statcom_bus": "1500", "statcom_q_min": -100.0, "statcom_q_max": 100.0})
e = edit_button("statcom_q"); e[3](*e[4]); run()
fill_and_submit({"qmin": "-50", "qmax": "60"}); run()
check("STATCOM Q change after the block: back to the controlled-bus question (regenerates the block)",
      ss["sim_step"] == "STATCOM_STEP_CBUS" and (ss["sim_data"]["statcom_q_min"], ss["sim_data"]["statcom_q_max"]) == (-50.0, 60.0))

setup("STEP8", BESS_FULL)
before = sim_state()
e = edit_button("bess_mva"); e[3](*e[4]); run()
run("abc")
check("unrecognised answer: re-asks, nothing changed, edit still pending",
      sim_state() == before and "_edit_pending" in ss and "Não identifiquei" in last_assistant()["content"])
run("cancelar")
check("'cancelar' keeps the value and returns to the step question", sim_state() == before and "_edit_pending" not in ss)
e = edit_button("bess_mva"); e[3](*e[4]); run()
run("encerrar")
check("'encerrar' during an edit ends the simulation as usual", ss["sim_step"] == "IDLE" and "_edit_pending" not in ss)

setup("STEP8", BESS_FULL, status="paused")
check("paused: progress + Retomar shown, no ✏️", not any(e[2] and e[2].startswith("edit_") for e in events("button"))
      and any(e[0] == "button" and e[1] == "▶️ Retomar" for e in EV))
setup("NET3_LINES", netdata(net3={"total": 1, "idx": 0, "field": "from_bus", "current": {}}))
shown = " ".join(e[1] for e in EV if e[0] == "markdown")
check("NETWORK panel: title, base, bus and line counts; progress 3 of 7",
      "Título: **Meu Caso**" in shown and "Barras: **2**" in shown and "Linhas: **0**" in shown
      and any(e[0] == "progress" and e[2].startswith("Passo 3 de 7") for e in EV))
e = edit_button("net_title"); e[3](*e[4]); run()
fill_and_submit({"title": "Rede Teste 3 Barras"}); run()
check("NETWORK title editable; returns to the current line question",
      ss["sim_data"]["network"]["title"] == "Rede Teste 3 Barras" and ss["sim_step"] == "NET3_LINES"
      and ss["sim_data"]["net3"]["field"] == "from_bus")


# ═════════════════════════════════════════════════════════════════════════════
section("13. Minhas conversas: a user only ever sees their own sessions")
# ═════════════════════════════════════════════════════════════════════════════
H.add_user("userB", "b@t")
svc.create_session("sessB", "userB")
svc.log_chat_message("userB", "sessB", "user", "SEGREDO DO USUARIO B", "IDLE", message_id="b1")
svc.log_chat_message("userB", "sessB", "assistant", "resposta para B", "IDLE", message_id="b2")
fresh(None, session_id="sessA2"); run(); run("pergunta de A")
mine = svc.list_user_sessions("userA")
check("list_user_sessions(A) lists only A's sessions", mine and all(s["id"] != "sessB" for s in mine)
      and {r["user_id"] for r in rows("SELECT user_id FROM sessions WHERE id IN (%s)" % ",".join("?" * len(mine)),
                                      [s["id"] for s in mine])} == {"userA"})
check("A cannot load B's transcript even with B's session id (SQL filter)", svc.get_user_session_messages("userA", "sessB") == [])
check("B still sees their own transcript", [m["message"] for m in svc.get_user_session_messages("userB", "sessB")]
      == ["SEGREDO DO USUARIO B", "resposta para B"])
check("unknown / malformed ids return nothing", svc.get_user_session_messages("userA", "nope'; --") == [])
src = open("auth/auth_service.py", encoding="utf-8").read()
check("both queries filter by user_id server-side",
      "WHERE s.user_id = %s::uuid" in src and "AND s.user_id = %s::uuid" in src and "AND cl.user_id = %s::uuid" in src)

ss["_view"] = "history"; run()
opens = [e for e in events("button") if e[2] and e[2].startswith("hist_open_")]
check("history list shows A's sessions only, with date/type/last step/count", opens
      and all("sessB" not in e[2] for e in opens)
      and any(e[0] == "caption" and "mensagens" in e[1] and "Último passo" in e[1] for e in EV))
check("chat input hidden while browsing history", not any(e[0] == "stream" for e in EV))
ss["_history_open"] = "sessB"; run()                      # direct id injection
rendered = " ".join(str(e[1]) for e in EV if e[0] in ("markdown", "caption", "info"))
check("injecting B's session id in the app renders nothing of B ('Conversa não encontrada')",
      "SEGREDO" not in rendered and any(e[0] == "info" and "não encontrada" in e[1] for e in EV))
ss["_history_open"] = "sessA2"; run()
check("opening own session: read-only chat bubbles, no widgets",
      any(e[:2] == ("enter", "chat") for e in EV) and "pergunta de A" in rendered + " ".join(str(e[1]) for e in EV if e[0] == "markdown")
      and not events("feedback") and not option_buttons())
new = next(e for e in events("button") if e[1] == "➕ Nova conversa"); new[3](*new[4])
check("'Nova conversa' returns to a fresh chat in a new session",
      ss["_view"] == "chat" and ss["session_id"] != "sessA2" and len(ss.messages) == 1 and ss["sim_step"] == "IDLE")


# ═════════════════════════════════════════════════════════════════════════════
section("14. modo iniciante / especialista (persisted per user) + glossary")
# ═════════════════════════════════════════════════════════════════════════════
pw = bcrypt.hashpw(b"segredo1", bcrypt.gensalt()).decode()
H.lite.execute("INSERT INTO users (id, email, password_hash, full_name, last_seen_version) VALUES ('userM','m@t',?,'M','v6.5.0')", (pw,))
H.lite.commit()
u = svc.login("m@t", "segredo1")
check("default mode is iniciante (column default)", u["ui_mode"] == "iniciante")
fresh(None, step="STEP6", data=LOADED, status="active", user=u); run(); run("vou desenhar")
m = last_assistant()
check("iniciante: secondary text in the 'Detalhes' expander", ("expander", "Detalhes") in EV
      and any(e[0] == "markdown" and e[1] == m["details"] for e in EV))
check("iniciante: inline glossary for terms in the latest message",
      ("expander", "📖 Termos desta mensagem") in EV or not find_terms(m["content"]))
tog = next(e for e in events("input") if e[1] == "toggle")
ss["_ui_mode_toggle"] = True; tog[4](*tog[5])
check("toggle saves ui_mode='especialista' for the user", rows("SELECT ui_mode FROM users WHERE id='userM'")[0]["ui_mode"] == "especialista")
run()
check("especialista: question visible, secondary text hidden (not even in an expander)",
      ("expander", "Detalhes") not in EV and not any(e[0] == "markdown" and m["details"] in e[1] for e in EV)
      and any(e[0] == "markdown" and "Qual é a barra" in e[1] for e in EV))
check("especialista: no inline glossary", ("expander", "📖 Termos desta mensagem") not in EV)
u2 = svc.login("m@t", "segredo1")
check("setting persists across logins", u2["ui_mode"] == "especialista")
ch = StreamChain(["Resposta curta."], scores(("a.pdf", 0.8)))
fresh(ch, user=u2); run(); run("O que é um STATCOM?")
check("especialista RAG: concise instruction added to the per-request context, question unchanged",
      "modo especialista" in ch.last_inputs["study_context"] and ch.last_inputs["question"] == "O que é um STATCOM?")
ch = StreamChain(["Resposta."], scores(("a.pdf", 0.8)))
fresh(ch, user=dict(u2, ui_mode="iniciante")); run(); run("O que é um STATCOM?")
check("iniciante RAG: no extra instruction", "modo especialista" not in ch.last_inputs["study_context"])
check("system prompt file untouched by this feature", "modo especialista" not in open("prompts/system_prompt.py", encoding="utf-8").read())
TERMS = ["PV", "PQ", "Referência", "SAV", "PWF", "LST", "DBAR", "DLIN", "DCER", "DCTG", "N-1", "hachura", "MVA", "Mvar", "pu"]
check("glossary covers all 15 terms, marked pending expert review",
      list(GLOSSARY) == TERMS and GLOSSARY_STATUS == "PENDING REVIEW BY DOMAIN EXPERT")
check("sidebar '📖 Glossário' entry", ("expander", "📖 Glossário") in EV)
check("term matching: acronyms exact, words case-insensitive",
      find_terms("Barra PV ou PQ em pu, hachura vermelha, N-1") == ["PV", "PQ", "N-1", "hachura", "pu"]
      and find_terms("pular puro PVC") == [])
try:
    svc.set_ui_mode("userM", "hacker"); bad = False
except ValueError:
    bad = True
check("invalid ui_mode rejected", bad)


# ═════════════════════════════════════════════════════════════════════════════
section("15. feedback, stuck analysis and admin with input_source rows")
# ═════════════════════════════════════════════════════════════════════════════
from agents.session_analysis import summarize_session, analyze_session
fresh(None, session_id="sessS"); run()
run("quero simular um BESS")
click(next(b for b in option_buttons() if b[1] == "ONS (PAR/PEL)"))
for _ in range(3):
    run("não sei o ano")                  # rejected 3× → stuck at STEP2
fill_and_submit({"years": "2028"}); run()
m = last_assistant()
_, _, oc, args = next(e for e in events("feedback") if m["message_id"] in e[1])
ss[f"fb_thumbs_{m['message_id']}"] = 0; oc(*args)
logs = [r for r in svc.get_chat_logs(user_id="userA") if r["session_id"] == "sessS"]
check("get_chat_logs returns input_source", {r["input_source"] for r in logs if r["role"] == "user"} == {"typed", "button", "form"})
sess = svc.get_session_summary("sessS")
fb = [dict(r) for r in rows("SELECT * FROM feedback WHERE session_id='sessS'")]
summ = summarize_session(sess, logs, fb)
check("stuck detection still flags STEP2 (3 turns without advancing)", "STEP2" in summ["analysis"]["not_advancing"], summ["analysis"])
check("feedback row attached to the session (👎)", summ["thumbs_down_count"] == 1)
spec = importlib.util.spec_from_file_location("admin_panel_t", "admin/panel.py")
panel = importlib.util.module_from_spec(spec); spec.loader.exec_module(panel)
EV.clear()
panel._render_transcript(sess, logs, fb, lambda *a: None)
caps = [e[1] for e in EV if e[0] == "caption"]
check("admin transcript renders and labels the input source",
      any("via botão" in c for c in caps) and any("via formulário" in c for c in caps) and any("via digitado" in c for c in caps))


H.finish()
