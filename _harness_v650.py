"""
Shared harness for the v6.5.0 suites (test_ux_v650.py, test_structured_v650.py).

- Recording Streamlit mock: every element is appended to EV as a tuple, widgets
  record their callbacks so a test can "click" by calling them, then rerun.
- The REAL auth/auth_service.py on an in-memory sqlite database (schema mirrors
  auth/db.py), so logging, feedback upserts and per-user queries run real SQL.
- The REAL PWF generators (agents.pwf_agent / agents.network_builder).
Only the LLM chain and Qdrant are faked.
"""
import copy
import hashlib
import importlib.util
import os
import re
import runpy
import sqlite3
import sys
import tempfile
import types
import uuid

_TMP = tempfile.mkdtemp(prefix="sin_v650_")
os.environ.setdefault("MODIFIED_PWF_DIR", os.path.join(_TMP, "modified_pwf"))
os.environ.setdefault("RESULTS_DIR", os.path.join(_TMP, "results"))
os.environ.setdefault("MEMORY_STORE_PATH", os.path.join(_TMP, "memory", "study.json"))

# python-dotenv is not installed in the test environment: config.settings only
# needs load_dotenv to exist.
if "dotenv" not in sys.modules:
    _d = types.ModuleType("dotenv")
    _d.load_dotenv = lambda *a, **kw: None
    sys.modules["dotenv"] = _d


# ── Recording Streamlit mock ──────────────────────────────────────────────────
class SS(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v

    def __delattr__(self, k):
        del self[k]


class StopRun(Exception):
    pass


ss = SS()
EV = []                       # rendered elements, in order
SCRIPT = {"prompt": None, "press": set(), "submit": False, "values": {}}
st = types.ModuleType("streamlit")
st.session_state = ss


class Ctx:
    def __init__(self, kind=None, label=None):
        self.kind, self.label = kind, label

    def __enter__(self):
        if self.kind:
            EV.append(("enter", self.kind, self.label))
        return self

    def __exit__(self, *a):
        if self.kind:
            EV.append(("exit", self.kind, self.label))
        return False

    def __getattr__(self, n):
        fn = getattr(st, n, None)
        return fn if fn is not None else (lambda *a, **kw: Ctx())


class Slot(Ctx):
    _n = 0

    def __init__(self):
        super().__init__()
        Slot._n += 1
        self.id = Slot._n

    def markdown(self, text, **kw):
        EV.append(("slot_md", self.id, text))

    def empty(self):
        EV.append(("slot_clear", self.id))

    def container(self, **kw):
        return Ctx("slot", self.id)


def _value(key, default=None):
    if key is not None and key in ss:
        return ss[key]
    return SCRIPT["values"].get(key, default)


def _noop(*a, **kw):
    return None


for _n in ["set_page_config", "error", "tabs", "divider", "info", "success", "warning",
           "rerun", "spinner_", "json"]:
    setattr(st, _n, _noop)
st.stop = lambda: (_ for _ in ()).throw(StopRun())
st.tabs = lambda labels: [Ctx("tab", l) for l in labels]
st.markdown = lambda body="", **kw: EV.append(("markdown", body))
st.write = lambda body="", **kw: EV.append(("markdown", str(body)))
st.caption = lambda body="", **kw: EV.append(("caption", body, kw.get("help")))
st.toast = lambda body, **kw: EV.append(("toast", body))
st.sidebar = Ctx("sidebar")
st.chat_message = lambda role, **kw: Ctx("chat", role)
st.spinner = lambda *a, **kw: Ctx()
st.expander = lambda label, **kw: (EV.append(("expander", label)), Ctx("expander", label))[1]
st.popover = lambda label, **kw: (EV.append(("popover", label)), Ctx("popover", label))[1]
st.container = lambda **kw: Ctx("container")
st.form = lambda key=None, **kw: (EV.append(("form", key)), Ctx("form", key))[1]
st.columns = lambda spec, **kw: [Ctx() for _ in range(spec if isinstance(spec, int) else len(spec))]
st.empty = lambda: Slot()
st.progress = lambda value, text=None, **kw: EV.append(("progress", value, text))
st.chat_input = lambda *a, **kw: SCRIPT["prompt"]


def _write_stream(gen):
    text = "".join(str(c) for c in gen)
    EV.append(("stream", text))
    return text


st.write_stream = _write_stream


def _button(label, key=None, on_click=None, args=(), kwargs=None, **kw):
    EV.append(("button", label, key, on_click, tuple(args or ()), kwargs or {}, kw))
    return key in SCRIPT["press"] or label in SCRIPT["press"]


st.button = _button


def _form_submit_button(label="Submit", key=None, on_click=None, args=(), kwargs=None, **kw):
    EV.append(("submit", label, key, on_click, tuple(args or ()), kwargs or {}))
    return SCRIPT["submit"]


st.form_submit_button = _form_submit_button


def _feedback(options="thumbs", key=None, on_change=None, args=(), **kw):
    EV.append(("feedback", key, on_change, tuple(args or ())))
    return _value(key)


st.feedback = _feedback


def _download_button(label, data=None, file_name=None, mime=None, key=None, **kw):
    EV.append(("download", label, file_name, data, key))
    return False


st.download_button = _download_button


def _input(kind):
    def f(label, *a, key=None, value=None, index=0, options=None, on_change=None, args=(), **kw):
        opts = options if options is not None else (a[0] if a else None)
        default = value
        if kind in ("selectbox", "radio", "segmented_control") and opts is not None:
            default = opts[index] if (index is not None and opts) else None
        EV.append(("input", kind, label, key, on_change, tuple(args or ()), kw.get("help")))
        return _value(key, default)
    return f


for _k in ["number_input", "text_input", "text_area", "selectbox", "radio", "toggle",
           "segmented_control", "checkbox", "date_input"]:
    setattr(st, _k, _input(_k))

sys.modules["streamlit"] = st
sys.modules["pandas"] = sys.modules.get("pandas") or types.ModuleType("pandas")

# ── sqlite stand-in for PostgreSQL (schema mirrors auth/db.py) ────────────────
lite = sqlite3.connect(":memory:", check_same_thread=False)
lite.row_factory = sqlite3.Row
lite.executescript("""
CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT UNIQUE, password_hash TEXT, full_name TEXT,
  role TEXT DEFAULT 'user', verified BOOLEAN DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  last_login TIMESTAMP, verification_token TEXT, verification_sent_at TIMESTAMP,
  last_seen_version TEXT, ui_mode TEXT DEFAULT 'iniciante');
CREATE TABLE sessions (id TEXT PRIMARY KEY, user_id TEXT, started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  last_message_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, message_count INTEGER DEFAULT 0, sim_type TEXT,
  final_sim_step TEXT, flagged BOOLEAN DEFAULT 0, flag_note TEXT, paused_state TEXT);
CREATE TABLE chat_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, session_id TEXT, role TEXT,
  message TEXT, sim_step TEXT, created_at TIMESTAMP DEFAULT (strftime('%Y-%m-%d %H:%M:%f','now')),
  message_id TEXT, sim_type TEXT, grounding_score REAL, grounding_level TEXT, input_source TEXT);
CREATE TABLE feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT, session_id TEXT, message_id TEXT,
  rating TEXT, category TEXT, comment TEXT, assistant_message TEXT, user_message TEXT, sim_type TEXT,
  sim_step_before TEXT, sim_step_after TEXT, app_version TEXT, status TEXT DEFAULT 'novo', admin_note TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  grounding_score REAL, grounding_level TEXT, UNIQUE (user_id, message_id));
""")
DB_FAIL = {"on": False}


def _sql(sql):
    sql = re.sub(r"%s::(uuid|jsonb)", "?", sql).replace("%s", "?")
    return sql.replace("now()", "CURRENT_TIMESTAMP")


class _Cur:
    def __init__(self):
        self.c = lite.cursor()
        self.rowcount = 0

    def execute(self, sql, params=()):
        if DB_FAIL["on"]:
            raise RuntimeError("db down")
        params = [str(p) if isinstance(p, uuid.UUID) else p for p in params]
        self.c.execute(_sql(sql), params)
        self.rowcount = self.c.rowcount
        return self

    def fetchone(self):
        r = self.c.fetchone()
        return dict(r) if r is not None else None

    def fetchall(self):
        return [dict(r) for r in self.c.fetchall()]

    def close(self):
        pass


class _Conn:
    def cursor(self, *a, **kw):
        return _Cur()

    def commit(self):
        lite.commit()

    def rollback(self):
        lite.rollback()

    def close(self):
        pass


_db = types.ModuleType("auth.db")
_db.get_connection = lambda: _Conn()
_db.get_cursor = lambda conn: conn.cursor()
_db.init_db = lambda: None
sys.modules["auth.db"] = _db

_spec = importlib.util.spec_from_file_location("auth.auth_service", "auth/auth_service.py")
svc = importlib.util.module_from_spec(_spec)
sys.modules["auth.auth_service"] = svc
_spec.loader.exec_module(svc)


def add_user(uid, email=None, **cols):
    lite.execute("INSERT INTO users (id, email, password_hash, full_name) VALUES (?, ?, 'x', ?)",
                 (uid, email or f"{uid}@t", uid.upper()))
    for k, v in cols.items():
        lite.execute(f"UPDATE users SET {k} = ? WHERE id = ?", (v, uid))
    lite.commit()


def rows(sql, params=()):
    return [dict(r) for r in lite.execute(sql, params)]


# ── Fake RAG pieces ───────────────────────────────────────────────────────────
_ret = types.ModuleType("rag.retriever")
_ret.get_collection_distance = lambda: "Cosine"
sys.modules["rag.retriever"] = _ret
sys.modules["rag.chain"] = types.ModuleType("rag.chain")


class Doc:
    def __init__(self, source, text="", page=None):
        self.metadata = {"source": source}
        if page is not None:
            self.metadata["page"] = page
        self.page_content = text


class StreamChain:
    """Same interface as rag.chain.SINChain (retrieve / stream / generate / remember / invoke)."""

    def __init__(self, chunks, scores, fail_stream=False, fail_after=None):
        self.chunks, self.scores = list(chunks), scores
        self.fail_stream, self.fail_after = fail_stream, fail_after
        self.retrieve_calls, self.generate_calls, self.remembered = 0, 0, []
        self.last_inputs = None

    def retrieve(self, question):
        self.retrieve_calls += 1
        return {"docs": [Doc(s["source"]) for s in self.scores],
                "retrieval_scores": copy.deepcopy(self.scores), "context": "ctx"}

    def stream(self, inputs, retrieved):
        self.last_inputs = inputs
        if self.fail_stream:
            raise RuntimeError("stream broke")
        for i, c in enumerate(self.chunks):
            if self.fail_after is not None and i >= self.fail_after:
                raise RuntimeError("stream broke mid-way")
            yield c

    def generate(self, inputs, retrieved):
        self.generate_calls += 1
        self.last_inputs = inputs
        return "".join(self.chunks)

    def remember(self, q, a):
        self.remembered.append((q, a))

    def invoke(self, inputs):  # not used when streaming works
        r = self.retrieve(inputs["question"])
        return {"answer": self.generate(inputs, r), "source_documents": r["docs"],
                "retrieval_scores": r["retrieval_scores"]}


def scores(*pairs):
    return [{"source": f"docs/{s}", "score": v, "excerpt": f"trecho de {s} com {v}"} for s, v in pairs]


# ── App runner ────────────────────────────────────────────────────────────────
_pspec = importlib.util.spec_from_file_location("_real_prompt", "prompts/system_prompt.py")
_pm = importlib.util.module_from_spec(_pspec)
_pspec.loader.exec_module(_pm)
PROMPT_HASH = hashlib.md5(_pm.SYSTEM_PROMPT.encode()).hexdigest()

USER = {"id": "userA", "email": "a@t", "full_name": "A", "last_seen_version": "v6.5.0",
        "ui_mode": "iniciante"}


def fresh(chain=None, step="IDLE", data=None, status=None, user=None, session_id="sessA"):
    ss.clear()
    u = dict(user or USER)
    if not rows("SELECT id FROM users WHERE id = ?", (u["id"],)):
        add_user(u["id"], u.get("email"))
    svc.create_session(session_id, u["id"])
    ss.update({"db_initialized": True, "user": u, "session_id": session_id,
               "chain": chain, "chain_error": None, "_prompt_hash": PROMPT_HASH,
               "simulation_mode": status == "active", "sim_step": step,
               "sim_data": copy.deepcopy(data or {}), "sim_status": status})
    EV.clear()
    SCRIPT.update(prompt=None, press=set(), submit=False, values={})
    DB_FAIL["on"] = False
    from agents import grounding as G
    G.reset_cosine_cache()


def run(prompt=None, clear=True):
    if clear:
        EV.clear()
    SCRIPT["prompt"] = prompt
    try:
        return runpy.run_path("app.py", run_name="app_under_test")
    except StopRun:
        return None
    finally:
        SCRIPT["prompt"] = None


def assistants():
    return [m for m in ss.messages if m["role"] == "assistant" and not m.get("welcome")]


def last_assistant():
    return assistants()[-1]


def sim_state():
    return copy.deepcopy({k: ss.get(k) for k in ("sim_step", "sim_data", "sim_status", "simulation_mode")})


def events(kind):
    return [e for e in EV if e[0] == kind]


PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
RESULTS = []


def check(name, cond, detail=""):
    print(f"  [{PASS if cond else FAIL}] {name}")
    if not cond and detail != "":
        print(f"         {str(detail)[:600]}")
    RESULTS.append((name, bool(cond)))


def section(title):
    print(f"\n═══ {title} ═══\n")


def finish():
    failed = [n for n, ok in RESULTS if not ok]
    print(f"\nResults: {len(RESULTS) - len(failed)} passed, {len(failed)} failed out of {len(RESULTS)} tests")
    sys.exit(1 if failed else 0)
