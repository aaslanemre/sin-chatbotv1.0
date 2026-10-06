"""
v6.4.0 — tester feedback: upsert SQL (sqlite stand-in), widget behaviour, state
immutability, stable message ids, chat_logs ids/steps, DB-failure tolerance.

Run from repo root:  python3 test_feedback_v64.py
"""
import copy
import re
import runpy
import sqlite3
import sys
import types

# ── Streamlit mock with scriptable widgets ───────────────────────────────────
class _SS(dict):
    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError(k)
    def __setattr__(self, k, v): self[k] = v
    def get(self, k, d=None): return super().get(k, d)
    def pop(self, k, *a): return super().pop(k, *a)

class _Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __getattr__(self, n): return lambda *a, **kw: _Ctx()

ss = _SS()
calls = {"popover": [], "toast": [], "markdown": [], "form_keys": []}
script = {"rating": None, "category": None, "comment": "", "submit": False, "prompt": None}

st = types.ModuleType("streamlit")
st.session_state = ss
for n in ["set_page_config", "stop", "error", "tabs", "form_submit_button_", "text_input", "spinner",
          "expander", "caption", "divider", "info", "success", "warning", "rerun"]:
    setattr(st, n, lambda *a, **kw: None)
calls["button_keys"] = []
st.button = lambda *a, **kw: calls["button_keys"].append(kw.get("key")) and None  # v6.5.0: 👍/👎 fallback buttons
st.markdown = lambda *a, **kw: calls["markdown"].append(a[0] if a else "")
st.sidebar = _Ctx()
st.columns = lambda n, **kw: [_Ctx() for _ in range(n if isinstance(n, int) else len(n))]
st.chat_message = lambda *a, **kw: _Ctx()
st.spinner = lambda *a, **kw: _Ctx()
st.expander = lambda *a, **kw: _Ctx()
st.container = lambda *a, **kw: _Ctx()  # v6.5.0 banner
st.popover = lambda label, **kw: (calls["popover"].append(label), _Ctx())[1]
def _form(key=None, **kw):
    calls["form_keys"].append(key); return _Ctx()
st.form = _form
st.radio = lambda label, opts, index=None, **kw: script["rating"] if script["rating"] else (opts[index] if index is not None else None)
st.selectbox = lambda label, opts, index=0, **kw: script["category"] if script["category"] else opts[index]
st.text_area = lambda label, value="", **kw: script["comment"] or value
st.form_submit_button = lambda *a, **kw: script["submit"]
st.toast = lambda msg, **kw: calls["toast"].append(msg)
st.chat_input = lambda *a, **kw: script["prompt"]
sys.modules["streamlit"] = st

# ── Stub heavy deps for importing app.py ─────────────────────────────────────
for m in ["agents.pwf_agent", "agents.results_analyzer", "memory.session_memory",
          "memory.persistent_memory", "auth.db", "auth.auth_service",
          "prompts.system_prompt", "rag.chain"]:
    sys.modules[m] = types.ModuleType(m)
sys.modules["agents.pwf_agent"].generate_dbar_block = lambda **kw: ""
sys.modules["agents.pwf_agent"].generate_statcom_block = lambda **kw: ""
sys.modules["agents.pwf_agent"].generate_contingency_block = lambda *a, **kw: ""
sys.modules["agents.results_analyzer"].save_results_file = lambda *a, **kw: None
sys.modules["agents.results_analyzer"].check_convergence = lambda *a, **kw: None
sys.modules["agents.results_analyzer"].format_results_report = lambda *a, **kw: ""
SS_CLS = type("StudyState", (), {"summary": lambda self: ""})
sys.modules["memory.session_memory"].StudyState = SS_CLS
sys.modules["memory.persistent_memory"].load_study = lambda: SS_CLS()
sys.modules["memory.persistent_memory"].save_study = lambda *a: None
sys.modules["memory.persistent_memory"].clear_study = lambda *a: None
sys.modules["auth.db"].init_db = lambda: None
sys.modules["prompts.system_prompt"].SYSTEM_PROMPT = "stub"

svc = sys.modules["auth.auth_service"]
logged, submitted = [], []
fail = {"log": False, "submit": False, "load": False}

def _log(user_id, session_id, role, message, sim_step=None, message_id=None, sim_type=None, **kw):
    if fail["log"]: raise RuntimeError("db down")
    logged.append({"role": role, "message": message, "sim_step": sim_step,
                   "message_id": message_id, "sim_type": sim_type})

def _submit(*args, **kw):
    if fail["submit"]: raise RuntimeError("db down")
    submitted.append(args)

def _load(uid, sid):
    if fail["load"]: raise RuntimeError("db down")
    return {}

for fn in ["signup", "login", "create_session", "update_session", "save_paused_state",
           "load_paused_state", "clear_paused_state"]:
    setattr(svc, fn, lambda *a, **kw: None)
svc.log_chat_message, svc.submit_feedback, svc.get_user_feedback_for_session = _log, _submit, _load

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
results = []
def check(name, cond, detail=""):
    print(f"  [{PASS if cond else FAIL}] {name}")
    if not cond and detail: print(f"         {detail}")
    results.append((name, bool(cond)))

def fresh_state():
    ss.clear()
    ss.update({"db_initialized": True, "user": {"id": "u1", "email": "t@t", "full_name": "T"},
               "session_id": "s1", "chain": None, "chain_error": None, "_prompt_hash": None,
               "simulation_mode": False, "sim_step": "IDLE", "sim_data": {}, "sim_status": None,
               "study": SS_CLS()})
    logged.clear(); submitted.clear()
    calls["popover"].clear(); calls["toast"].clear()
    script.update(rating=None, category=None, comment="", submit=False, prompt=None)
    fail.update(log=False, submit=False, load=False)

def run_app(prompt=None):
    script["prompt"] = prompt
    return runpy.run_path("app.py", run_name="app_under_test")

# ═════════════════════════════════════════════════════════════════════════════
print("\n═══ 1. submit_feedback upsert (real SQL on sqlite) ═══\n")
# ═════════════════════════════════════════════════════════════════════════════
import importlib.util
db = sys.modules["auth.db"]
lite = sqlite3.connect(":memory:", check_same_thread=False)
lite.row_factory = sqlite3.Row
lite.execute("""CREATE TABLE feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id, session_id, message_id,
    rating, category, comment, assistant_message, user_message, sim_type, sim_step_before, sim_step_after,
    app_version, status DEFAULT 'novo', admin_note, created_at DEFAULT CURRENT_TIMESTAMP,
    updated_at DEFAULT CURRENT_TIMESTAMP, grounding_score, grounding_level, UNIQUE (user_id, message_id))""")

class _Cur:
    def __init__(self): self.c = lite.cursor()
    def execute(self, sql, params=()):
        sql = sql.replace("%s::uuid", "?").replace("%s", "?").replace("now()", "CURRENT_TIMESTAMP")
        self.c.execute(sql, params); return self
    def fetchall(self): return [dict(r) for r in self.c.fetchall()]
    def close(self): pass
class _Conn:
    def cursor(self, *a, **kw): return _Cur()
    def commit(self): lite.commit()
    def rollback(self): lite.rollback()
    def close(self): pass
db.get_connection = lambda: _Conn()
db.get_cursor = lambda conn: conn.cursor()

spec = importlib.util.spec_from_file_location("real_auth_service", "auth/auth_service.py")
real = importlib.util.module_from_spec(spec); spec.loader.exec_module(real)

args = ("u1", "s1", "m1", "up", None, "bom", "resposta", "pergunta", "BESS", "STEP2", "STEP3", "v6.4.0")
real.submit_feedback(*args)
real.submit_feedback("u1", "s1", "m1", "down", "passo", "confuso", "resposta", "pergunta", "BESS", "STEP2", "STEP3", "v6.4.0")
n = lite.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
row = dict(lite.execute("SELECT * FROM feedback").fetchone())
check("second submit by same user/message → one row", n == 1, n)
check("row updated (rating/category/comment)", (row["rating"], row["category"], row["comment"]) == ("down", "passo", "confuso"), row)
real.update_feedback_status(1, "em_analise", "olhando")
real.submit_feedback("u1", "s1", "m1", "down", "passo", "ainda confuso", "resposta", "pergunta", "BESS", "STEP2", "STEP3", "v6.4.0")
row = dict(lite.execute("SELECT * FROM feedback").fetchone())
check("admin status/note survive a tester resubmit", (row["status"], row["admin_note"], row["comment"]) == ("em_analise", "olhando", "ainda confuso"), row)
real.submit_feedback("u1", "s1", "m2", "up", None, "", "r2", "p2", "BESS", "STEP3", "STEP4", "v6.4.0")
real.submit_feedback("u2", "s2", "m1", "up", None, "", "r", "p", "BESS", "STEP1", "STEP2", "v6.4.0")
check("different message / different user → new rows", lite.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 3)
got = real.get_user_feedback_for_session("u1", "s1")
check("get_user_feedback_for_session keyed by message_id", set(got) == {"m1", "m2"}, got.keys())
try:
    real.update_feedback_status(1, "invalido", None); bad = False
except ValueError:
    bad = True
check("invalid status rejected", bad)

# ═════════════════════════════════════════════════════════════════════════════
print("\n═══ import app + helpers ═══\n")
# ═════════════════════════════════════════════════════════════════════════════
fresh_state()
env = run_app()
make, render_widget = env["_make_assistant_message"], env["_render_feedback_widget"]
VERSION = env["APP_VERSION"]
check("APP_VERSION constant is set (single source)", VERSION == "v6.5.0")

# ═════════════════════════════════════════════════════════════════════════════
print("\n═══ 2. submit leaves simulation state untouched ═══\n")
# ═════════════════════════════════════════════════════════════════════════════
def snapshot():
    return copy.deepcopy({k: ss.get(k) for k in ("sim_step", "sim_data", "sim_status", "simulation_mode")})

def exercise(label, step, data, status, sim_mode):
    fresh_state()
    env = run_app()
    ss.update(sim_step=step, sim_data=copy.deepcopy(data), sim_status=status, simulation_mode=sim_mode)
    msg = env["_make_assistant_message"]("Qual a potência?", user_message="2028",
                                         step_before="STEP6", type_before="BESS")
    ss.messages.append(msg)
    def boom(*a, **kw): raise AssertionError("chat pipeline must not run on feedback submit")
    env["_handle_sim_state"].__globals__["_handle_sim_state"] = boom
    before, nmsg, nlog = snapshot(), len(ss.messages), len(logged)
    # v6.5.0: one click on 👎 records the rating, then the optional comment form
    env["_record_rating"](msg, "down")
    script.update(category="passo", comment="não entendi", submit=True)
    env["_render_feedback_widget"](msg)
    after = snapshot()
    check(f"{label}: sim_step/sim_data/sim_status/mode identical", before == after, (before, after))
    check(f"{label}: no new messages, no chat_logs rows, pipeline not run", len(ss.messages) == nmsg and len(logged) == nlog)
    check(f"{label}: feedback saved (click, then comment on the same message) + thanks toast + ✅ state",
          len(submitted) == 2 and all(a[2] == msg["message_id"] for a in submitted)
          and submitted[-1][3:6] == ("down", "passo", "não entendi")
          and "Obrigado pelo feedback!" in calls["toast"] and msg["message_id"] in ss["_feedback_cache"])
    check(f"{label}: snapshot carries version/step/type/user msg",
          submitted[0][11] == VERSION and submitted[0][7] == "2028" and submitted[0][8] == data["sim_type"] and submitted[0][2] == msg["message_id"], submitted[0])

exercise("BESS STEP7", "STEP7", {"sim_type": "BESS", "db": "ONS", "years": [2028]}, "active", True)
exercise("NET state", "NET3_LINES", {"sim_type": "NETWORK", "network": {"title": "x", "base_mva": 100.0, "buses": [{"n": 1}], "lines": []}}, "active", True)
exercise("paused", "STEP8", {"sim_type": "BESS", "db": "ONS"}, "paused", False)

# ═════════════════════════════════════════════════════════════════════════════
print("\n═══ 3/4. stable ids, chat_logs ids, welcome vs. others ═══\n")
# ═════════════════════════════════════════════════════════════════════════════
fresh_state()
run_app()                                   # first render creates the welcome message
welcome = ss.messages[0]
check("welcome message has no id and is flagged", welcome.get("welcome") and not welcome.get("message_id"))
run_app("quero simular um BESS")            # chain None → deterministic sim response
run_app("ONS")
msgs = list(ss.messages)
ids = [m.get("message_id") for m in msgs[1:]]
check("every non-welcome message got a uuid message_id, all unique",
      all(re.fullmatch(r"[0-9a-f-]{36}", i or "") for i in ids) and len(set(ids)) == len(ids), ids)
assistants = [m for m in msgs if m["role"] == "assistant" and not m.get("welcome")]
check("assistant messages carry sim_type / step_before / step_after / user_message",
      all(m.get("sim_step_after") and "user_message" in m and "sim_step_before" in m for m in assistants), assistants)

# chat_logs rows reuse the same ids
by_id = {r["message_id"]: r for r in logged}
check("same message_id written to chat_logs for every user and assistant message",
      all(i in by_id for i in ids), (ids, list(by_id)))
a1 = by_id[assistants[0]["message_id"]]; u1 = by_id[msgs[1]["message_id"]]
check("user row logs step on arrival (IDLE); assistant row logs step after (STEP1) + sim_type BESS",
      u1["sim_step"] == "IDLE" and a1["sim_step"] == "STEP1" and a1["sim_type"] == "BESS", (u1, a1))
check("sim_step populated on EVERY chat_logs row", all(r["sim_step"] for r in logged), logged)

# reruns / history replay keep ids and render one widget per non-welcome assistant
calls["popover"].clear(); calls["button_keys"].clear()
run_app(); run_app()
check("ids unchanged after reruns", [m.get("message_id") for m in ss.messages[1:]] == ids)
n_assist = len(assistants)
_thumbs = [k for k in calls["button_keys"] if k and k.startswith("fb_up_")]
check("welcome has no 👍/👎; every other assistant message has them (always visible)",
      len(_thumbs) == 2 * n_assist and not any(welcome.get("message_id") and welcome["message_id"] in k for k in _thumbs),
      (len(_thumbs), n_assist))
legacy = {"role": "assistant", "content": "antiga"}
ss.messages.append(legacy)
run_app()
_first = legacy.get("message_id")
run_app()
check("history message without id gets one once and keeps it", _first and legacy["message_id"] == _first)
check("widget keys derive from message_id", any(k and k.startswith("fb_up_") and legacy["message_id"] in k for k in calls["button_keys"]))

# pause / resume sidebar-type messages also get ids and are logged
fresh_state(); env = run_app()
env["_append_system_assistant_message"]("Simulação pausada.")
check("system assistant message has id and is logged with it", ss.messages[-1]["message_id"] == logged[-1]["message_id"])

# ═════════════════════════════════════════════════════════════════════════════
print("\n═══ 13. DB failures never crash the chat ═══\n")
# ═════════════════════════════════════════════════════════════════════════════
fresh_state(); env = run_app()
msg = env["_make_assistant_message"]("x", user_message="y")
ss.messages.append(msg)
fail["submit"] = True
try:
    env["_record_rating"](msg, "up"); env["_render_feedback_widget"](msg); crashed = False
except Exception as e:
    crashed = True
check("submit_feedback DB error: no exception, friendly toast, no ✅ state",
      not crashed and any("Não foi possível" in t for t in calls["toast"]) and msg["message_id"] not in ss["_feedback_cache"])
fresh_state(); fail["load"] = True
try:
    run_app(); ok = True
except Exception:
    ok = False
check("feedback lookup failing at render: chat still renders", ok)
fresh_state(); fail["log"] = True
try:
    run_app(); run_app("oi, tudo bem?"); ok = True
except Exception as e:
    ok = False; print(e)
check("chat_logs write failing: reply still produced and stored", ok and ss.messages[-1]["role"] == "assistant" and len(ss.messages) == 3)
fresh_state()
script.update(rating=None, submit=True)
run_app(); env_msg = ss.messages[0]
fresh_state(); env = run_app(); m = env["_make_assistant_message"]("z"); ss.messages.append(m)
script.update(rating=None, submit=True)
env["_render_feedback_widget"](m)
check("submit without choosing 👍/👎 saves nothing", submitted == [])

failed = [n for n, ok in results if not ok]
print(f"\nResults: {len(results) - len(failed)} passed, {len(failed)} failed out of {len(results)} tests")
sys.exit(1 if failed else 0)
