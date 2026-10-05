"""
Pure session analysis for the admin panel (v6.4.0).

No Streamlit and no DB imports: everything here takes plain dicts/lists so it can
be unit-tested in isolation. "Stuck" is detected ONLY from step changes, user
message counts and tester feedback — never from the bot's wording.

Message dicts (chat_logs rows or in-memory messages) use these keys:
    role ('user' | 'assistant'), message (or content), sim_step, sim_type,
    message_id, session_id.
A user row carries the step active when the message ARRIVED; an assistant row
carries the step active AFTER the reply was produced.
"""

import re
import unicodedata

NOT_ADVANCING_THRESHOLD = 3

TERMINAL_STEPS = {"STEP12", "NET7_RESULTS"}

# Steps where a user legitimately sends many messages without the step changing
# (bus-by-bus / line-by-line data entry), so the "N turns without advancing"
# rule would flag every healthy network session.
MULTI_TURN_STEPS = ("NET2_BUSES", "NET3_LINES")

HELP_BACK_PHRASES = {"ajuda", "help", "nao sei", "voltar"}
END_TOKENS = {"encerrar", "encerra", "finalizar", "finaliza", "terminar", "fim", "sair"}

FEEDBACK_CATEGORIES = {
    "tecnico": "Informação técnica errada",
    "passo": "Passo confuso ou mal explicado",
    "faltou": "Faltou algo / fluxo não cobre meu caso",
    "formato": "Formato PWF/ANAREDE incorreto",
    "outro": "Outro",
}

FEEDBACK_STATUSES = ["novo", "em_analise", "resolvido", "descartado"]

OUTCOME_LABELS = {
    "finished": "✅ finalizada",
    "paused": "⏸️ pausada",
    "abandoned": "⛔ abandonada",
}

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize(text) -> str:
    """Lowercase, accent-insensitive, punctuation stripped, whitespace collapsed."""
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _text(m: dict) -> str:
    return m.get("message") if m.get("message") is not None else (m.get("content") or "")


def _is_idle(step) -> bool:
    return not step or step == "IDLE"


def infer_sim_type(step, carried=None, default=None):
    if step and step.startswith("NET"):
        return "NETWORK"
    if step and step.startswith("STATCOM"):
        return "STATCOM"
    if step and step.startswith("IDLE_LT"):
        return "LT"
    return carried or default or "N/D"


def _annotate(messages, default_sim_type=None):
    """Normalise rows: (role, text, step, sim_type) with sim_type carried forward."""
    out, carried = [], None
    for m in messages:
        step = m.get("sim_step")
        stype = m.get("sim_type") or infer_sim_type(step, carried, default_sim_type)
        if m.get("sim_type"):
            carried = m["sim_type"]
        out.append({
            "role": m.get("role"),
            "text": _text(m),
            "step": None if _is_idle(step) else step,
            "sim_type": stype,
            "msg": m,
        })
    return out


def _turn_advanced(rows, i) -> bool:
    """Did the user turn at rows[i] move the flow? Compare with the step after the reply."""
    if i + 1 >= len(rows):
        return False
    return rows[i + 1]["step"] != rows[i]["step"]


def is_help_or_back(text) -> bool:
    return normalize(text) in HELP_BACK_PHRASES


def is_end_message(text) -> bool:
    return bool(END_TOKENS & set(normalize(text).split()))


def clean_excerpt(text, limit=140) -> str:
    t = _EMAIL_RE.sub("[email]", re.sub(r"\s+", " ", str(text or "")).strip())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def _feedback_key(fb):
    """(sim_type, step) a feedback item is attributed to (the step shown on the bubble)."""
    step = fb.get("sim_step_after") or fb.get("sim_step_before")
    if _is_idle(step):
        return None
    return (fb.get("sim_type") or infer_sim_type(step), step)


# ── Core analysis ─────────────────────────────────────────────────────────────

def analyze_session(messages, feedback=None, *, threshold=NOT_ADVANCING_THRESHOLD,
                    paused=None, default_sim_type=None,
                    exempt_steps=MULTI_TURN_STEPS) -> dict:
    """
    Returns:
      steps            [(sim_type, sim_step, turn_count)] consecutive repeats collapsed
      not_advancing    steps with >= `threshold` consecutive user turns at the same step
      help_back_counts {step: n} for "ajuda"/"help"/"não sei"/"voltar" messages
      outcome          'finished' | 'paused' | 'abandoned' | None (no simulation steps)
      stuck_steps      union of not_advancing, help/back and 👎 steps (ordered)
      last_step        (sim_type, sim_step) of the last simulation step, or None
      by_key           {(sim_type, step): {not_advancing, help_back, down, abandoned, excerpts}}
    `paused`: True if the session's sim_status was paused at the end (falls back to
    a `sim_status` key on the last message).
    """
    rows = _annotate(messages or [], default_sim_type)

    # Timeline: consecutive repeats collapsed; an IDLE row breaks the collapse.
    steps, prev = [], None
    for r in rows:
        if r["step"] is None:
            prev = None
            continue
        key = (r["sim_type"], r["step"])
        if key != prev:
            steps.append([r["sim_type"], r["step"], 0])
            prev = key
        if r["role"] == "user":
            steps[-1][2] += 1

    by_key = {}

    def slot(key):
        return by_key.setdefault(key, {"not_advancing": False, "help_back": 0, "down": 0,
                                       "abandoned": False, "excerpts": []})

    # Consecutive user turns at the same step.
    run_key, run_turns = None, []
    help_back_counts = {}
    flagged = []

    def close_run():
        nonlocal run_key, run_turns
        if run_key and run_key[1] not in exempt_steps and len(run_turns) >= threshold:
            s = slot(run_key)
            s["not_advancing"] = True
            if run_key[1] not in flagged:
                flagged.append(run_key[1])
            for t in run_turns:
                if not t["advanced"]:
                    s["excerpts"].append(t["text"])
        run_key, run_turns = None, []

    for i, r in enumerate(rows):
        if r["role"] != "user":
            continue
        if r["step"] is None:
            close_run()
            continue
        key = (r["sim_type"], r["step"])
        if key != run_key:
            close_run()
            run_key = key
        run_turns.append({"text": r["text"], "advanced": _turn_advanced(rows, i)})
        if is_help_or_back(r["text"]):
            help_back_counts[r["step"]] = help_back_counts.get(r["step"], 0) + 1
            s = slot(key)
            s["help_back"] += 1
            s["excerpts"].append(r["text"])
    close_run()

    # 👎 feedback
    down_steps = []
    for fb in feedback or []:
        if fb.get("rating") != "down":
            continue
        k = _feedback_key(fb)
        if k:
            slot(k)["down"] += 1
            if k[1] not in down_steps:
                down_steps.append(k[1])

    # Outcome
    last_step = (steps[-1][0], steps[-1][1]) if steps else None
    if paused is None and messages:
        paused = (messages[-1].get("sim_status") == "paused")
    outcome = None
    if steps:
        last_user = next((r for r in reversed(rows) if r["role"] == "user"), None)
        ended_idle = rows[-1]["step"] is None
        if paused:
            outcome = "paused"
        elif (steps[-1][1] in TERMINAL_STEPS
              or (last_user is not None and is_end_message(last_user["text"]) and ended_idle)):
            outcome = "finished"
        else:
            outcome = "abandoned"
        if outcome == "abandoned":
            slot(last_step)["abandoned"] = True
            # The last user message at that step is evidence of where they gave up.
            for r in reversed(rows):
                if r["role"] == "user" and (r["sim_type"], r["step"]) == last_step:
                    by_key[last_step]["excerpts"].append(r["text"])
                    break

    stuck = []
    for s in flagged + list(help_back_counts) + down_steps:
        if s not in stuck:
            stuck.append(s)

    return {
        "steps": [tuple(s) for s in steps],
        "not_advancing": flagged,
        "help_back_counts": help_back_counts,
        "outcome": outcome,
        "stuck_steps": stuck,
        "last_step": last_step,
        "by_key": by_key,
    }


# ── Presentation helpers (still pure) ────────────────────────────────────────

def timeline_text(analysis, threshold=NOT_ADVANCING_THRESHOLD) -> str:
    """e.g. 'STEP1 → STEP3 → STEP7 ×4 ⚠️ → ⛔ abandonada'"""
    parts = []
    for _stype, step, turns in analysis["steps"]:
        label = step
        if turns > 1:
            label += f" ×{turns}"
        if step in analysis["not_advancing"]:
            label += " ⚠️"
        parts.append(label)
    marker = OUTCOME_LABELS.get(analysis.get("outcome"))
    if marker:
        parts.append(marker)
    return " → ".join(parts) if parts else "—"


def stuck_badges(analysis, thumbs_down_count=0) -> list:
    badges = [f"⚠️ travou em {s}" for s in analysis["not_advancing"]]
    if analysis["help_back_counts"]:
        badges.append("🆘 pediu ajuda")
    if analysis["outcome"] == "abandoned":
        badges.append("⛔ abandonada")
    if thumbs_down_count:
        badges.append("🚩 👎")
    return badges


def summarize_session(session, messages, feedback=None, paused=None) -> dict:
    """One row per session for the admin list / CSV."""
    feedback = feedback or []
    a = analyze_session(
        messages, feedback,
        paused=paused if paused is not None else session.get("is_paused"),
        default_sim_type=session.get("sim_type"),
    )
    down = sum(1 for f in feedback if f.get("rating") == "down")
    last = f"{a['last_step'][0]} {a['last_step'][1]}" if a["last_step"] else "-"
    return {
        "session_id": session.get("id"),
        "feedback_count": len(feedback),
        "thumbs_down_count": down,
        "last_step": last,
        "outcome": a["outcome"],
        "stuck_steps": a["stuck_steps"],
        "badges": stuck_badges(a, down),
        "analysis": a,
    }


def filter_session_summaries(summaries, only_feedback=False, only_down=False,
                             only_stuck=False, only_abandoned=False) -> list:
    out = []
    for s in summaries:
        if only_feedback and not s["feedback_count"]:
            continue
        if only_down and not s["thumbs_down_count"]:
            continue
        if only_stuck and not s["stuck_steps"]:
            continue
        if only_abandoned and s["outcome"] != "abandoned":
            continue
        out.append(s)
    return out


def match_feedback_to_messages(messages, feedback) -> list:
    """
    For each message (same order) return the list of feedback items attached to it.
    Primary key: message_id. Fallback for old rows lacking ids: same session and
    identical assistant text (first assistant bubble with that text wins).
    """
    result = [[] for _ in messages]
    by_id = {}
    for i, m in enumerate(messages):
        if m.get("role") == "assistant" and m.get("message_id"):
            by_id.setdefault(m["message_id"], i)
    unmatched = []
    for fb in feedback or []:
        i = by_id.get(fb.get("message_id")) if fb.get("message_id") else None
        if i is not None:
            result[i].append(fb)
        else:
            unmatched.append(fb)
    for fb in unmatched:
        target = (fb.get("assistant_message") or "").strip()
        if not target:
            continue
        for i, m in enumerate(messages):
            if m.get("role") != "assistant":
                continue
            if m.get("message_id") and fb.get("message_id"):
                continue  # both have ids and they differ: not the same message
            sid_ok = (not fb.get("session_id") or not m.get("session_id")
                      or str(fb["session_id"]) == str(m["session_id"]))
            if sid_ok and _text(m).strip() == target:
                result[i].append(fb)
                break
    return result


# ── Cross-session aggregation ────────────────────────────────────────────────

def aggregate_by_step(summaries, feedback=None) -> list:
    """
    One row per (sim_type, sim_step): 👎 count, sessions that did not advance,
    help/back uses, abandonments, sorted most problematic first.
    """
    agg = {}

    def row(key):
        return agg.setdefault(key, {"sim_type": key[0], "sim_step": key[1], "down": 0,
                                    "sessions_not_advancing": 0, "help_back": 0,
                                    "abandoned": 0})

    for s in summaries:
        for key, d in s["analysis"]["by_key"].items():
            r = row(key)
            if d["not_advancing"]:
                r["sessions_not_advancing"] += 1
            r["help_back"] += d["help_back"]
            if d["abandoned"]:
                r["abandoned"] += 1
    for fb in feedback or []:
        if fb.get("rating") == "down":
            k = _feedback_key(fb)
            if k:
                row(k)["down"] += 1
    rows = list(agg.values())
    for r in rows:
        r["score"] = r["down"] + r["sessions_not_advancing"] + r["help_back"] + r["abandoned"]
    rows = [r for r in rows if r["score"] > 0]
    rows.sort(key=lambda r: (-r["score"], -r["down"], r["sim_type"], r["sim_step"]))
    return rows


LEVEL_ICONS = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def grounding_caption(level, score=None) -> str:
    """'🟢 0.78' for admin bubbles; '' for old rows without grounding data."""
    icon = LEVEL_ICONS.get(level)
    if not icon:
        return ""
    return f"{icon} {float(score):.2f}" if score is not None else icon


def grounding_vs_rating(feedback) -> list:
    """Per grounding level: 👍/👎 counts and average score per rating (threshold tuning)."""
    out = []
    for level in ("green", "yellow", "red"):
        items = [f for f in feedback or [] if f.get("grounding_level") == level]
        if not items:
            continue
        def avg(rating):
            v = [float(f["grounding_score"]) for f in items
                 if f.get("rating") == rating and f.get("grounding_score") is not None]
            return round(sum(v) / len(v), 3) if v else None
        out.append({"level": level, "up": sum(1 for f in items if f.get("rating") == "up"),
                    "down": sum(1 for f in items if f.get("rating") == "down"),
                    "avg_up": avg("up"), "avg_down": avg("down")})
    return out


def _step_sort_key(step):
    m = re.match(r"([A-Z_]*?)(\d+)([A-Z]*)$", step or "")
    return (m.group(1), int(m.group(2)), m.group(3)) if m else (step or "", 0, "")


def build_markdown_report(summaries, feedback, filters=None, max_excerpts=3,
                          assistant_limit=600) -> str:
    """
    Markdown grouped by sim_type → sim_step, meant to be pasted into a Claude Code
    prompt. Contains no user names or emails (emails typed in messages are masked).
    """
    feedback = feedback or []
    filters = filters or {}
    groups = {}

    def g(key):
        return groups.setdefault(key, {"versions": set(), "stuck": 0, "abandoned": 0,
                                       "feedback": [], "excerpts": []})

    for s in summaries:
        for key, d in s["analysis"]["by_key"].items():
            gg = g(key)
            if d["not_advancing"] or d["help_back"] or d["down"]:
                gg["stuck"] += 1
            if d["abandoned"]:
                gg["abandoned"] += 1
            for ex in d["excerpts"]:
                c = clean_excerpt(ex)
                if c and c not in gg["excerpts"]:
                    gg["excerpts"].append(c)
    for fb in feedback:
        k = _feedback_key(fb) or ("Livre", "(sem passo)")
        gg = g(k)
        gg["feedback"].append(fb)
        if fb.get("app_version"):
            gg["versions"].add(fb["app_version"])

    n_down = sum(1 for f in feedback if f.get("rating") == "down")
    n_up = sum(1 for f in feedback if f.get("rating") == "up")
    lines = ["# Relatório de feedback e travamentos por passo", "", "## Filtros"]
    if filters:
        lines += [f"- {k}: {v}" for k, v in filters.items()]
    else:
        lines.append("- (nenhum)")
    lines += ["", "## Contagens",
              f"- Sessões analisadas: {len(summaries)}",
              f"- Itens de feedback: {len(feedback)} (👎 {n_down}, 👍 {n_up})",
              f"- Sessões abandonadas: {sum(1 for s in summaries if s['outcome'] == 'abandoned')}",
              ""]

    by_type = {}
    for (stype, step), gg in groups.items():
        if gg["stuck"] or gg["abandoned"] or gg["feedback"]:
            by_type.setdefault(stype, {})[step] = gg

    if not by_type:
        lines.append("_Nenhum travamento ou feedback no período._")
    for stype in sorted(by_type):
        lines += [f"## {stype}", ""]
        for step in sorted(by_type[stype], key=_step_sort_key):
            gg = by_type[stype][step]
            vers = ", ".join(sorted(gg["versions"])) or "n/d"
            lines += [f"### {step}",
                      f"- Versão(ões): {vers}",
                      f"- Sessões travadas neste passo: {gg['stuck']}",
                      f"- Abandonos: {gg['abandoned']}"]
            if gg["feedback"]:
                lines.append("- Feedback:")
                for fb in gg["feedback"]:
                    cat = FEEDBACK_CATEGORIES.get(fb.get("category"), "sem categoria")
                    icon = "👎" if fb.get("rating") == "down" else "👍"
                    amsg = re.sub(r"\s+", " ", fb.get("assistant_message") or "").strip()
                    if len(amsg) > assistant_limit:
                        amsg = amsg[:assistant_limit].rstrip() + "…"
                    gcap = grounding_caption(fb.get("grounding_level"), fb.get("grounding_score"))
                    lines += [
                        f"  - {icon} [{cat}] status: {fb.get('status') or 'novo'}"
                        + (f" · grounding: {gcap}" if gcap else ""),
                        f"    - Comentário do tester: {clean_excerpt(fb.get('comment'), 500) or '(sem comentário)'}",
                        f"    - Mensagem do assistente: {_EMAIL_RE.sub('[email]', amsg)}",
                    ]
            if gg["excerpts"]:
                lines.append("- Trechos de mensagens de usuários que não avançaram:")
                lines += [f"  - \"{ex}\"" for ex in gg["excerpts"][:max_excerpts]]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
