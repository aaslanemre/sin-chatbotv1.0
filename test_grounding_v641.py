"""
v6.4.1 — grounding confidence: classification, config validation, meta replies,
where badges/disclosure apply, cosine guard, persistence (sqlite harness), admin helpers.

Run from repo root:  python3 test_grounding_v641.py
"""
import copy, hashlib, importlib.util, logging, runpy, sqlite3, sys, types

# ── Streamlit mock (records captions/markdown) ───────────────────────────────
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
rec = {"caption": [], "markdown": [], "toast": []}
script = {"rating": None, "category": None, "comment": "", "submit": False, "prompt": None}
st = types.ModuleType("streamlit")
st.session_state = ss
for n in ["set_page_config", "stop", "error", "tabs", "text_input", "divider", "button", "info",
          "success", "warning", "rerun"]:
    setattr(st, n, lambda *a, **kw: None)
st.caption = lambda *a, **kw: rec["caption"].append(a[0] if a else "")
st.markdown = lambda *a, **kw: rec["markdown"].append(a[0] if a else "")
st.sidebar = _Ctx()
st.columns = lambda n, **kw: [_Ctx() for _ in range(n if isinstance(n, int) else len(n))]
st.chat_message = lambda *a, **kw: _Ctx()
st.spinner = lambda *a, **kw: _Ctx()
st.expander = lambda *a, **kw: _Ctx()
st.container = lambda *a, **kw: _Ctx()  # v6.5.0 banner
st.toggle = st.progress = lambda *a, **kw: None  # v6.5.0 sidebar
st.popover = lambda *a, **kw: _Ctx()
st.form = lambda *a, **kw: _Ctx()
st.radio = lambda l, opts, index=None, **kw: script["rating"] or (opts[index] if index is not None else None)
st.selectbox = lambda l, opts, index=0, **kw: script["category"] or opts[index]
st.text_area = lambda l, value="", **kw: script["comment"] or value
st.form_submit_button = lambda *a, **kw: script["submit"]
st.toast = lambda msg, **kw: rec["toast"].append(msg)
st.chat_input = lambda *a, **kw: script["prompt"]
sys.modules["streamlit"] = st
sys.modules["pandas"] = types.ModuleType("pandas")

for m in ["agents.pwf_agent", "agents.results_analyzer", "memory.session_memory", "memory.persistent_memory",
          "auth.db", "auth.auth_service", "prompts.system_prompt", "rag.chain", "rag.retriever"]:
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
distance = {"value": "Cosine"}
sys.modules["rag.retriever"].get_collection_distance = lambda: distance["value"]

svc = sys.modules["auth.auth_service"]
logged, submitted = [], []
for fn in ["signup", "login", "create_session", "update_session", "save_paused_state",
           "load_paused_state", "clear_paused_state"]:
    setattr(svc, fn, lambda *a, **kw: None)
svc.log_chat_message = lambda *a, **kw: logged.append((a, kw))
svc.submit_feedback = lambda *a, **kw: submitted.append((a, kw))
svc.get_user_feedback_for_session = lambda u, s: {}

from agents import grounding as G
from agents.session_analysis import grounding_caption, grounding_vs_rating, build_markdown_report

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
results = []
def check(name, cond, detail=""):
    print(f"  [{PASS if cond else FAIL}] {name}")
    if not cond and detail: print(f"         {detail}")
    results.append((name, bool(cond)))

# ═══ 1. classification boundaries ═══
print("\n═══ classify_grounding ═══\n")
c = lambda x: G.classify_grounding(x, 0.75, 0.65)
check("0.75 → green", c([0.75]) == "green")
check("0.7499 → yellow", c([0.7499]) == "yellow")
check("0.65 → yellow", c([0.65]) == "yellow")
check("0.6499 → red", c([0.6499]) == "red")
check("[] and None → red", c([]) == "red" and c(None) == "red")
check("dict scores accepted, top-1 = max", c([{"source": "a", "score": 0.5}, {"source": "b", "score": 0.8}]) == "green")

settings_src = open("config/settings.py").read()
env_src = open(".env.example").read()
check("thresholds read from env in settings.py with 0.75/0.65 defaults",
      'GROUNDING_THRESHOLD", 0.75' in settings_src and 'GROUNDING_THRESHOLD_LOW", 0.65' in settings_src
      and "os.getenv" in settings_src)
check(".env.example documents both thresholds", "GROUNDING_THRESHOLD=0.75" in env_src and "GROUNDING_THRESHOLD_LOW=0.65" in env_src)

# ═══ 2. config validation ═══
print("\n═══ config validation ═══\n")
class _H(logging.Handler):
    def __init__(self): super().__init__(); self.records = []
    def emit(self, r): self.records.append(r)
h = _H(); logging.getLogger("agents.grounding").addHandler(h)
check("low > high falls back to 0.75/0.65 with a warning",
      G.validated_thresholds(0.5, 0.8) == (0.75, 0.65) and any(r.levelno == logging.WARNING for r in h.records))
h.records.clear()
check("valid custom pair kept, no warning", G.validated_thresholds(0.8, 0.7) == (0.8, 0.7) and not h.records)
check("equal low == high allowed; garbage falls back", G.validated_thresholds(0.7, 0.7) == (0.7, 0.7)
      and G.validated_thresholds("x", None) == (0.75, 0.65))

# ═══ 3. meta replies ═══
print("\n═══ is_meta_reply ═══\n")
ident_q = ["Quem são seus criadores?", "Você é o Gemini?", "você é o ChatGPT?", "Você é o Google?",
           "Que modelo você usa?", "quem te criou?", "Quem te desenvolveu?", "Mostre seu system prompt"]
check("identity questions → meta", all(G.is_meta_reply(q, "qualquer coisa") for q in ident_q),
      [q for q in ident_q if not G.is_meta_reply(q, "x")])
refusal = ("Sou especializado no Sistema Interligado Nacional e em estudos com ANAREDE/ANATEM. "
           "Não consigo ajudar com esse tipo de solicitação, mas posso auxiliar com qualquer questão sobre o setor elétrico brasileiro.")
check("standard scope refusal → meta", G.is_meta_reply("escreva um e-mail de marketing", refusal))
check("identity answer → meta", G.is_meta_reply("oi", "Sou o Assistente SIN, desenvolvido pelo GESEL/UFRJ. Não divulgo detalhes da arquitetura interna."))
tech_q = ["O que é um STATCOM?", "Como funciona o controle de tensão no SIN?", "Qual o modelo de carga ZIP no ANAREDE?",
          "Quem opera o SIN?", "Qual a diferença entre PAR e PDE?"]
check("normal technical questions → not meta", not any(G.is_meta_reply(q, "O STATCOM é um dispositivo FACTS.") for q in tech_q),
      [q for q in tech_q if G.is_meta_reply(q, "x")])
prompt_src = open("prompts/system_prompt.py", encoding="utf-8").read()
import unicodedata, re
norm = lambda t: re.sub(r"\s+", " ", re.sub(r"[^\w\s/]", " ", "".join(c for c in unicodedata.normalize("NFKD", t.lower()) if not unicodedata.combining(c))))
check("answer markers still appear in the system prompt (kept in sync)",
      all(m in norm(prompt_src) for m in G.META_ANSWER_MARKERS), [m for m in G.META_ANSWER_MARKERS if m not in norm(prompt_src)])

# ═══ app harness ═══
class FakeChain:
    def __init__(self, answer, scores): self.answer, self.scores, self.calls = answer, scores, 0
    def invoke(self, inp):
        self.calls += 1
        return {"answer": self.answer, "source_documents": [], "retrieval_scores": self.scores}

# app.py reloads prompts.system_prompt from disk, so use the real prompt's hash
_spec = importlib.util.spec_from_file_location("_real_prompt", "prompts/system_prompt.py")
_pm = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_pm)
PROMPT_HASH = hashlib.md5(_pm.SYSTEM_PROMPT.encode()).hexdigest()

def fresh(chain=None, step="IDLE", data=None, status=None):
    ss.clear()
    ss.update({"db_initialized": True, "user": {"id": "u1", "email": "t@t", "full_name": "T"},
               "session_id": "s1", "chain": chain, "chain_error": None,
               "_prompt_hash": PROMPT_HASH, "simulation_mode": status == "active",
               "sim_step": step, "sim_data": copy.deepcopy(data or {}), "sim_status": status, "study": SS_CLS()})
    logged.clear(); submitted.clear()
    for k in rec: rec[k].clear()
    script.update(rating=None, category=None, comment="", submit=False, prompt=None)
    G.reset_cosine_cache(); distance["value"] = "Cosine"

def run(prompt=None):
    script["prompt"] = prompt
    return runpy.run_path("app.py", run_name="app_under_test")

def last_assistant():
    return [m for m in ss.messages if m["role"] == "assistant"][-1]

def has_badge():
    return any(l in rec["caption"] for l in G.BADGE_LABELS.values())

SC = lambda v: [{"source": "docs/manual_anarede.pdf", "score": v}, {"source": "docs/b.pdf", "score": v - 0.1}]

# ═══ 5. disclosure only for red ═══
print("\n═══ badges and disclosure on free RAG answers ═══\n")
for score, level, badge in [(0.80, "green", "🟢 Baseado nos documentos"),
                            (0.70, "yellow", "🟡 Parcialmente baseado nos documentos"),
                            (0.50, "red", "🔴 Conhecimento geral")]:  # v6.5.0 PT-BR labels
    fresh(FakeChain("O STATCOM é um dispositivo FACTS.", SC(score)))
    run(); run("O que é um STATCOM?")
    m = last_assistant()
    check(f"{level}: badge shown, level/score stored on message", badge in rec["caption"]
          and m["grounding_level"] == level and abs(m["grounding_score"] - score) < 1e-9, (m.get("grounding_level"), rec["caption"]))
    check(f"{level}: disclosure {'present' if level == 'red' else 'absent'}",
          m["content"].startswith(G.DISCLOSURE) == (level == "red") and (G.DISCLOSURE in m["content"]) == (level == "red"))
    rec["caption"].clear(); run()
    check(f"{level}: badge shown again on history replay", badge in rec["caption"])
    row = [kw for a, kw in logged if a[2] == "assistant" and a[3] == m["content"]][-1]
    check(f"{level}: chat_logs call carries score and level", row.get("grounding_level") == level and abs(row["grounding_score"] - score) < 1e-9, row)

fresh(FakeChain("O STATCOM é um dispositivo FACTS.", []))
run(); run("O que é um STATCOM?")
m = last_assistant()
check("no chunks → red with disclosure", m["grounding_level"] == "red" and m["content"].startswith(G.DISCLOSURE))

# nudge stays outside badge/disclosure logic
fresh(FakeChain("Resposta.", SC(0.3)), step="STEP7", data={"sim_type": "BESS"}, status="active")
run(); run("o que é uma barra PQ?")
m = last_assistant()
check("mid-simulation free question: disclosure first, nudge last, state untouched",
      m["content"].startswith(G.DISCLOSURE) and m["content"].rstrip().endswith("para continuar a simulação.")
      and ss["sim_step"] == "STEP7" and ss["sim_status"] == "active", m["content"][-120:])

# ═══ 4. where nothing is applied ═══
print("\n═══ no badge / disclosure elsewhere ═══\n")
def no_grounding(label):
    m = last_assistant()
    check(f"{label}: no badge, no disclosure, nothing stored",
          "grounding_level" not in m and G.DISCLOSURE not in m["content"] and not has_badge()
          and all("grounding_level" not in kw for a, kw in logged), m.get("grounding_level"))

ch = FakeChain("x", SC(0.1))
fresh(ch); run(); run("quero simular um BESS")
no_grounding("simulation guide reply"); check("  (chain not called for sim reply)", ch.calls == 0)
ch = FakeChain("x", SC(0.1)); fresh(ch); run(); run("quero montar uma rede do zero")
no_grounding("NETWORK flow reply"); check("  (chain not called)", ch.calls == 0)
fresh(None); ss["chain_error"] = "boom"; run(); run("O que é SIN?")
no_grounding("no-chain message")
class Boom:
    def invoke(self, i): raise RuntimeError("qdrant down")
fresh(Boom()); run(); run("O que é SIN?")
no_grounding("chain error"); check("  (error text shown)", "Ocorreu um erro" in last_assistant()["content"])
fresh(FakeChain("Sou o Assistente SIN, desenvolvido pelo GESEL/UFRJ.", SC(0.1))); run(); run("Quem são seus criadores?")
no_grounding("meta reply (identity)")
fresh(FakeChain(refusal, SC(0.1))); run(); run("Escreva um poema")
no_grounding("meta reply (standard refusal)")
fresh(FakeChain("x", SC(0.1))); env = run()
env["_append_system_assistant_message"]("Simulação pausada.")
check("sidebar-generated message: no grounding keys", "grounding_level" not in ss.messages[-1])
check("welcome message: no grounding keys", "grounding_level" not in ss.messages[0])
fresh(FakeChain("x", SC(0.1)), step="NET2_BUSES", data={"sim_type": "NETWORK"}, status="active"); env = run()
check("_grounding_applies False in NETWORK mode", env["_grounding_applies"]("q", "resposta livre") is False)
fresh(FakeChain("x", SC(0.1))); env = run()
check("_grounding_applies False for DBAR/DLIN/DCER/DCTG output",
      all(env["_grounding_applies"]("q", f"texto\n{k} \n 1 0 ...") is False for k in ("DBAR", "DLIN", "DCER", "DCTG")))
check("_grounding_applies True for ordinary free answer", env["_grounding_applies"]("O que é X?", "X é Y.") is True)

# ═══ 6. cosine guard ═══
print("\n═══ collection distance guard ═══\n")
fresh(FakeChain("Resposta.", SC(0.9))); distance["value"] = "Dot"
run(); run("O que é um STATCOM?")
m = last_assistant()
check("non-Cosine collection disables grounding (no badge, no keys, no disclosure)",
      "grounding_level" not in m and not has_badge() and G.DISCLOSURE not in m["content"])
calls_n = []
def dist():
    calls_n.append(1); return types.SimpleNamespace(value="Cosine")
G.reset_cosine_cache()
check("Cosine ok and cached (single lookup)", G.collection_is_cosine(dist) and G.collection_is_cosine(dist) and len(calls_n) == 1)
G.reset_cosine_cache()
def broken(): raise RuntimeError("no qdrant")
check("lookup failure disables grounding without caching", G.collection_is_cosine(broken) is False and G.collection_is_cosine(dist) is True)

# ═══ 8. feedback submit leaves sim state alone, snapshots grounding ═══
print("\n═══ feedback + grounding ═══\n")
fresh(FakeChain("R", SC(0.55)), step="STEP7", data={"sim_type": "BESS", "db": "ONS"}, status="active")
run(); run("o que é uma barra PQ?")
m = last_assistant()
before = copy.deepcopy({k: ss[k] for k in ("sim_step", "sim_data", "sim_status", "simulation_mode")})
nmsg = len(ss.messages)
env = run()
env["_record_rating"](m, "down")  # v6.5.0 one-click 👎 (widget callback)
script.update(category="tecnico", comment="errado", submit=True, prompt=None)
run()  # rerun with the optional comment form submitted
after = {k: ss[k] for k in ("sim_step", "sim_data", "sim_status", "simulation_mode")}
check("feedback submit leaves sim_step/sim_data/sim_status/mode identical, no new messages",
      before == after and len(ss.messages) == nmsg, (before, after))
args, kw = submitted[-1]
check("feedback snapshot includes grounding score + level", kw.get("grounding_level") == "red" and abs(kw["grounding_score"] - 0.55) < 1e-9, kw)

# ═══ 7. persistence (sqlite harness) ═══
print("\n═══ persistence ═══\n")
lite = sqlite3.connect(":memory:", check_same_thread=False); lite.row_factory = sqlite3.Row
lite.execute("""CREATE TABLE feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id, session_id, message_id, rating,
  category, comment, assistant_message, user_message, sim_type, sim_step_before, sim_step_after, app_version,
  status DEFAULT 'novo', admin_note, created_at DEFAULT CURRENT_TIMESTAMP, updated_at DEFAULT CURRENT_TIMESTAMP,
  grounding_score REAL, grounding_level TEXT, UNIQUE (user_id, message_id))""")
lite.execute("""CREATE TABLE chat_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id, session_id, role, message,
  sim_step, message_id, sim_type, grounding_score REAL, grounding_level TEXT, created_at DEFAULT CURRENT_TIMESTAMP,
  input_source TEXT)""")  # v6.5.0 column (auth/db.py)
class _Cur:
    def __init__(self): self.c = lite.cursor()
    def execute(self, sql, params=()):
        self.c.execute(sql.replace("%s::uuid", "?").replace("%s", "?").replace("now()", "CURRENT_TIMESTAMP"), params); return self
    def fetchall(self): return [dict(r) for r in self.c.fetchall()]
    def close(self): pass
class _Conn:
    def cursor(self, *a, **k): return _Cur()
    def commit(self): lite.commit()
    def rollback(self): lite.rollback()
    def close(self): pass
sys.modules["auth.db"].get_connection = lambda: _Conn()
sys.modules["auth.db"].get_cursor = lambda c: c.cursor()
spec = importlib.util.spec_from_file_location("real_auth", "auth/auth_service.py")
real = importlib.util.module_from_spec(spec); spec.loader.exec_module(real)

real.log_chat_message("u1", "s1", "assistant", "resp", "IDLE", message_id="m1", sim_type=None,
                      grounding_score=0.78, grounding_level="green")
real.log_chat_message("u1", "s1", "assistant", "antiga", "STEP2", message_id="m0")  # old-style, no grounding
rows = [dict(r) for r in lite.execute("SELECT * FROM chat_logs ORDER BY id")]
check("chat_logs stores grounding_score/level", (rows[0]["grounding_score"], rows[0]["grounding_level"]) == (0.78, "green"), rows[0])
check("rows logged without grounding stay NULL", rows[1]["grounding_score"] is None and rows[1]["grounding_level"] is None)
real.submit_feedback("u1", "s1", "m1", "down", "tecnico", "x", "resp", "q", None, "IDLE", "IDLE", "v6.4.1",
                     grounding_score=0.78, grounding_level="green")
real.submit_feedback("u1", "s1", "m0", "up", None, "", "antiga", "q", "BESS", "STEP1", "STEP2", "v6.4.0")
fbs = real.get_user_feedback_for_session("u1", "s1")
check("feedback snapshot stores grounding", (fbs["m1"]["grounding_score"], fbs["m1"]["grounding_level"]) == (0.78, "green"))
check("old feedback row: NULL grounding, renders as empty caption",
      fbs["m0"]["grounding_level"] is None and grounding_caption(fbs["m0"]["grounding_level"], fbs["m0"]["grounding_score"]) == "")
real.submit_feedback("u1", "s1", "m1", "up", None, "ok", "resp", "q", None, "IDLE", "IDLE", "v6.4.1")
check("resubmit keeps the original grounding snapshot",
      real.get_user_feedback_for_session("u1", "s1")["m1"]["grounding_level"] == "green")

# ═══ admin helpers ═══
print("\n═══ admin helpers ═══\n")
check("caption '🟢 0.78'", grounding_caption("green", 0.78) == "🟢 0.78" and grounding_caption("red", 0.5) == "🔴 0.50")
check("caption empty for old rows", grounding_caption(None, None) == "")
data = [{"grounding_level": "green", "grounding_score": 0.80, "rating": "up"},
        {"grounding_level": "green", "grounding_score": 0.90, "rating": "up"},
        {"grounding_level": "green", "grounding_score": 0.76, "rating": "down"},
        {"grounding_level": "red", "grounding_score": 0.40, "rating": "down"},
        {"grounding_level": None, "grounding_score": None, "rating": "down"}]
t = {r["level"]: r for r in grounding_vs_rating(data)}
check("grounding × rating table: counts and avg score per rating",
      (t["green"]["up"], t["green"]["down"], t["green"]["avg_up"], t["green"]["avg_down"]) == (2, 1, 0.85, 0.76)
      and (t["red"]["up"], t["red"]["down"], t["red"]["avg_up"], t["red"]["avg_down"]) == (0, 1, None, 0.4) and "yellow" not in t, t)
md = build_markdown_report([], [{"rating": "down", "category": "tecnico", "comment": "c", "assistant_message": "a",
                                 "sim_type": "BESS", "sim_step_after": "STEP7", "status": "novo",
                                 "grounding_level": "red", "grounding_score": 0.41}])
check("Markdown export items include the grounding level", "grounding: 🔴 0.41" in md, md)

failed = [n for n, ok in results if not ok]
print(f"\nResults: {len(results) - len(failed)} passed, {len(failed)} failed out of {len(results)} tests")
sys.exit(1 if failed else 0)
