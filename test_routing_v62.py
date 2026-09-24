"""
Routing test suite for v6.2 — tests both the root-cause analysis (what the
bug was) and the fixed behavior (what happens after the fix).

Run from the repo root:  python3 test_routing_v62.py
"""

import re
import sys
import types
import unicodedata
from types import SimpleNamespace
import contextlib

# ── Minimal Streamlit mock ────────────────────────────────────────────────────

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
sys.modules["memory.session_memory"].StudyState            = type("StudyState", (), {"summary": lambda self: ""})
sys.modules["memory.persistent_memory"].load_study         = lambda: sys.modules["memory.session_memory"].StudyState()
sys.modules["memory.persistent_memory"].save_study         = lambda *a: None
sys.modules["memory.persistent_memory"].clear_study        = lambda *a: None
sys.modules["auth.db"].init_db                             = lambda: None
for _fn in ["signup","login","log_chat_message","create_session","update_session",
            "save_paused_state","load_paused_state","clear_paused_state"]:
    setattr(sys.modules["auth.auth_service"], _fn, lambda *a, **kw: None)
sys.modules["prompts.system_prompt"].SYSTEM_PROMPT         = "stub"

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

# ── Import routing functions ──────────────────────────────────────────────────
import app as _app

_is_simulation_intent = _app._is_simulation_intent
_is_free_question     = _app._is_free_question
_is_lt_data_message   = _app._is_lt_data_message
_parse_lt_params      = _app._parse_lt_params
_format_lt_params     = _app._format_lt_params
_parse_mva            = _app._parse_mva
_handle_sim_state     = _app._handle_sim_state
extract_sim_context   = _app.extract_sim_context

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
    print(f"  [{status}] {name}")
    if detail:
        print(f"         {detail}")
    results.append((name, condition))


# ── Test messages ─────────────────────────────────────────────────────────────

# Gabriel's exact message style (ends with question about ANAREDE)
MSG_A1 = (
    "Tenho uma linha de transmissão de 230 kV, 180 km, com "
    "R = 0,0257 ohms/km, X = 0,2995 ohms/km e B = 5,4542 μS/km. "
    "Como eu integro isso no ANAREDE?"
)

# Same data declarative, no question mark
MSG_A2 = (
    "Tenho uma LT de 230 kV com R=0.0257 ohms/km, X=0.2995 ohms/km, "
    "B=5.4542 μS/km, 180 km"
)

# With explicit DLIN keyword
MSG_A3 = (
    "Preciso modelar uma LT: tensão 500 kV, comprimento 250 km, "
    "R = 0,05 ohm/km, X = 0,35 ohm/km, B = 3,2 μS/km. "
    "Quero inserir no DLIN do ANAREDE."
)

# Explicit trigger + LT params in same message (should NOT double-prompt)
MSG_EXPLICIT_PLUS_LT = (
    "Quero simular uma BESS. Tenho uma LT de 230 kV com "
    "R=0.0257 ohms/km, X=0.2995 ohms/km, B=5.4542 μS/km, 180 km."
)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 1 — Root-cause assertions (confirm the analysis was correct)
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 1: Root-cause analysis — trigger list gap confirmed ═══\n")

check(
    "MSG_A1: _is_simulation_intent still False (trigger list intentionally unchanged)",
    _is_simulation_intent(MSG_A1) is False,
)
check(
    "MSG_A2: _is_simulation_intent still False",
    _is_simulation_intent(MSG_A2) is False,
)
check(
    "MSG_A3: _is_simulation_intent still False",
    _is_simulation_intent(MSG_A3) is False,
)
check(
    "MSG_A1: _is_lt_data_message now True (new detector)",
    _is_lt_data_message(MSG_A1) is True,
)
check(
    "MSG_A2: _is_lt_data_message True",
    _is_lt_data_message(MSG_A2) is True,
)
check(
    "MSG_A3: _is_lt_data_message True",
    _is_lt_data_message(MSG_A3) is True,
)

# Confirm _parse_lt_params extracts correct values from Gabriel's message
params_A1 = _parse_lt_params(MSG_A1)
print(f"  Parsed from MSG_A1: {params_A1}")
check(
    "MSG_A1 parsed: voltage_kv = 230",
    params_A1.get("voltage_kv") == 230.0,
)
check(
    "MSG_A1 parsed: length_km = 180",
    params_A1.get("length_km") == 180.0,
)
check(
    "MSG_A1 parsed: R_ohm_km = 0.0257",
    params_A1.get("R_ohm_km") == 0.0257,
)
check(
    "MSG_A1 parsed: X_ohm_km = 0.2995",
    params_A1.get("X_ohm_km") == 0.2995,
)
check(
    "MSG_A1 parsed: B_us_km = 5.4542",
    params_A1.get("B_us_km") == 5.4542,
)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 2 — CASE A fixed: IDLE_LT_CONFIRM triggered (not RAG fallthrough)
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 2: CASE A fix — IDLE_LT_CONFIRM triggered ═══\n")

reset_idle()
resp_A1 = _handle_sim_state(MSG_A1)
print(f"MSG_A1 from IDLE:")
print(f"  sim_step → {_ss['sim_step']}")
print(f"  response → {repr(resp_A1[:80]) if resp_A1 else 'None'}")

check(
    "A1: sim_step set to IDLE_LT_CONFIRM (not IDLE)",
    _ss["sim_step"] == "IDLE_LT_CONFIRM",
)
check(
    "A1: response is a confirmation prompt (not None/RAG)",
    resp_A1 is not None and "Sim" in resp_A1 and "Não" in resp_A1,
)
check(
    "A1: LT params stored in sim_data['pending_lt']",
    _ss["sim_data"].get("pending_lt", {}).get("voltage_kv") == 230.0,
)
check(
    "A1: original question stored in sim_data['pending_question']",
    _ss["sim_data"].get("pending_question") == MSG_A1,
)
check(
    "A1: detected params shown in confirmation text",
    "230 kV" in (resp_A1 or "") and "0.0257" in (resp_A1 or ""),
)

reset_idle()
resp_A2 = _handle_sim_state(MSG_A2)
print(f"\nMSG_A2 (declarative) from IDLE:")
print(f"  sim_step → {_ss['sim_step']}")
check(
    "A2: sim_step set to IDLE_LT_CONFIRM",
    _ss["sim_step"] == "IDLE_LT_CONFIRM",
)
check(
    "A2: response is confirmation prompt",
    resp_A2 is not None and "Não" in resp_A2,
)

reset_idle()
resp_A3 = _handle_sim_state(MSG_A3)
print(f"\nMSG_A3 (DLIN keyword) from IDLE:")
print(f"  sim_step → {_ss['sim_step']}")
check(
    "A3: sim_step set to IDLE_LT_CONFIRM",
    _ss["sim_step"] == "IDLE_LT_CONFIRM",
)

# ── IDLE_LT_CONFIRM: user says "sim" → enters STEP1, keeps pending_lt ─────────
print("\n--- IDLE_LT_CONFIRM 'sim' path ---\n")

reset_idle()
_handle_sim_state(MSG_A1)                       # → IDLE_LT_CONFIRM
resp_confirm_yes = _handle_sim_state("sim")     # user confirms
print(f"  sim_step after 'sim' → {_ss['sim_step']}")
print(f"  sim_status           → {_ss['sim_status']}")
print(f"  pending_lt preserved → {bool(_ss['sim_data'].get('pending_lt'))}")
print(f"  response excerpt     → {repr(resp_confirm_yes[:120]) if resp_confirm_yes else 'None'}")

check(
    "IDLE_LT_CONFIRM 'sim': sim_step advances to STEP1",
    _ss["sim_step"] == "STEP1",
)
check(
    "IDLE_LT_CONFIRM 'sim': sim_status = active",
    _ss["sim_status"] == "active",
)
check(
    "IDLE_LT_CONFIRM 'sim': pending_lt preserved in sim_data",
    bool(_ss["sim_data"].get("pending_lt")),
)
check(
    "IDLE_LT_CONFIRM 'sim': response contains DLIN flag note",
    resp_confirm_yes is not None and "DLIN" in resp_confirm_yes,
)

# ── IDLE_LT_CONFIRM: user says "não" → LLM gets original question ─────────────
print("\n--- IDLE_LT_CONFIRM 'não' path ---\n")

reset_idle()
_handle_sim_state(MSG_A1)               # → IDLE_LT_CONFIRM
resp_confirm_no = _handle_sim_state("não")
lt_q_stored = _ss.get("_lt_confirm_question")
print(f"  sim_step after 'não'           → {_ss['sim_step']}")
print(f"  _lt_confirm_question stored    → {bool(lt_q_stored)}")
print(f"  response                       → {repr(resp_confirm_no)}")

check(
    "IDLE_LT_CONFIRM 'não': sim_step reset to IDLE",
    _ss["sim_step"] == "IDLE",
)
check(
    "IDLE_LT_CONFIRM 'não': _handle_sim_state returns None (→ LLM)",
    resp_confirm_no is None,
)
check(
    "IDLE_LT_CONFIRM 'não': original question stored for LLM override",
    lt_q_stored == MSG_A1,
)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 3 — CASE B fixed: no silent misparse in mid-simulation steps
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 3: CASE B fix — mid-simulation misparsing eliminated ═══\n")

# STEP7 BESS — long LT param message: no decimal fragment grab, clarifying Q returned
set_active("STEP7", {"sim_type": "BESS", "db": "ONS", "years": [2028],
                      "year": 2028, "scenario": "Verão Máxima Diurna"})

resp_B7_fix = _handle_sim_state(MSG_A2)
bus_set_B7  = _ss["sim_data"].get("bess_bus")

print(f"At STEP7 with long LT params msg:")
print(f"  bess_bus set to → {repr(bus_set_B7)}")
print(f"  response        → {repr(resp_B7_fix[:80]) if resp_B7_fix else 'None'}")

check(
    "B-STEP7 fix: bess_bus NOT populated from LT param message",
    bus_set_B7 is None,
    "Lookbehind prevents decimal-fragment match; long-text fallback rejected"
)
check(
    "B-STEP7 fix: returns clarifying question (not silent misparse)",
    resp_B7_fix is not None and "barra" in resp_B7_fix.lower(),
)

# STEP7 question-form still goes to LLM (v6.1 behavior preserved)
set_active("STEP7", {"sim_type": "BESS", "db": "ONS", "years": [2028],
                      "year": 2028, "scenario": "Verão Máxima Diurna"})
resp_B7_q = _handle_sim_state(MSG_A1)
check(
    "B-STEP7 '?' form: still routed to LLM (sim_state preserved)",
    resp_B7_q is None and _ss["sim_step"] == "STEP7",
)

# STEP8 — no MVA grab from "230 kV"
set_active("STEP8", {"sim_type": "BESS", "db": "ONS", "bess_bus": "12345",
                      "bess_mode": "PV", "years": [2028], "year": 2028,
                      "scenario": "Verão Máxima Diurna"})

resp_B8_fix = _handle_sim_state(MSG_A2)
mva_set_B8  = _ss["sim_data"].get("bess_mva")

print(f"\nAt STEP8 with long LT params msg:")
print(f"  bess_mva set to → {repr(mva_set_B8)}")
print(f"  response        → {repr(resp_B8_fix[:80]) if resp_B8_fix else 'None'}")

check(
    "B-STEP8 fix: bess_mva NOT set from LT param message (no '230' grab)",
    mva_set_B8 is None,
)
check(
    "B-STEP8 fix: returns clarifying question asking for MVA",
    resp_B8_fix is not None and "MVA" in resp_B8_fix,
)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 4 — _parse_mva fix
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 4: _parse_mva fix ═══\n")

check("_parse_mva('100 MVA') = '100'",     _parse_mva("100 MVA")   == "100")
check("_parse_mva('100 mva') = '100'",     _parse_mva("100 mva")   == "100")
check("_parse_mva('100') = '100'",         _parse_mva("100")       == "100",
      "bare number still accepted")
check("_parse_mva('100,5 MVA') = '100.5'", _parse_mva("100,5 MVA") == "100.5")
check("_parse_mva('230 kV') = None",       _parse_mva("230 kV")    is None,
      "voltage not grabbed as MVA anymore")
check("_parse_mva('180 km') = None",       _parse_mva("180 km")    is None,
      "length not grabbed as MVA")
check("_parse_mva(MSG_A2) = None",         _parse_mva(MSG_A2)      is None,
      "full LT param dump yields no MVA parse")

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 5 — Regression: explicit trigger phrases still work
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 5: Known trigger phrases still fire ═══\n")

for phrase in [
    "quero simular um BESS no SIN",
    "quero inserir um BESS na rede",
    "preciso de uma simulação",
    "iniciar simulação",
    "gostaria de fazer um estudo",
]:
    r = _is_simulation_intent(phrase)
    check(f"trigger: '{phrase[:45]}'", r is True)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 6 — Regression test 1: Gabriel's exact original message → IDLE_LT_CONFIRM
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Regression 1: Gabriel's exact message from IDLE ═══\n")

GABRIEL_MSG = (
    "Tenho uma LT de 230 kV com R=0.0257 ohms/km, X=0.2995 ohms/km, "
    "B=5.4542 μS/km, 180 km"
)

reset_idle()
resp_gabriel = _handle_sim_state(GABRIEL_MSG)

print(f"  sim_step → {_ss['sim_step']}")
print(f"  response → {repr(resp_gabriel[:100]) if resp_gabriel else 'None (→ RAG)'}")

check(
    "REG-1: Gabriel's message → IDLE_LT_CONFIRM (NOT RAG fallthrough)",
    _ss["sim_step"] == "IDLE_LT_CONFIRM" and resp_gabriel is not None,
)
check(
    "REG-1: confirmation prompt asks Sim/Não",
    resp_gabriel is not None and "Sim" in resp_gabriel and "Não" in resp_gabriel,
)
check(
    "REG-1: detected kV and R param shown in prompt",
    resp_gabriel is not None and "230 kV" in resp_gabriel and "0.0257" in resp_gabriel,
)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 7 — Regression test 2: explicit trigger + LT params → no double-prompt
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Regression 2: Explicit trigger + LT params → no double-prompting ═══\n")

reset_idle()
resp_explicit = _handle_sim_state(MSG_EXPLICIT_PLUS_LT)

print(f"  MSG: '{MSG_EXPLICIT_PLUS_LT[:70]}...'")
print(f"  sim_step → {_ss['sim_step']}")
print(f"  response → {repr(resp_explicit[:80]) if resp_explicit else 'None'}")

check(
    "REG-2: explicit trigger wins → goes directly to STEP1 (no IDLE_LT_CONFIRM)",
    _ss["sim_step"] == "STEP1",
)
check(
    "REG-2: response is standard guided-flow intro (no confusion with LT confirm)",
    resp_explicit is not None and "Qual base de dados" in resp_explicit,
)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 8 — Regression test 3a: bare bus number at STEP7 still works
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Regression 3a: bare '9999' at STEP7 still works ═══\n")

set_active("STEP7", {"sim_type": "BESS", "db": "ONS", "years": [2028],
                      "year": 2028, "scenario": "Verão Máxima Diurna"})

resp_bus = _handle_sim_state("9999")
bus_after = _ss["sim_data"].get("bess_bus")

print(f"  bess_bus set to → {repr(bus_after)}")
print(f"  sim_step        → {_ss['sim_step']}")

check(
    "REG-3a: bare '9999' at STEP7 accepted as bus number",
    bus_after == "9999",
    "Lookbehind fix must not break standalone 4-digit numbers"
)

# Subestação name (short text) also still works
set_active("STEP7", {"sim_type": "BESS", "db": "ONS", "years": [2028],
                      "year": 2028, "scenario": "Verão Máxima Diurna"})

resp_bus_name = _handle_sim_state("SE Tijuco Preto")
bus_name_after = _ss["sim_data"].get("bess_bus")

check(
    "REG-3a: short subestação name at STEP7 still accepted",
    bus_name_after == "SE Tijuco Preto",
)

# A 5-digit bus number
set_active("STEP7", {"sim_type": "BESS", "db": "ONS", "years": [2028],
                      "year": 2028, "scenario": "Verão Máxima Diurna"})

_handle_sim_state("barra 12345")
check(
    "REG-3a: '12345' in 'barra 12345' extracted correctly",
    _ss["sim_data"].get("bess_bus") == "12345",
)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 9 — Regression test 3b: bare '100' at STEP8 still works
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Regression 3b: bare '100' at STEP8 still works ═══\n")

set_active("STEP8", {"sim_type": "BESS", "db": "ONS", "bess_bus": "12345",
                      "bess_mode": "PV", "years": [2028], "year": 2028,
                      "scenario": "Verão Máxima Diurna"})

resp_mva = _handle_sim_state("100")
mva_after = _ss["sim_data"].get("bess_mva")

print(f"  bess_mva set to → {repr(mva_after)}")

check(
    "REG-3b: bare '100' at STEP8 accepted as MVA",
    mva_after == "100",
    "Bare-number fallback in _parse_mva must still work for simple responses"
)

set_active("STEP8", {"sim_type": "BESS", "db": "ONS", "bess_bus": "12345",
                      "bess_mode": "PV", "years": [2028], "year": 2028,
                      "scenario": "Verão Máxima Diurna"})

_handle_sim_state("150 MVA")
check(
    "REG-3b: '150 MVA' explicit unit also accepted",
    _ss["sim_data"].get("bess_mva") == "150",
)

set_active("STEP8", {"sim_type": "BESS", "db": "ONS", "bess_bus": "12345",
                      "bess_mode": "PV", "years": [2028], "year": 2028,
                      "scenario": "Verão Máxima Diurna"})

_handle_sim_state("100,5 MVA")
check(
    "REG-3b: '100,5 MVA' decimal with comma accepted",
    _ss["sim_data"].get("bess_mva") == "100.5",
)

# ─────────────────────────────────────────────────────────────────────────────
# SECTION 10 — False-positive guard: generic kV+km question should NOT trigger
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Section 10: False-positive guard ═══\n")

reset_idle()
resp_fp1 = _handle_sim_state("Como funciona uma LT de 230 kV?")
check(
    "FP: 'Como funciona uma LT de 230 kV?' → NOT IDLE_LT_CONFIRM (only 1 param signal)",
    _ss["sim_step"] == "IDLE" and resp_fp1 is None,
)

reset_idle()
resp_fp2 = _handle_sim_state("Qual a impedância de uma linha de 230 kV com 200 km?")
check(
    "FP: '230 kV + 200 km' question with '?' → NOT IDLE_LT_CONFIRM (_is_free_question wins)",
    _ss["sim_step"] == "IDLE" and resp_fp2 is None,
    "Two param signals but ends with '?' → _is_free_question short-circuits before LT check"
)

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print("\n═══ Summary ═══\n")
total  = len(results)
passed = sum(1 for _, ok in results if ok)
failed = total - passed
for name, ok in results:
    print(f"  {'✓' if ok else '✗'} {name}")
print(f"\n{passed}/{total} checks passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
