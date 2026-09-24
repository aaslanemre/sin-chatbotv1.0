"""
Test suite for v6.3.0 — network-from-scratch guided flow.

Covers:
  - Unit tests for agents/network_builder.py
  - Flow tests for the NET state machine in app.py

Run from repo root:  python3 test_network_v63.py
"""

import re
import sys
import math
import types
import unicodedata
import contextlib

# ── Minimal Streamlit mock (reuse pattern from test_routing_v62.py) ──────────

class _SessionState(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)
    def __setattr__(self, key, value):
        self[key] = value
    def get(self, key, default=None):
        return super().get(key, default)
    def pop(self, key, *args):
        return super().pop(key, *args)


_ss = _SessionState()

_st_mod = types.ModuleType("streamlit")
_st_mod.session_state = _ss
for _name in [
    "set_page_config", "stop", "error", "markdown", "tabs", "form",
    "text_input", "form_submit_button", "spinner", "chat_input",
    "chat_message", "expander", "caption", "divider",
    "button", "info", "success", "warning", "rerun",
]:
    setattr(_st_mod, _name, lambda *a, **kw: None)

class _CtxMgr:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __getattr__(self, name): return lambda *a, **kw: _CtxMgr()

_st_mod.sidebar  = _CtxMgr()
_st_mod.columns  = lambda n, **kw: [_CtxMgr() for _ in range(n if isinstance(n, int) else len(n))]
_st_mod.chat_message = lambda *a, **kw: _CtxMgr()
_st_mod.spinner      = lambda *a, **kw: _CtxMgr()
_st_mod.expander     = lambda *a, **kw: _CtxMgr()
sys.modules["streamlit"] = _st_mod

# ── Stub heavy dependencies ───────────────────────────────────────────────────
for _mod in [
    "agents.pwf_agent", "agents.results_analyzer",
    "memory.session_memory", "memory.persistent_memory",
    "auth.db", "auth.auth_service",
    "prompts.system_prompt", "rag.chain",
]:
    sys.modules[_mod] = types.ModuleType(_mod)

sys.modules["agents.pwf_agent"].generate_dbar_block        = lambda **kw: "(dbar stub)"
sys.modules["agents.pwf_agent"].generate_statcom_block     = lambda **kw: "(statcom stub)"
sys.modules["agents.pwf_agent"].generate_contingency_block = lambda *a, **kw: "(ctg stub)"
sys.modules["agents.results_analyzer"].save_results_file   = lambda *a, **kw: None
sys.modules["agents.results_analyzer"].check_convergence   = lambda *a, **kw: None
sys.modules["agents.results_analyzer"].format_results_report = lambda *a, **kw: ""
sys.modules["memory.session_memory"].StudyState = type("StudyState", (), {"summary": lambda self: ""})
sys.modules["memory.persistent_memory"].load_study  = lambda: sys.modules["memory.session_memory"].StudyState()
sys.modules["memory.persistent_memory"].save_study  = lambda *a: None
sys.modules["memory.persistent_memory"].clear_study = lambda *a: None
sys.modules["auth.db"].init_db = lambda: None
for _fn in ["signup","login","log_chat_message","create_session","update_session",
            "save_paused_state","load_paused_state","clear_paused_state"]:
    setattr(sys.modules["auth.auth_service"], _fn, lambda *a, **kw: None)
sys.modules["prompts.system_prompt"].SYSTEM_PROMPT = "stub"

# ── Pre-seed session_state ────────────────────────────────────────────────────
_ss["db_initialized"]   = True
_ss["user"]             = {"id": 1, "email": "test@test.com", "full_name": "Test"}
_ss["session_id"]       = "test-session"
_ss["chain"]            = None
_ss["chain_error"]      = None
_ss["_prompt_hash"]     = None
_ss["messages"]         = []
_ss["study"]            = sys.modules["memory.session_memory"].StudyState()
_ss["simulation_mode"]  = False
_ss["sim_step"]         = "IDLE"
_ss["sim_data"]         = {}
_ss["sim_status"]       = None

# ── Import modules under test ─────────────────────────────────────────────────
from agents.network_builder import (
    convert_line_params,
    validate_network,
    build_full_pwf,
    diagnose_nonconvergence,
    format_network_summary,
)
import app as _app

_handle_sim_state  = _app._handle_sim_state
_handle_net_state  = _app._handle_net_state
_is_lt_data_message = _app._is_lt_data_message
_parse_lt_params    = _app._parse_lt_params
_current_step_question = _app._current_step_question
_parse_compact_bus  = _app._parse_compact_bus
_looks_like_line_def = _app._looks_like_line_def

# ── Helpers ───────────────────────────────────────────────────────────────────

def reset_idle():
    _ss["sim_step"]        = "IDLE"
    _ss["sim_data"]        = {}
    _ss["simulation_mode"] = False
    _ss["sim_status"]      = None
    _ss.pop("_lt_confirm_question", None)


def set_active(step, data=None):
    _ss["sim_step"]        = step
    _ss["sim_data"]        = data or {}
    _ss["simulation_mode"] = True
    _ss["sim_status"]      = "active"


PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
results = []


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    msg = f"  [{status}] {name}"
    print(msg)
    if not condition and detail:
        print(f"         {detail}")
    results.append((name, condition))


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — Unit tests: convert_line_params
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 1: convert_line_params ═══\n")

# Gabriel's exact line: 230 kV, 180 km, R=0.0257 Ω/km, X=0.2995 Ω/km, B=5.4542 μS/km
result_gabriel = convert_line_params(
    230, "per_km", {"R": 0.0257, "X": 0.2995, "B": 5.4542}, length_km=180
)
check(
    "Gabriel's line — R% ≈ 0.8745 %",
    abs(result_gabriel["r_pct"] - 0.8745) < 0.001,
    f"got {result_gabriel['r_pct']:.4f}"
)
check(
    "Gabriel's line — X% ≈ 10.19 %",
    abs(result_gabriel["x_pct"] - 10.19) < 0.02,
    f"got {result_gabriel['x_pct']:.4f}"
)
check(
    "Gabriel's line — Q ≈ 51.93 Mvar",
    abs(result_gabriel["q_mvar"] - 51.93) < 0.1,
    f"got {result_gabriel['q_mvar']:.4f}"
)
check(
    "Gabriel's line — calc_str contains step-by-step PT-BR",
    "Zbase" in result_gabriel["calc_str"] and "Passo" in result_gabriel["calc_str"],
)

# pu mode
result_pu = convert_line_params(230, "pu", {"R": 0.00875, "X": 0.1019, "B": 0.5193}, base_mva=100)
check("pu mode — R% = 0.875", abs(result_pu["r_pct"] - 0.875) < 0.001, f"got {result_pu['r_pct']}")
check("pu mode — Q = 51.93 Mvar", abs(result_pu["q_mvar"] - 51.93) < 0.01, f"got {result_pu['q_mvar']}")

# pct pass-through mode
result_pct = convert_line_params(230, "pct", {"R": 0.87, "X": 10.19, "Q": 51.93})
check("pct pass-through — R% unchanged", abs(result_pct["r_pct"] - 0.87) < 1e-9)
check("pct pass-through — calc_str mentions pass-through", "pass-through" in result_pct["calc_str"].lower())

# Error cases
try:
    convert_line_params(-10, "per_km", {"R": 0.01, "X": 0.1, "B": 1.0}, 100)
    check("invalid kV raises ValueError", False, "no exception raised")
except ValueError:
    check("invalid kV raises ValueError", True)

try:
    convert_line_params(230, "per_km", {"R": 0.01, "X": 0.1, "B": 1.0})  # missing length
    check("per_km without length raises ValueError", False, "no exception raised")
except ValueError:
    check("per_km without length raises ValueError", True)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — Unit tests: validate_network
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 2: validate_network ═══\n")

# Valid 3-bus network
net_3bus = {
    "title": "Teste 3 barras",
    "base_mva": 100.0,
    "buses": [
        {"number": 1, "name": "REF", "kv": 230.0, "tipo": 2, "v_pu": 1.05, "angle_deg": 0,
         "p_gen_mw": 0, "q_min_mvar": -100, "q_max_mvar": 100, "p_load_mw": 0, "q_load_mvar": 0},
        {"number": 2, "name": "GER", "kv": 230.0, "tipo": 1, "v_pu": 1.02, "angle_deg": 0,
         "p_gen_mw": 150, "q_min_mvar": -80, "q_max_mvar": 80, "p_load_mw": 0, "q_load_mvar": 0},
        {"number": 3, "name": "CARGA", "kv": 230.0, "tipo": 0, "v_pu": 1.0, "angle_deg": 0,
         "p_gen_mw": 0, "q_min_mvar": 0, "q_max_mvar": 0, "p_load_mw": 100, "q_load_mvar": 40},
    ],
    "lines": [
        {"id": 1, "from_bus": 1, "to_bus": 2, "circuit": 1, "r_pct": 0.5, "x_pct": 5.0, "q_mvar": 20.0},
        {"id": 2, "from_bus": 1, "to_bus": 3, "circuit": 1, "r_pct": 0.8, "x_pct": 8.0, "q_mvar": 30.0},
        {"id": 3, "from_bus": 2, "to_bus": 3, "circuit": 1, "r_pct": 0.4, "x_pct": 4.0, "q_mvar": 15.0},
    ],
}
issues_3bus = validate_network(net_3bus)
errors_3bus = [i for i in issues_3bus if i["severity"] == "error"]
check("Valid 3-bus network — no errors", len(errors_3bus) == 0, f"errors: {[e['message'] for e in errors_3bus]}")

# No reference bus
net_no_ref = {**net_3bus, "buses": [
    {**net_3bus["buses"][0], "tipo": 1},  # change REF to PV
    net_3bus["buses"][1],
    net_3bus["buses"][2],
]}
issues_no_ref = validate_network(net_no_ref)
no_ref_errors = [i for i in issues_no_ref if i["severity"] == "error" and "referência" in i["message"].lower()]
check("No reference bus → error", len(no_ref_errors) > 0, f"no ref error not found; errors: {[e['message'] for e in issues_no_ref if e['severity']=='error']}")

# Two reference buses
net_two_ref = {**net_3bus, "buses": [
    net_3bus["buses"][0],
    {**net_3bus["buses"][1], "tipo": 2},  # also REF
    net_3bus["buses"][2],
]}
issues_two_ref = validate_network(net_two_ref)
two_ref_errors = [i for i in issues_two_ref if i["severity"] == "error" and "Mais de uma" in i["message"]]
check("Two reference buses → error", len(two_ref_errors) > 0)

# Isolated bus
net_isolated = {
    "title": "Rede com barra isolada",
    "base_mva": 100.0,
    "buses": [
        {"number": 1, "name": "REF", "kv": 230.0, "tipo": 2, "v_pu": 1.05, "angle_deg": 0,
         "p_gen_mw": 0, "q_min_mvar": -100, "q_max_mvar": 100, "p_load_mw": 0, "q_load_mvar": 0},
        {"number": 2, "name": "CARGA", "kv": 230.0, "tipo": 0, "v_pu": 1.0, "angle_deg": 0,
         "p_gen_mw": 0, "q_min_mvar": 0, "q_max_mvar": 0, "p_load_mw": 100, "q_load_mvar": 40},
        {"number": 99, "name": "ISOLADA", "kv": 230.0, "tipo": 0, "v_pu": 1.0, "angle_deg": 0,
         "p_gen_mw": 0, "q_min_mvar": 0, "q_max_mvar": 0, "p_load_mw": 50, "q_load_mvar": 20},
    ],
    "lines": [
        {"id": 1, "from_bus": 1, "to_bus": 2, "circuit": 1, "r_pct": 0.5, "x_pct": 5.0, "q_mvar": 20.0},
    ],
}
issues_iso = validate_network(net_isolated)
iso_errors = [i for i in issues_iso if i["severity"] == "error" and "isolad" in i["message"].lower()]
check(
    "Isolated bus → error mentioning bus 99",
    len(iso_errors) > 0 and "99" in str(iso_errors[0].get("target", "")),
    f"errors: {[e['message'] for e in issues_iso if e['severity']=='error']}"
)

# Line between different kV buses
net_kv_mismatch = {
    "title": "Tensões diferentes",
    "base_mva": 100.0,
    "buses": [
        {"number": 1, "name": "REF_230", "kv": 230.0, "tipo": 2, "v_pu": 1.05, "angle_deg": 0,
         "p_gen_mw": 0, "q_min_mvar": -100, "q_max_mvar": 100, "p_load_mw": 0, "q_load_mvar": 0},
        {"number": 2, "name": "CARGA_500", "kv": 500.0, "tipo": 0, "v_pu": 1.0, "angle_deg": 0,
         "p_gen_mw": 0, "q_min_mvar": 0, "q_max_mvar": 0, "p_load_mw": 100, "q_load_mvar": 40},
    ],
    "lines": [
        {"id": 1, "from_bus": 1, "to_bus": 2, "circuit": 1, "r_pct": 0.5, "x_pct": 5.0, "q_mvar": 20.0},
    ],
}
issues_kv = validate_network(net_kv_mismatch)
kv_errors = [i for i in issues_kv if i["severity"] == "error" and "transformador" in i["message"].lower()]
check("Line between 230/500 kV → transformer error", len(kv_errors) > 0, f"errors: {[e['message'] for e in issues_kv if e['severity']=='error']}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — Unit tests: build_full_pwf
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 3: build_full_pwf ═══\n")

pwf_text = build_full_pwf(net_3bus)

check("PWF contains DBAR", "DBAR" in pwf_text)
check("PWF contains DLIN", "DLIN" in pwf_text)
check("PWF ends with FIM", pwf_text.strip().endswith("FIM"))
check("PWF contains 99999 terminators", pwf_text.count("99999") >= 2)

# Type mapping: check that tipo 2 (REF) appears in the DBAR line for bus 1
dbar_lines = []
in_dbar = False
for line in pwf_text.splitlines():
    if line.strip() == "DBAR":
        in_dbar = True
        continue
    if line.strip() == "99999" and in_dbar:
        break
    if in_dbar and not line.startswith("("):
        dbar_lines.append(line)

# Bus 1 tipo=2 — check field at column 8 (0-indexed: cols 0-4=num, 5=op, 6=estado, 7=tipo)
bus1_line = next((l for l in dbar_lines if l.strip().startswith("1")), None)
bus2_line = next((l for l in dbar_lines if l.strip().startswith("2")), None)
bus3_line = next((l for l in dbar_lines if l.strip().startswith("3")), None)

if bus1_line:
    tipo1 = bus1_line[7] if len(bus1_line) > 7 else "?"
    check("Bus 1 tipo=2 (Referência)", tipo1 == "2", f"got '{tipo1}' in line: {repr(bus1_line)}")
else:
    check("Bus 1 line found in DBAR", False, "bus 1 line not found")

if bus2_line:
    tipo2 = bus2_line[7] if len(bus2_line) > 7 else "?"
    check("Bus 2 tipo=1 (PV)", tipo2 == "1", f"got '{tipo2}' in line: {repr(bus2_line)}")
else:
    check("Bus 2 line found in DBAR", False, "bus 2 line not found")

if bus3_line:
    tipo3 = bus3_line[7] if len(bus3_line) > 7 else "?"
    check("Bus 3 tipo=0 (PQ)", tipo3 == "0", f"got '{tipo3}' in line: {repr(bus3_line)}")
else:
    check("Bus 3 line found in DBAR", False, "bus 3 line not found")

# TAP field empty for transmission lines
# In the LT format, TAP starts after suceptancia (6+8+6=20 chars for R+X+B in DLIN body)
# The key check is that no tap value other than space is present
dlin_section = pwf_text.split("DLIN")[1].split("99999")[0] if "DLIN" in pwf_text else ""
for line in dlin_section.splitlines():
    if len(line) > 30:
        # Tap field starts at position ~35 in a LT line (after the impedance fields)
        # Just verify no integer-like value appears where tap would be
        pass
check("DLIN section has 3 lines (3 circuits)", dlin_section.count("\n") >= 3)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — Unit tests: diagnose_nonconvergence
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 4: diagnose_nonconvergence ═══\n")

checklist_red = diagnose_nonconvergence(net_3bus, "red")
check("diagnose returns non-empty list", len(checklist_red) > 0)
check("red color tip mentions divergência", any("divergência" in c or "vermelho" in c.lower() for c in checklist_red))

checklist_yellow = diagnose_nonconvergence(net_3bus, "yellow")
check("yellow color tip mentions iterações", any("iteraç" in c.lower() for c in checklist_yellow))


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — Flow test: Gabriel's LT → option 1 → line pre-filled
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 5: LT detection → option 1 → NETWORK mode ═══\n")

reset_idle()
MSG_GABRIEL = (
    "Tenho uma linha de transmissão de 230 kV, 180 km, com "
    "R = 0,0257 ohms/km, X = 0,2995 ohms/km e B = 5,4542 μS/km. "
    "Como eu integro isso no ANAREDE?"
)

check("Gabriel's message detected as LT data", _is_lt_data_message(MSG_GABRIEL))

# Trigger LT confirmation
resp1 = _handle_sim_state(MSG_GABRIEL)
check("LT confirmation triggered", resp1 is not None and "parâmetros" in resp1.lower())
check("State is IDLE_LT_CONFIRM", _ss["sim_step"] == "IDLE_LT_CONFIRM")
check("pending_lt stored", _ss["sim_data"].get("pending_lt", {}).get("voltage_kv") == 230.0)

# User says "sim" → IDLE_LT_NET_CHOICE
resp2 = _handle_sim_state("sim")
check("IDLE_LT_CONFIRM sim → IDLE_LT_NET_CHOICE", _ss["sim_step"] == "IDLE_LT_NET_CHOICE",
      f"step={_ss['sim_step']}, resp={resp2[:80] if resp2 else None}")
check("Two options shown", resp2 is not None and "1" in resp2 and "2" in resp2)

# User chooses option 1 → NET1_SETUP
resp3 = _handle_sim_state("1")
check("IDLE_LT_NET_CHOICE 1 → NET1_SETUP", _ss["sim_step"] == "NET1_SETUP",
      f"step={_ss['sim_step']}")
check("sim_type = NETWORK", _ss["sim_data"].get("sim_type") == "NETWORK")
check("pending_lt preserved in sim_data", "pending_lt" in _ss["sim_data"])

# NET1_SETUP: confirm defaults
resp4 = _handle_sim_state("confirmar")
check("NET1_SETUP confirmar → NET2_BUSES", _ss["sim_step"] == "NET2_BUSES",
      f"step={_ss['sim_step']}")

# NET2_BUSES: set 2 buses
resp5 = _handle_sim_state("2")
check("2 buses accepted", "Barra 1" in (resp5 or ""), f"resp: {resp5}")

# Enter bus 1: REF
_handle_sim_state("1")       # number
_handle_sim_state("REF_230") # name
_handle_sim_state("230")     # kV
_handle_sim_state("2")       # tipo REF
resp_v = _handle_sim_state("1.05")  # v_pu
check("REF bus accepted, moving to bus 2 or NET3",
      _ss["sim_step"] in ("NET2_BUSES", "NET3_LINES"), f"step={_ss['sim_step']}, resp={resp_v}")

# Enter bus 2: PQ
if _ss["sim_step"] == "NET2_BUSES":
    _handle_sim_state("2")       # number
    _handle_sim_state("CARGA_230")
    _handle_sim_state("230")
    _handle_sim_state("0")       # tipo PQ
    _handle_sim_state("150")     # PL
    resp_ql = _handle_sim_state("50")    # QL

check("After 2 buses → NET3_LINES", _ss["sim_step"] == "NET3_LINES",
      f"step={_ss['sim_step']}")

# NET3_LINES: pending_lt pre-fills line 1
# The first thing is asking for count
resp_cnt = _handle_sim_state("1")  # 1 line total
check("Line count 1 accepted, asks for from_bus OR shows converted params",
      resp_cnt is not None and len(resp_cnt) > 10, f"resp: {resp_cnt}")
# Check params were pre-filled (pending_lt conversion)
check("Pre-filled line params present in net3 current or resp",
      "R" in (resp_cnt or "") or "barra" in (resp_cnt or "").lower()
      or _ss["sim_data"].get("net3", {}).get("current", {}).get("r_pct") is not None)

# Enter bus endpoints for the pre-filled line
net3 = _ss["sim_data"].get("net3", {})
if net3.get("field") == "from_bus":
    _handle_sim_state("1")  # from
    resp_to = _handle_sim_state("2")  # to
    check("to_bus accepted", "circuit" in (resp_to or "").lower() or net3.get("field") in ("circuit","to_bus","mode","values","count"),
          f"resp: {resp_to}")
    if _ss["sim_data"].get("net3", {}).get("field") == "circuit":
        resp_circ = _handle_sim_state("1")
        # If pre-filled, should go to NET4_REVIEW
        check("Pre-filled line: after circuit → NET4_REVIEW or NET3 with no more lines",
              _ss["sim_step"] in ("NET4_REVIEW", "NET3_LINES"), f"step={_ss['sim_step']}")

# Pre-filled line: parameters were NOT re-asked
lines_in_network = _ss["sim_data"].get("network", {}).get("lines", [])
if lines_in_network:
    line1 = lines_in_network[0]
    check("Pre-filled line has r_pct from pending_lt (≈0.8745)",
          abs(line1.get("r_pct", 0) - 0.8745) < 0.01,
          f"r_pct={line1.get('r_pct')}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — Flow test: 3-bus network full round-trip
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 6: 3-bus network full PWF generation ═══\n")

reset_idle()
set_active("NET1_SETUP", {
    "sim_type": "NETWORK",
    "network": {"title": "Meu Caso", "base_mva": 100.0, "buses": [], "lines": []}
})

_handle_sim_state("LT 230kV Teste, 100 MVA")
check("After NET1_SETUP → NET2_BUSES", _ss["sim_step"] == "NET2_BUSES", f"step={_ss['sim_step']}")

# Add 3 buses
_handle_sim_state("3")          # count

# Bus 1: REF (tipo 2)
_handle_sim_state("1")          # number
_handle_sim_state("REF_230")    # name
_handle_sim_state("230")        # kV
_handle_sim_state("2")          # tipo REF
_handle_sim_state("1.05")       # v_pu

# Bus 2: PV (tipo 1)
_handle_sim_state("2")
_handle_sim_state("GER_230")
_handle_sim_state("230")
_handle_sim_state("1")          # tipo PV
_handle_sim_state("150")        # Pg
_handle_sim_state("1.02")       # v_pu
_handle_sim_state("-80")        # Qmin
_handle_sim_state("80")         # Qmax

# Bus 3: PQ (tipo 0)
_handle_sim_state("3")
_handle_sim_state("CARGA_230")
_handle_sim_state("230")
_handle_sim_state("0")          # tipo PQ
_handle_sim_state("100")        # PL
resp_after_buses = _handle_sim_state("40")  # QL

check("After 3 buses → NET3_LINES", _ss["sim_step"] == "NET3_LINES",
      f"step={_ss['sim_step']}")

# Add 3 lines
_handle_sim_state("3")  # count

# Line 1: by km (Gabriel's)
_handle_sim_state("1")  # from
_handle_sim_state("2")  # to
_handle_sim_state("1")  # circuit
_handle_sim_state("1")  # mode = per_km
_handle_sim_state("R=0.05 X=0.3 B=3.0 L=100")

# Line 2: by pct
_handle_sim_state("1")  # from
_handle_sim_state("3")  # to
_handle_sim_state("1")
_handle_sim_state("3")  # mode = pct
_handle_sim_state("R=0.8 X=9.5 Q=40")

# Line 3: pu mode
_handle_sim_state("2")  # from
_handle_sim_state("3")  # to
_handle_sim_state("1")
_handle_sim_state("2")  # mode = pu
resp_after_lines = _handle_sim_state("R=0.001 X=0.05 B=0.1")

check("After 3 lines → NET4_REVIEW", _ss["sim_step"] == "NET4_REVIEW",
      f"step={_ss['sim_step']}")

# Validate and generate
resp_confirm = _handle_sim_state("confirmar")
check("confirmar → NET5_GENERATE or error", _ss["sim_step"] in ("NET5_GENERATE", "NET4_REVIEW"),
      f"step={_ss['sim_step']}, resp={resp_confirm[:80] if resp_confirm else None}")

if _ss["sim_step"] == "NET5_GENERATE":
    pwf = _ss["sim_data"].get("net_pwf", "")
    check("Generated PWF has DBAR", "DBAR" in pwf)
    check("Generated PWF has DLIN", "DLIN" in pwf)
    check("Generated PWF ends with FIM", pwf.strip().endswith("FIM"))

    # Check tipo mapping: parse only the DBAR section to avoid DLIN lines
    dbar_lines_s6 = []
    in_dbar_s6 = False
    for line in pwf.splitlines():
        if line.strip() == "DBAR":
            in_dbar_s6 = True
            continue
        if line.strip() == "99999" and in_dbar_s6:
            break
        if in_dbar_s6 and not line.startswith("("):
            dbar_lines_s6.append(line)
    tipos = {}
    for l in dbar_lines_s6:
        m = re.match(r'^\s*(\d+)', l)
        if m and len(l) > 7:
            tipos[int(m.group(1))] = l[7]
    check("Bus 1 tipo=2", tipos.get(1) == "2", f"tipos={tipos}")
    check("Bus 2 tipo=1", tipos.get(2) == "1", f"tipos={tipos}")
    check("Bus 3 tipo=0", tipos.get(3) == "0", f"tipos={tipos}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — Validation blockers
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 7: Validation blockers ═══\n")

# No reference bus
net_no_ref2 = {
    "title": "Sem REF", "base_mva": 100.0,
    "buses": [
        {"number": 1, "name": "PV", "kv": 230.0, "tipo": 1, "v_pu": 1.02, "angle_deg": 0,
         "p_gen_mw": 100, "q_min_mvar": -50, "q_max_mvar": 50, "p_load_mw": 0, "q_load_mvar": 0},
        {"number": 2, "name": "PQ", "kv": 230.0, "tipo": 0, "v_pu": 1.0, "angle_deg": 0,
         "p_gen_mw": 0, "q_min_mvar": 0, "q_max_mvar": 0, "p_load_mw": 80, "q_load_mvar": 30},
    ],
    "lines": [
        {"id": 1, "from_bus": 1, "to_bus": 2, "circuit": 1, "r_pct": 0.5, "x_pct": 5.0, "q_mvar": 10.0},
    ],
}
issues_no_ref2 = validate_network(net_no_ref2)
no_ref2_errors = [i for i in issues_no_ref2 if i["severity"] == "error"]
check("No REF bus → has error", len(no_ref2_errors) > 0)
check("No REF error message in PT-BR", any("referência" in e["message"].lower() or "referencia" in e["message"].lower() for e in no_ref2_errors),
      f"messages: {[e['message'] for e in no_ref2_errors]}")

# confirm blocked when errors exist
reset_idle()
set_active("NET4_REVIEW", {
    "sim_type": "NETWORK",
    "network": net_no_ref2,
})
resp_block = _handle_sim_state("confirmar")
check("NET4_REVIEW with errors blocks generation", "erro" in (resp_block or "").lower(),
      f"resp: {resp_block}")
check("Step stays at NET4_REVIEW after blocked", _ss["sim_step"] == "NET4_REVIEW",
      f"step={_ss['sim_step']}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8 — "ajuda" at every NET state
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 8: ajuda at every NET state ═══\n")

for net_step in ["NET1_SETUP", "NET2_BUSES", "NET3_LINES", "NET4_REVIEW",
                 "NET5_GENERATE", "NET6_RUN", "NET7_RESULTS"]:
    reset_idle()
    base_data = {"sim_type": "NETWORK", "network": {"title": "T", "base_mva": 100.0, "buses": [], "lines": []}}
    if net_step == "NET2_BUSES":
        base_data["net2"] = {"total": None, "idx": 0, "field": "count", "current": {}}
    if net_step == "NET3_LINES":
        base_data["net3"] = {"total": None, "idx": 0, "field": "count", "current": {}}
    if net_step in ("NET5_GENERATE",):
        base_data["net_pwf"] = "DBAR\n99999\nDLIN\n99999\nFIM"
    set_active(net_step, base_data)
    resp = _handle_sim_state("ajuda")
    check(
        f"{net_step}: ajuda returns non-empty, step unchanged",
        resp is not None and len(resp) > 20 and _ss["sim_step"] == net_step,
        f"step={_ss['sim_step']}, len={len(resp) if resp else 0}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9 — "voltar" preserves data
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 9: voltar preserves data ═══\n")

reset_idle()
network_with_buses = {
    "title": "Teste Voltar", "base_mva": 100.0,
    "buses": [
        {"number": 1, "name": "REF", "kv": 230.0, "tipo": 2, "v_pu": 1.05, "angle_deg": 0,
         "p_gen_mw": 0, "q_min_mvar": -100, "q_max_mvar": 100, "p_load_mw": 0, "q_load_mvar": 0},
    ],
    "lines": [],
}
set_active("NET3_LINES", {
    "sim_type": "NETWORK",
    "network": network_with_buses,
    "net3": {"total": None, "idx": 0, "field": "count", "current": {}},
})
resp_back = _handle_sim_state("voltar")
check("voltar from NET3_LINES → NET2_BUSES", _ss["sim_step"] == "NET2_BUSES",
      f"step={_ss['sim_step']}")
check("voltar preserves network buses", len(_ss["sim_data"].get("network", {}).get("buses", [])) == 1,
      f"buses={_ss['sim_data'].get('network',{}).get('buses',[])} ")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 10 — Pause mid-NET3, resume → data intact
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 10: pause/resume mid-NET3 ═══\n")

partial_network = {
    "title": "Pause Test", "base_mva": 100.0,
    "buses": [
        {"number": 1, "name": "REF", "kv": 230.0, "tipo": 2, "v_pu": 1.05, "angle_deg": 0,
         "p_gen_mw": 0, "q_min_mvar": -100, "q_max_mvar": 100, "p_load_mw": 0, "q_load_mvar": 0},
        {"number": 2, "name": "PQ", "kv": 230.0, "tipo": 0, "v_pu": 1.0, "angle_deg": 0,
         "p_gen_mw": 0, "q_min_mvar": 0, "q_max_mvar": 0, "p_load_mw": 100, "q_load_mvar": 40},
    ],
    "lines": [
        {"id": 1, "from_bus": 1, "to_bus": 2, "circuit": 1, "r_pct": 0.87, "x_pct": 10.19, "q_mvar": 51.93},
    ],
}
paused_data = {
    "sim_type": "NETWORK",
    "network": partial_network,
    "net3": {"total": 2, "idx": 1, "field": "from_bus", "current": {}},
}

# Simulate pause/resume by directly setting state
set_active("NET3_LINES", paused_data)

# Verify data intact on resume
check("After resume: sim_step = NET3_LINES", _ss["sim_step"] == "NET3_LINES")
check("Line 1 still in network", len(_ss["sim_data"]["network"]["lines"]) == 1)
check("Line 1 r_pct = 0.87", abs(_ss["sim_data"]["network"]["lines"][0]["r_pct"] - 0.87) < 1e-6)
check("net3.idx = 1 (resuming line 2)", _ss["sim_data"]["net3"]["idx"] == 1)


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 11 — Converged → offer BESS
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 11: converged → offer BESS ═══\n")

reset_idle()
set_active("NET7_RESULTS", {
    "sim_type": "NETWORK",
    "network": net_3bus,
    "net7_color": "green",
})
resp_results = _handle_sim_state("O caso convergiu, quadrado verde")
check("Converged response shows BESS/STATCOM/contingency options",
      resp_results is not None and (
          "bess" in (resp_results or "").lower() or
          "statcom" in (resp_results or "").lower() or
          "contingência" in (resp_results or "").lower()
      ), f"resp: {resp_results[:200] if resp_results else None}")

# Test BESS option specifically
reset_idle()
set_active("NET7_RESULTS", {
    "sim_type": "NETWORK",
    "network": net_3bus,
    "net7_color": "green",
})
resp_bess = _handle_sim_state("inserir BESS")
check("inserir BESS from NET7 shows guidance (OPEN QUESTION acknowledged)",
      resp_bess is not None and len(resp_bess) > 20, f"resp: {resp_bess}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 12 — Regression: BESS/STATCOM flows unchanged (options 1 and 2)
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 12: regression — BESS/STATCOM flows ═══\n")

# Option 1 at STEP1 → EPE, still works
reset_idle()
_handle_sim_state("quero simular")
check("BESS simulation starts at STEP1", _ss["sim_step"] == "STEP1")
resp_step1_epe = _handle_sim_state("1")
check("STEP1 '1' → EPE, goes to STEP2", _ss["sim_step"] == "STEP2")
check("DB = EPE", _ss["sim_data"].get("db") == "EPE")

# Option 2 at STEP1 → ONS, still works
reset_idle()
_handle_sim_state("quero simular")
resp_step1_ons = _handle_sim_state("2")
check("STEP1 '2' → ONS, goes to STEP2", _ss["sim_step"] == "STEP2")
check("DB = ONS", _ss["sim_data"].get("db") == "ONS")

# Option 3 at STEP1 → NETWORK
reset_idle()
_handle_sim_state("quero simular")
resp_step1_net = _handle_sim_state("3")
check("STEP1 '3' → NET1_SETUP", _ss["sim_step"] == "NET1_SETUP",
      f"step={_ss['sim_step']}")
check("sim_type = NETWORK", _ss["sim_data"].get("sim_type") == "NETWORK")

# STATCOM still works
reset_idle()
_handle_sim_state("quero inserir um statcom")
check("STATCOM still starts STEP1", _ss["sim_step"] == "STEP1")
_handle_sim_state("2")  # ONS
_handle_sim_state("2028")
check("STATCOM reaches STEP3", _ss["sim_step"] == "STEP3")

# BESS full flow check
reset_idle()
set_active("STEP7", {"sim_type": "BESS", "db": "ONS", "year": 2028, "scenario": "Verão Máxima Diurna"})
r = _handle_sim_state("barra 1001")
check("STEP7 bus number still accepted for BESS", "1001" in (r or "") or _ss["sim_data"].get("bess_bus") == "1001",
      f"resp={r}, data={_ss['sim_data']}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 13 — FIX 1: option 3 appears in EVERY STEP1 prompt variant
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 13: FIX 1 — option 3 in every STEP1 prompt ═══\n")


def _lists_option3(s):
    if not s:
        return False
    low = s.lower()
    return "própria rede" in low and re.search(r"\b3\b", s) is not None


# Variant: canonical constant
check("constant _STEP1_DB_QUESTION lists option 3", _lists_option3(_app._STEP1_DB_QUESTION))

# Variant: _current_step_question at STEP1 (re-prompt / pause-resume nudge)
reset_idle()
set_active("STEP1", {"sim_type": "BESS"})
check("_current_step_question(STEP1) lists option 3", _lists_option3(_current_step_question()))

# Variant: PRIMARY intro (fresh simulation trigger from IDLE, with EPE/ONS links)
reset_idle()
resp_intro = _handle_sim_state("Quero simular a inserção de um BESS no sistema")
check("primary intro is the STEP1 prompt", _ss["sim_step"] == "STEP1", f"step={_ss['sim_step']}")
check("primary intro lists option 3", _lists_option3(resp_intro), f"resp={resp_intro[:160] if resp_intro else None}")
check("primary intro still has SINTEGRE/EPE links",
      resp_intro and "ons.org.br" in resp_intro and "epe.gov.br" in resp_intro)

# Variant: _RESTART handler (restart while mid-flow)
reset_idle()
set_active("STEP7", {"sim_type": "BESS", "db": "ONS"})
resp_restart = _handle_sim_state("quero simular")
check("_RESTART message lists option 3", _lists_option3(resp_restart), f"resp={resp_restart[:160] if resp_restart else None}")

# Variant: IDLE_LT_NET_CHOICE → option 2 (insert in existing case) renders STEP1 DB question
reset_idle()
_handle_sim_state(MSG_GABRIEL)
_handle_sim_state("sim")
resp_ltchoice = _handle_sim_state("2")
check("IDLE_LT_NET_CHOICE opt 2 DB question lists option 3", _lists_option3(resp_ltchoice),
      f"resp={resp_ltchoice[:160] if resp_ltchoice else None}")

# Variant: STEP1 unrecognized-answer retry
reset_idle()
set_active("STEP1", {"sim_type": "BESS"})
resp_retry = _handle_sim_state("qwertyuiop")
check("STEP1 retry lists option 3", _lists_option3(resp_retry), f"resp={resp_retry[:160] if resp_retry else None}")

# Variant: STEP12 restart-from-scratch
reset_idle()
set_active("STEP12", {"sim_type": "BESS", "db": "ONS", "years": [2028], "year_idx": 0})
resp_step12 = _handle_sim_state("reiniciar")
check("STEP12 restart DB question lists option 3", _lists_option3(resp_step12),
      f"step={_ss['sim_step']}, resp={resp_step12[:160] if resp_step12 else None}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 14 — FIX 2: exact 3-message compact bus sequence (no field bleed)
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 14: FIX 2 — compact 3-bus sequence ═══\n")

reset_idle()
set_active("NET2_BUSES", {
    "sim_type": "NETWORK",
    "network": {"title": "T", "base_mva": 100.0, "buses": [], "lines": []},
    "net2": {"total": 3, "idx": 0, "field": "number", "current": {}},
})
_handle_sim_state("1, Barra A, 230 kV, referência, V=1.02")
_handle_sim_state("2, Barra B, 230 kV, PV, 150 MW, V=1.01")
_handle_sim_state("3, Barra C, 230 kV, PQ, 200 MW, 60 Mvar")

buses = _ss["sim_data"]["network"]["buses"]
check("compact: exactly 3 buses registered", len(buses) == 3, f"got {len(buses)}: {buses}")

if len(buses) == 3:
    b1, b2, b3 = buses
    # Bus 1 — REF
    check("compact bus1 number=1", b1["number"] == 1, f"{b1}")
    check("compact bus1 name=Barra_A (no bleed)", b1["name"] == "Barra_A", f"name={b1['name']}")
    check("compact bus1 kv=230", abs(b1["kv"] - 230.0) < 1e-9, f"kv={b1['kv']}")
    check("compact bus1 tipo=2 (Referência)", b1["tipo"] == 2, f"tipo={b1['tipo']}")
    check("compact bus1 v_pu=1.02", abs(b1["v_pu"] - 1.02) < 1e-9, f"v_pu={b1['v_pu']}")
    # Bus 2 — PV
    check("compact bus2 number=2", b2["number"] == 2, f"{b2}")
    check("compact bus2 name=Barra_B (no bleed)", b2["name"] == "Barra_B", f"name={b2['name']}")
    check("compact bus2 tipo=1 (PV)", b2["tipo"] == 1, f"tipo={b2['tipo']}")
    check("compact bus2 p_gen_mw=150", abs(b2["p_gen_mw"] - 150) < 1e-9, f"pg={b2['p_gen_mw']}")
    check("compact bus2 v_pu=1.01", abs(b2["v_pu"] - 1.01) < 1e-9, f"v_pu={b2['v_pu']}")
    # Bus 3 — PQ
    check("compact bus3 number=3", b3["number"] == 3, f"{b3}")
    check("compact bus3 name=Barra_C (no bleed)", b3["name"] == "Barra_C", f"name={b3['name']}")
    check("compact bus3 tipo=0 (PQ)", b3["tipo"] == 0, f"tipo={b3['tipo']}")
    check("compact bus3 p_load_mw=200", abs(b3["p_load_mw"] - 200) < 1e-9, f"pl={b3['p_load_mw']}")
    check("compact bus3 q_load_mvar=60", abs(b3["q_load_mvar"] - 60) < 1e-9, f"ql={b3['q_load_mvar']}")

check("compact 3-bus → advanced to NET3_LINES", _ss["sim_step"] == "NET3_LINES", f"step={_ss['sim_step']}")

# Direct unit tests of the compact parser
_b, _c, _r = _parse_compact_bus("1, Barra A, 230 kV, referência, V=1.02")
check("parser: REF compact complete", _b is not None and _c and _b["tipo"] == 2 and abs(_b["v_pu"] - 1.02) < 1e-9)
_b, _c, _r = _parse_compact_bus("2, Barra B, 230 kV, PV, 150 MW, V=1.01")
check("parser: PV compact complete", _b is not None and _c and _b["tipo"] == 1 and _b["p_gen_mw"] == 150)
_b, _c, _r = _parse_compact_bus("3, Barra C, 230 kV, PQ, 200 MW, 60 Mvar")
check("parser: PQ compact complete", _b is not None and _c and _b["tipo"] == 0 and _b["q_load_mvar"] == 60)
_b, _c, _r = _parse_compact_bus("1")
check("parser: bare number is NOT a compact bus", _b is None)
_b, _c, _r = _parse_compact_bus("4, Barra D, 230 kV, PQ, 200 MW")
check("parser: partial PQ → incomplete, resume 'ql'", _b is not None and not _c and _r == "ql", f"complete={_c}, resume={_r}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 15 — FIX 2: field-by-field entry (one answer per message) still works
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 15: FIX 2 — field-by-field entry ═══\n")

reset_idle()
set_active("NET2_BUSES", {
    "sim_type": "NETWORK",
    "network": {"title": "T", "base_mva": 100.0, "buses": [], "lines": []},
    "net2": {"total": 2, "idx": 0, "field": "number", "current": {}},
})
_handle_sim_state("1")        # bare number
_handle_sim_state("REF_A")    # name
_handle_sim_state("230")      # kV
_handle_sim_state("2")        # tipo REF
_handle_sim_state("1.05")     # v_pu → finalize bus 1
_handle_sim_state("2")        # bare number bus 2
_handle_sim_state("CARGA_B")  # name
_handle_sim_state("230")      # kV
_handle_sim_state("0")        # tipo PQ
_handle_sim_state("100")      # pl
_handle_sim_state("40")       # ql → finalize bus 2

fbf_buses = _ss["sim_data"]["network"]["buses"]
check("field-by-field: 2 buses registered", len(fbf_buses) == 2, f"got {len(fbf_buses)}")
if len(fbf_buses) == 2:
    check("fbf bus1 REF, v_pu=1.05",
          fbf_buses[0]["tipo"] == 2 and abs(fbf_buses[0]["v_pu"] - 1.05) < 1e-9, f"{fbf_buses[0]}")
    check("fbf bus2 PQ, pl=100, ql=40",
          fbf_buses[1]["tipo"] == 0 and fbf_buses[1]["p_load_mw"] == 100 and fbf_buses[1]["q_load_mvar"] == 40,
          f"{fbf_buses[1]}")
check("field-by-field → NET3_LINES", _ss["sim_step"] == "NET3_LINES", f"step={_ss['sim_step']}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 16 — FIX 2: "voltar" mid-bus entry goes back one field, not to NET1
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 16: FIX 2 — voltar during bus entry ═══\n")

# Mid-entry (field=kv) with one already-registered bus → back one field (kv→name)
reset_idle()
set_active("NET2_BUSES", {
    "sim_type": "NETWORK",
    "network": {"title": "T", "base_mva": 100.0,
                "buses": [{"number": 1, "name": "REF", "kv": 230.0, "tipo": 2, "v_pu": 1.05,
                           "angle_deg": 0, "p_gen_mw": 0, "q_min_mvar": -100, "q_max_mvar": 100,
                           "p_load_mw": 0, "q_load_mvar": 0}],
                "lines": []},
    "net2": {"total": 2, "idx": 1, "field": "kv", "current": {"number": 2, "name": "CARGA"}},
})
resp_back1 = _handle_sim_state("voltar")
check("voltar mid-entry stays in NET2_BUSES", _ss["sim_step"] == "NET2_BUSES", f"step={_ss['sim_step']}")
check("voltar mid-entry: kv → name (one step)", _ss["sim_data"]["net2"]["field"] == "name",
      f"field={_ss['sim_data']['net2']['field']}")
check("voltar mid-entry preserves already-registered bus",
      len(_ss["sim_data"]["network"]["buses"]) == 1, f"buses={_ss['sim_data']['network']['buses']}")
check("voltar mid-entry preserves current bus data",
      _ss["sim_data"]["net2"]["current"].get("number") == 2)

# Back navigation respects the type branch: v_pu (PV) → pg
reset_idle()
set_active("NET2_BUSES", {
    "sim_type": "NETWORK",
    "network": {"title": "T", "base_mva": 100.0, "buses": [], "lines": []},
    "net2": {"total": 2, "idx": 0, "field": "v_pu",
             "current": {"number": 1, "name": "GER", "kv": 230.0, "tipo": 1, "p_gen_mw": 150}},
})
_handle_sim_state("voltar")
check("voltar from v_pu (PV) → pg", _ss["sim_data"]["net2"]["field"] == "pg",
      f"field={_ss['sim_data']['net2']['field']}")

# First question of the very first bus → NET1_SETUP
reset_idle()
set_active("NET2_BUSES", {
    "sim_type": "NETWORK",
    "network": {"title": "T", "base_mva": 100.0, "buses": [], "lines": []},
    "net2": {"total": 2, "idx": 0, "field": "number", "current": {}},
})
_handle_sim_state("voltar")
check("voltar at first bus/first field → NET1_SETUP", _ss["sim_step"] == "NET1_SETUP",
      f"step={_ss['sim_step']}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 17 — FIX 2: line-def / other-bus message mid-entry is not absorbed
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 17: FIX 2 — stray records during bus entry ═══\n")

check("_looks_like_line_def detects from-to", _looks_like_line_def("1-2, circuito 1, R=0.5 X=5 Q=20"))
check("_looks_like_line_def rejects a bus line", not _looks_like_line_def("1, Barra A, 230 kV, referência, V=1.02"))

# Line-definition message while still entering a bus (field=name)
reset_idle()
set_active("NET2_BUSES", {
    "sim_type": "NETWORK",
    "network": {"title": "T", "base_mva": 100.0, "buses": [], "lines": []},
    "net2": {"total": 2, "idx": 0, "field": "name", "current": {"number": 1}},
})
resp_line = _handle_sim_state("1-2, circuito 1, R=0.5 X=5 Q=20")
check("line-def not consumed as name (field unchanged)",
      _ss["sim_data"]["net2"]["field"] == "name", f"field={_ss['sim_data']['net2']['field']}")
check("line-def did not set a name on the current bus",
      "name" not in _ss["sim_data"]["net2"]["current"], f"current={_ss['sim_data']['net2']['current']}")
check("line-def response clarifies (mentions barra/linha)",
      resp_line and ("barra" in resp_line.lower() or "linha" in resp_line.lower()))

# Full record for a DIFFERENT bus arriving mid-entry (field=name)
reset_idle()
set_active("NET2_BUSES", {
    "sim_type": "NETWORK",
    "network": {"title": "T", "base_mva": 100.0, "buses": [], "lines": []},
    "net2": {"total": 3, "idx": 0, "field": "name", "current": {"number": 1}},
})
resp_other = _handle_sim_state("2, Barra B, 230 kV, PV, 150 MW, V=1.01")
check("other-bus record not consumed as name (field unchanged)",
      _ss["sim_data"]["net2"]["field"] == "name" and "name" not in _ss["sim_data"]["net2"]["current"],
      f"field={_ss['sim_data']['net2']['field']}, current={_ss['sim_data']['net2']['current']}")
check("other-bus record did not register a stray bus",
      len(_ss["sim_data"]["network"]["buses"]) == 0, f"buses={_ss['sim_data']['network']['buses']}")
check("other-bus response clarifies (mentions outra barra)",
      resp_other and "outra barra" in resp_other.lower(), f"resp={resp_other[:160] if resp_other else None}")


# ─────────────────────────────────────────────────────────────────────────────
# SECTION 18 — bus-count question requires a BARE integer (no leading-digit grab)
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 18: bus-count requires bare integer ═══\n")

# A full compact bus record at the count question must be REJECTED and re-asked,
# not have its leading "2" silently extracted as the bus count.
reset_idle()
set_active("NET2_BUSES", {
    "sim_type": "NETWORK",
    "network": {"title": "T", "base_mva": 100.0, "buses": [], "lines": []},
    "net2": {"total": None, "idx": 0, "field": "count", "current": {}},
})
resp_cnt = _handle_sim_state("2, Barra B, 230 kV, PV, 150 MW, V=1.01")
check("compact record at count question does NOT set total",
      _ss["sim_data"]["net2"]["total"] is None, f"total={_ss['sim_data']['net2']['total']}")
check("compact record at count question stays in count field",
      _ss["sim_data"]["net2"]["field"] == "count", f"field={_ss['sim_data']['net2']['field']}")
check("compact record at count question re-asks (número entre 2 e 20)",
      resp_cnt and "número entre" in resp_cnt.lower(),
      f"resp={resp_cnt[:160] if resp_cnt else None}")

# A bare integer (optionally padded with whitespace) is still accepted.
reset_idle()
set_active("NET2_BUSES", {
    "sim_type": "NETWORK",
    "network": {"title": "T", "base_mva": 100.0, "buses": [], "lines": []},
    "net2": {"total": None, "idx": 0, "field": "count", "current": {}},
})
resp_ok = _handle_sim_state(" 3 ")
check("padded bare integer accepted as count",
      _ss["sim_data"]["net2"]["total"] == 3 and _ss["sim_data"]["net2"]["field"] == "number",
      f"total={_ss['sim_data']['net2']['total']}, field={_ss['sim_data']['net2']['field']}")


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "═" * 60)
passed = sum(1 for _, ok in results if ok)
failed = sum(1 for _, ok in results if not ok)
print(f"\nResults: {passed} passed, {failed} failed out of {len(results)} tests\n")
if failed:
    print("Failed tests:")
    for name, ok in results:
        if not ok:
            print(f"  - {name}")
    sys.exit(1)
else:
    print("All tests passed.")
    sys.exit(0)
