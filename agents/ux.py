"""
UX helpers for the user app (v6.5.0).

Pure module: no Streamlit and no DB imports, so everything here is unit-testable.
  - trailing "Deseja que eu te guie…" offer: deterministic strip + streaming filter
  - "Fontes consultadas" grouping by source file
  - .pwf download: code-block extraction, file names, CRLF bytes
  - deterministic step messages: main text / "Detalhes" split
"""

import os
import re
import unicodedata

# ── Trailing guide offer (LLM output driven by the system prompt, MODE 1) ─────

# The sentence the system prompt asks the LLM to append, with optional bold
# markers and small wording variations ("te"/"lhe"/"o"/"a", any ending up to "?").
GUIDE_RE = re.compile(
    r"[ \t]*(?:\*\*|__)?[ \t]*deseja que eu (?:te |lhe |o |a )?guie\b[^?\n]*\?(?:\*\*|__)?",
    re.IGNORECASE,
)
_GUIDE_START = "deseja que eu"

# Window: the offer may appear at most once every GUIDE_EVERY assistant messages.
GUIDE_EVERY = 5


def has_guide_offer(text) -> bool:
    return bool(GUIDE_RE.search(text or ""))


def strip_guide_offer(text: str) -> str:
    """Remove every occurrence of the guide offer and tidy the trailing whitespace."""
    out = GUIDE_RE.sub("", text or "")
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.rstrip()


def guide_offer_allowed(previous_assistant_texts, sim_in_progress: bool) -> bool:
    """
    False while a simulation is active or paused. Otherwise True only if none of
    the previous GUIDE_EVERY-1 assistant messages carried the offer, so it shows
    at most once in any GUIDE_EVERY consecutive assistant messages.
    """
    if sim_in_progress:
        return False
    recent = list(previous_assistant_texts or [])[-(GUIDE_EVERY - 1):]
    return not any(has_guide_offer(t) for t in recent)


def clean_llm_answer(raw: str, keep_guide: bool) -> str:
    """Deterministic post-processing of a free-conversation LLM answer."""
    return (raw or "").rstrip() if keep_guide else strip_guide_offer(raw)


def filter_guide_stream(chunks, keep_guide: bool):
    """
    Wrap an iterator of text chunks for live display. When the offer must be
    removed, text that could be the start of it is held back until the sentence
    is complete ('?' or newline), then dropped if it matches. The final message
    is always re-rendered from clean_llm_answer(), so this only avoids a flash.
    """
    if keep_guide:
        for c in chunks:
            if c:
                yield c
        return
    buf = ""
    for c in chunks:
        if not c:
            continue
        buf += c
        while True:
            low = buf.lower()
            i = low.find(_GUIDE_START)
            if i == -1:
                # hold back a possible partial prefix at the very end
                hold = 0
                for k in range(min(len(_GUIDE_START) - 1, len(low)), 0, -1):
                    if _GUIDE_START.startswith(low[-k:]):
                        hold = k
                        break
                emit, buf = buf[: len(buf) - hold], buf[len(buf) - hold:]
                if emit:
                    yield emit
                break
            # sentence start found: emit everything before it, wait for its end
            if i:
                yield buf[:i]
                buf = buf[i:]
                continue
            end = min([p for p in (buf.find("?"), buf.find("\n")) if p != -1], default=-1)
            if end == -1:
                break  # incomplete sentence: keep holding
            sentence, buf = buf[: end + 1], buf[end + 1:]
            if not has_guide_offer(sentence):
                yield sentence
            # loop again on the remainder
    if buf:
        yield strip_guide_offer(buf) if has_guide_offer(buf) else buf


# ── Sources ("Fontes consultadas") ────────────────────────────────────────────

EXCERPT_CHARS = 200


def _basename(src) -> str:
    src = str(src or "desconhecido")
    return os.path.basename(src) or src


def excerpt(text, limit=EXCERPT_CHARS) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def group_sources(retrieval_scores):
    """
    One entry per source file, best score first:
      {"file", "best", "count", "pages": [sorted ints/strs], "excerpts": [str]}
    Items are {'source', 'score'[, 'page', 'excerpt']}; extra keys are optional
    so messages stored before v6.5.0 still group correctly.
    """
    groups = {}
    for item in retrieval_scores or []:
        name = _basename(item.get("source"))
        g = groups.setdefault(name, {"file": name, "best": None, "count": 0,
                                     "pages": [], "excerpts": []})
        score = item.get("score")
        if score is not None and (g["best"] is None or float(score) > g["best"]):
            g["best"] = float(score)
        g["count"] += 1
        page = item.get("page")
        if page not in (None, "") and page not in g["pages"]:
            g["pages"].append(page)
        if item.get("excerpt"):
            g["excerpts"].append(excerpt(item["excerpt"]))
    out = list(groups.values())
    for g in out:
        try:
            g["pages"].sort(key=lambda p: (0, int(p)) if str(p).isdigit() else (1, str(p)))
        except Exception:
            pass
    out.sort(key=lambda g: (g["best"] is None, -(g["best"] or 0.0)))
    return out


def source_label(g) -> str:
    """'manual.pdf — 0.82 · 3 trechos · p. 4, 7'"""
    parts = [g["file"]]
    if g.get("best") is not None:
        parts[0] += f" — {g['best']:.2f}"
    parts.append(f"{g['count']} trecho{'s' if g['count'] != 1 else ''}")
    if g.get("pages"):
        parts.append("p. " + ", ".join(str(p) for p in g["pages"]))
    return " · ".join(parts)


# ── .pwf downloads ────────────────────────────────────────────────────────────

FENCE_RE = re.compile(r"```[^\n]*\n(.*?)\n```", re.S)

PWF_FILENAMES = {
    "BESS": "BESS_modificacao.pwf",
    "STATCOM": "STATCOM_modificacao.pwf",
    "DCTG": "DCTG_contingencias.pwf",
}


def slugify(text, default="minha_rede") -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).lower()
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    return t or default


def classify_pwf_block(block: str, sim_type=None):
    """'BESS' | 'STATCOM' | 'DCTG' | 'NETWORK' | None for a generated code block."""
    first = next((ln.strip() for ln in block.splitlines() if ln.strip()), "")
    head = first.split()[0].upper() if first else ""
    if head == "DCTG":
        return "DCTG"
    if head != "DBAR":
        return None
    if re.search(r"^\s*DCER\b", block, re.M):
        return "STATCOM"
    if sim_type == "NETWORK":
        return "NETWORK"
    return "BESS"


def pwf_filename(kind, network_title=None) -> str:
    if kind == "NETWORK":
        return slugify(network_title) + ".pwf"
    return PWF_FILENAMES[kind]


def pwf_bytes(block: str):
    """
    (bytes, encoding) for a download: the code-block text byte for byte, with
    CRLF line endings. ASCII when possible, latin-1 otherwise (ANAREDE's
    encoding); characters outside latin-1 become '?'.
    """
    text = block.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\r\n")
    try:
        return text.encode("ascii"), "ascii"
    except UnicodeEncodeError:
        return text.encode("latin-1", errors="replace"), "latin-1"


def split_pwf_segments(content: str, sim_type=None):
    """
    Split a deterministic message into ('text', s) and ('pwf', fenced, block, kind)
    segments. Only generated DBAR/DCTG blocks become 'pwf' segments; any other
    fenced block stays inside the surrounding text. Returns [] when there is
    nothing to download (caller renders the message in one piece).
    """
    segs, pos, found = [], 0, False
    for m in FENCE_RE.finditer(content or ""):
        kind = classify_pwf_block(m.group(1), sim_type)
        if kind is None:
            continue
        found = True
        if m.start() > pos:
            segs.append(("text", content[pos:m.start()]))
        segs.append(("pwf", m.group(0), m.group(1), kind))
        pos = m.end()
    if not found:
        return []
    if pos < len(content):
        segs.append(("text", content[pos:]))
    return segs


# ── Deterministic messages: main text + "Detalhes" ────────────────────────────

# Separator placed by the state machine between the visible part of a step
# message (including the step question) and its secondary explanation.
DETAILS_SEP = "\n\n\x1edetalhes\x1e\n\n"


def with_details(main: str, details: str) -> str:
    return f"{main}{DETAILS_SEP}{details}" if details else main


def split_details(text: str):
    """(main, details or None). Extra separators fold into the details part."""
    if not text or DETAILS_SEP not in text:
        return text, None
    main, *rest = text.split(DETAILS_SEP)
    details = "\n\n".join(r.strip() for r in rest if r.strip())
    return main.rstrip(), details or None


def plain_text(text: str) -> str:
    """Full text without the separator: what gets logged and snapshotted."""
    main, details = split_details(text)
    return f"{main}\n\n{details}" if details else main
