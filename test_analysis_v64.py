"""
v6.4.0 — pure analysis, feedback matching, filters, aggregation, Markdown export
and admin transcript rendering (no Streamlit / DB / pandas needed).

Run from repo root:  python3 test_analysis_v64.py
"""
import sys
import types

# ── Minimal stubs so admin.panel can be imported (it is never run against a DB) ──
class _Ctx:
    def __enter__(self): return self
    def __exit__(self, *a): return False

_log = []
_st = types.ModuleType("streamlit")
_st.session_state = {}
_st.markdown = lambda *a, **kw: _log.append(("markdown", a[0] if a else ""))
_st.caption = lambda *a, **kw: _log.append(("caption", a[0] if a else ""))
_st.info = lambda *a, **kw: _log.append(("info", a[0] if a else ""))
_st.container = lambda *a, **kw: _Ctx()
sys.modules["streamlit"] = _st
sys.modules["pandas"] = types.ModuleType("pandas")

from agents.session_analysis import (
    analyze_session, timeline_text, summarize_session, filter_session_summaries,
    match_feedback_to_messages, aggregate_by_step, build_markdown_report,
)
import admin.panel as panel

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
results = []


def check(name, cond, detail=""):
    print(f"  [{PASS if cond else FAIL}] {name}")
    if not cond and detail:
        print(f"         {detail}")
    results.append((name, bool(cond)))


def U(text, step, stype="BESS", mid=None):
    return {"role": "user", "message": text, "sim_step": step, "sim_type": stype, "message_id": mid}


def A(text, step, stype="BESS", mid=None):
    return {"role": "assistant", "message": text, "sim_step": step, "sim_type": stype, "message_id": mid}


# ── 5. not advancing ─────────────────────────────────────────────────────────
print("\n═══ analyze_session ═══\n")
stuck7 = [U("quero simular", "IDLE", None), A("base?", "STEP1")]
for i in range(4):
    stuck7 += [U(f"resposta {i}", "STEP7"), A("barra inválida", "STEP7")]
a = analyze_session(stuck7)
check("4 consecutive user turns at STEP7 → not_advancing includes STEP7", "STEP7" in a["not_advancing"], a)
check("STEP7 in stuck_steps", "STEP7" in a["stuck_steps"])
check("timeline collapses to STEP7 ×4", ("BESS", "STEP7", 4) in a["steps"], a["steps"])
check("timeline text has ⚠️ and ⛔", "STEP7 ×4 ⚠️" in timeline_text(a) and "⛔" in timeline_text(a), timeline_text(a))
a2 = analyze_session([U("x", "STEP7"), A("y", "STEP7"), U("z", "STEP7"), A("w", "STEP8")])
check("2 turns → not flagged", a2["not_advancing"] == [])
a3 = analyze_session(stuck7, threshold=5)
check("threshold is a parameter", a3["not_advancing"] == [])
net = []
for i in range(6):
    net += [U(f"barra {i}", "NET2_BUSES", "NETWORK"), A("ok", "NET2_BUSES", "NETWORK")]
check("bus-by-bus NET2_BUSES entry is not flagged as stuck", analyze_session(net)["not_advancing"] == [])

# ── 6. outcomes ──────────────────────────────────────────────────────────────
ab = [U("quero simular", "IDLE", None), A("base?", "STEP1"), U("ONS", "STEP1"), A("ano?", "STEP2"),
      U("2028", "STEP7"), A("potência?", "STEP8")]
check("ends at STEP8 without encerrar → abandoned", analyze_session(ab)["outcome"] == "abandoned")
fin = ab + [U("ok", "STEP8"), A("fim", "STEP12")]
check("reaches STEP12 → finished", analyze_session(fin)["outcome"] == "finished")
check("NET7_RESULTS terminal", analyze_session([U("a", "NET6_RUN", "NETWORK"), A("r", "NET7_RESULTS", "NETWORK")])["outcome"] == "finished")
enc = ab + [U("Encerrar", "STEP8"), A("Sessão encerrada", "IDLE", None)]
check("session ended with encerrar → finished", analyze_session(enc)["outcome"] == "finished")
check("sim_status paused → paused", analyze_session(ab, paused=True)["outcome"] == "paused")
check("paused via last message sim_status", analyze_session(ab[:-1] + [dict(ab[-1], sim_status="paused")])["outcome"] == "paused")
free = [U("o que é SIN?", "IDLE", None), A("resposta", "IDLE", None)]
fa = analyze_session(free)
check("free chat → no outcome, no steps", fa["outcome"] is None and fa["steps"] == [] and fa["stuck_steps"] == [])

# ── 7. help/back ─────────────────────────────────────────────────────────────
hb = [U("Ajuda", "STEP3"), A("x", "STEP3"), U("AJUDA", "STEP3"), A("x", "STEP3"),
      U("não sei", "STEP4"), A("x", "STEP4"), U("voltar", "STEP4"), A("x", "STEP3"),
      U("ajudar a entender", "STEP7"), A("x", "STEP7"), U("help!", "STEP7"), A("x", "STEP7")]
c = analyze_session(hb)["help_back_counts"]
check("Ajuda/AJUDA counted at STEP3", c.get("STEP3") == 2, c)
check("'não sei' + 'voltar' counted at STEP4", c.get("STEP4") == 2, c)
check("'ajudar a entender' not counted, 'help!' counted", c.get("STEP7") == 1, c)
check("help/back steps are stuck", {"STEP3", "STEP4", "STEP7"} <= set(analyze_session(hb)["stuck_steps"]))

# 👎 in stuck_steps
fb_down = [{"rating": "down", "sim_type": "BESS", "sim_step_before": "STEP2", "sim_step_after": "STEP3"}]
check("👎 feedback adds its step to stuck_steps", "STEP3" in analyze_session(ab, fb_down)["stuck_steps"])
check("👍 does not", "STEP3" not in analyze_session(ab, [dict(fb_down[0], rating="up")])["stuck_steps"])

# ── 8. feedback ↔ bubbles ───────────────────────────────────────────────────
print("\n═══ feedback matching & transcript ═══\n")
msgs = [U("oi", "STEP1", mid="u1"), A("pergunta A", "STEP2", mid="m1"),
        U("2028", "STEP2", mid="u2"), A("pergunta B", "STEP3", mid="m2"),
        A("pergunta B", "STEP3", mid="m3")]
fb_id = {"id": "f1", "message_id": "m2", "assistant_message": "pergunta B", "rating": "down"}
fb_old = {"id": "f2", "message_id": None, "session_id": "S", "assistant_message": "pergunta A", "rating": "up"}
fb_none = {"id": "f3", "message_id": "zzz", "assistant_message": "nada disso", "rating": "up"}
mt = match_feedback_to_messages(msgs, [fb_id, fb_old, fb_none])
check("matched by message_id (not by identical text on m3)", [f["id"] for f in mt[3]] == ["f1"] and mt[4] == [], mt)
check("old row without message_id falls back to assistant text", [f["id"] for f in mt[1]] == ["f2"], mt)
check("user bubbles / unmatched never get cards", mt[0] == [] and mt[2] == [] and all(f["id"] != "f3" for g in mt for f in g))
old_logs = [dict(m, message_id=None) for m in msgs[:4]]
mt2 = match_feedback_to_messages(old_logs, [fb_old, dict(fb_id, message_id="gone")])
check("both rows without ids → text fallback", [f["id"] for f in mt2[1]] == ["f2"] and [f["id"] for f in mt2[3]] == ["f1"], mt2)

seq = []
panel._bubble = lambda role, name, step, text: seq.append(("bubble", role, text))
panel._feedback_card = lambda fb, kp, fn: seq.append(("card", fb["id"]))
_log.clear()
panel._render_transcript({"id": "S", "full_name": "Fulano"}, msgs, [fb_id, fb_old], lambda *a: None)
bubbles = [s for s in seq if s[0] in ("bubble", "card")]
i_card = bubbles.index(("card", "f1"))
check("card f1 rendered directly under the 'pergunta B' bubble m2", bubbles[i_card - 1] == ("bubble", "assistant", "pergunta B") and i_card == 5, bubbles)
check("timeline strip rendered first", any("Linha do tempo" in t for k, t in _log if k == "markdown"))
check("every message has a bubble", sum(1 for s in bubbles if s[0] == "bubble") == len(msgs))

# ── 11. free-chat session renders ───────────────────────────────────────────
seq.clear(); _log.clear()
try:
    panel._render_transcript({"id": "F"}, free, [], lambda *a: None)
    ok = True
except Exception as e:  # noqa
    ok = False; err = e
check("free-chat session (no steps, no feedback) renders without errors", ok and len(seq) == 2)
check("free-chat summary row", summarize_session({"id": "F"}, free, [])["last_step"] == "-")
try:
    panel._render_transcript({"id": "E"}, [], [], lambda *a: None); ok = True
except Exception:
    ok = False
check("empty session renders", ok)

# ── 9. filters ──────────────────────────────────────────────────────────────
print("\n═══ filters / aggregation / export ═══\n")
sessions = {
    "free": ({"id": "free"}, free, []),
    "fbup": ({"id": "fbup"}, fin, [{"rating": "up", "sim_type": "BESS", "sim_step_after": "STEP8"}]),
    "fbdown": ({"id": "fbdown"}, fin, [{"rating": "down", "sim_type": "BESS", "sim_step_after": "STEP12"}]),
    "stuck": ({"id": "stuck"}, stuck7, []),
    "aband": ({"id": "aband"}, ab, []),
    "paused": ({"id": "paused", "is_paused": True}, ab, []),
}
summ = {k: summarize_session(*v) for k, v in sessions.items()}
allS = list(summ.values())
ids = lambda l: sorted(s["session_id"] for s in l)
check("'Só com feedback'", ids(filter_session_summaries(allS, only_feedback=True)) == ["fbdown", "fbup"])
check("'Só com 👎'", ids(filter_session_summaries(allS, only_down=True)) == ["fbdown"])
check("'Só com sinais de travamento'", ids(filter_session_summaries(allS, only_stuck=True)) == ["fbdown", "stuck"], ids(filter_session_summaries(allS, only_stuck=True)))
check("'Só abandonadas' (paused and finished excluded)", ids(filter_session_summaries(allS, only_abandoned=True)) == ["aband", "stuck"], ids(filter_session_summaries(allS, only_abandoned=True)))
check("filters combine (AND)", ids(filter_session_summaries(allS, only_feedback=True, only_stuck=True)) == ["fbdown"])
check("paused session outcome from is_paused", summ["paused"]["outcome"] == "paused")
check("badges", "⚠️ travou em STEP7" in summ["stuck"]["badges"] and "⛔ abandonada" in summ["stuck"]["badges"]
      and "🚩 👎" in summ["fbdown"]["badges"])

# ── 10. aggregation ─────────────────────────────────────────────────────────
helpme = [U("quero simular", "IDLE", None), A("base?", "STEP1"), U("ajuda", "STEP1"), A("x", "STEP1"),
          U("voltar", "STEP1"), A("x", "STEP1")]
agg_sessions = [summarize_session({"id": "h"}, helpme, []),     # STEP1: 2 help/back, abandoned
                summarize_session({"id": "s"}, stuck7, []),      # STEP7: not advancing + abandoned
                summarize_session({"id": "s2"}, stuck7, [])]
all_fb = [{"rating": "down", "sim_type": "BESS", "sim_step_after": "STEP7"},
          {"rating": "down", "sim_type": "BESS", "sim_step_after": "STEP7"},
          {"rating": "up", "sim_type": "BESS", "sim_step_after": "STEP7"}]
agg = {(r["sim_type"], r["sim_step"]): r for r in aggregate_by_step(agg_sessions, all_fb)}
r7, r1 = agg[("BESS", "STEP7")], agg[("BESS", "STEP1")]
check("STEP7: 2 👎, 2 sessions not advancing, 0 help, 2 abandoned",
      (r7["down"], r7["sessions_not_advancing"], r7["help_back"], r7["abandoned"]) == (2, 2, 0, 2), r7)
check("STEP1: 0 👎, 0 not advancing, 2 help/back, 1 abandoned",
      (r1["down"], r1["sessions_not_advancing"], r1["help_back"], r1["abandoned"]) == (0, 0, 2, 1), r1)
check("sorted: most problematic step first", aggregate_by_step(agg_sessions, all_fb)[0]["sim_step"] == "STEP7")

# ── 12. markdown export ─────────────────────────────────────────────────────
fbs = [{"rating": "down", "category": "passo", "comment": "confuso, contato fulano@x.com",
        "assistant_message": "Z" * 900, "sim_type": "BESS", "sim_step_after": "STEP7",
        "app_version": "v6.4.0", "status": "novo", "email": "tester@lab.com", "full_name": "Maria Silva"},
       {"rating": "down", "category": "formato", "comment": "PWF errado", "assistant_message": "dbar",
        "sim_type": "NETWORK", "sim_step_after": "NET5_GENERATE", "app_version": "v6.3.0",
        "status": "resolvido", "email": "tester@lab.com", "full_name": "Maria Silva"}]
stuck_named = [U("não entendi a barra maria@lab.com", "STEP7"), A("x", "STEP7"),
               U("sei lá", "STEP7"), A("x", "STEP7"), U("barra 5?", "STEP7"), A("x", "STEP7")]
rep_sessions = [dict(summarize_session({"id": "s", "email": "tester@lab.com", "full_name": "Maria Silva"},
                                       [U("quero simular", "IDLE", None), A("b", "STEP1")] + stuck_named, []))]
md = build_markdown_report(rep_sessions, fbs, filters={"Período": "2026-01-01 a 2026-02-01", "Tipo": "Todos"})
check("groups by sim_type then step", md.index("## BESS") < md.index("### STEP7") and md.index("## NETWORK") < md.index("### NET5_GENERATE"), md)
check("header has filters and counts", "Período: 2026-01-01" in md and "Itens de feedback: 2" in md)
check("assistant message truncated to ~600 chars", "Z" * 600 in md and "Z" * 601 not in md)
check("category label, status and comment present", "Passo confuso ou mal explicado" in md and "status: resolvido" in md and "PWF errado" in md)
check("version listed per step", "Versão(ões): v6.4.0" in md and "Versão(ões): v6.3.0" in md)
check("user-message excerpts included (≤3)", "barra 5?" in md and md.count('  - "') == 3, md.count('  - "'))
check("no emails / names anywhere", "@" not in md and "Maria" not in md and "Silva" not in md and "lab.com" not in md, [l for l in md.splitlines() if "@" in l or "Maria" in l])

failed = [n for n, ok in results if not ok]
print(f"\nResults: {len(results) - len(failed)} passed, {len(failed)} failed out of {len(results)} tests")
sys.exit(1 if failed else 0)
