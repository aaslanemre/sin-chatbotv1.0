"""
Grounding confidence for free-conversation RAG answers (v6.4.1).

Pure module: no Streamlit and no DB imports. Thresholds apply to the top-1
cosine similarity returned by Qdrant.
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

DEFAULT_HIGH = 0.75
DEFAULT_LOW = 0.65

BADGE_LABELS = {
    "green": "🟢 Grounded",
    "yellow": "🟡 Parcialmente fundamentado",
    "red": "🔴 Sem base documental",
}

DISCLOSURE = (
    "Não encontrei essa informação específica nos documentos — "
    "respondendo com base em conhecimento geral de sistemas de "
    "potência:"
)


def validated_thresholds(high, low):
    """Return (high, low); fall back to 0.75/0.65 with a warning if misconfigured."""
    try:
        high, low = float(high), float(low)
        ok = 0.0 <= low <= high <= 1.0
    except (TypeError, ValueError):
        ok = False
    if not ok:
        logger.warning(
            "Invalid grounding thresholds (high=%r, low=%r): need 0 <= low <= high <= 1. "
            "Falling back to %.2f/%.2f.", high, low, DEFAULT_HIGH, DEFAULT_LOW)
        return DEFAULT_HIGH, DEFAULT_LOW
    return high, low


def top_score(scores):
    """Best score from a list of floats or {'score': float, ...} dicts; None if empty."""
    vals = []
    for s in scores or []:
        v = s.get("score") if isinstance(s, dict) else s
        if v is not None:
            vals.append(float(v))
    return max(vals) if vals else None


def classify_grounding(scores, high=DEFAULT_HIGH, low=DEFAULT_LOW) -> str:
    """green if top >= high, yellow if top >= low, else red (empty/None -> red)."""
    top = top_score(scores)
    if top is None:
        return "red"
    if top >= high:
        return "green"
    if top >= low:
        return "yellow"
    return "red"


# ── Meta replies (identity / scope refusal) ───────────────────────────────────
# MUST stay in sync with prompts/system_prompt.py (REGRAS 1-5 and the standard
# refusal in ESCOPO). Markers are matched on normalized text (lowercase, no accents).

def _norm(text) -> str:
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s/]", " ", t)).strip()


_MODELS = r"(gemini|chatgpt|gpt|claude|google|openai|anthropic|llama|meta)"
META_QUESTION_PATTERNS = [re.compile(p) for p in (
    r"\bquem (sao|e|foram) (os |as )?(seus |suas )?(criadores?|desenvolvedores?)",
    r"\bquem (te|lhe|voce) (criou|desenvolveu|fez|programou|treinou)\b",
    r"\bquem (criou|desenvolveu|fez|programou|treinou) (voce|o assistente)\b",
    r"\bque empresa (fez|criou|desenvolveu) voce\b",
    r"\bvoce (e|usa|foi treinad[oa]|roda)\b.*\b" + _MODELS + r"\b",
    r"\b(que|qual) (modelo|llm|api)\b.*\b(voce|usa|utiliza)\b",
    r"\bqual (e )?(o )?seu (modelo|llm)\b",
    r"\b(mostre|revele|exiba|qual|me d[eê]).{0,30}(system prompt|prompt do sistema|instrucoes internas)",
    r"\bsystem prompt\b",
)]

META_ANSWER_MARKERS = (
    # Identity answers (REGRAS 1-4)
    "desenvolvido pelo gesel/ufrj",
    "nao divulgo detalhes da arquitetura interna",
    "nao tenho informacoes a divulgar sobre minha arquitetura interna",
    # REGRA 5
    "nao posso compartilhar informacoes sobre a implementacao interna do sistema",
    # Standard scope refusal
    "sou especializado no sistema interligado nacional e em estudos com anarede/anatem",
    "nao consigo ajudar com esse tipo de solicitacao",
)


def is_meta_reply(question, answer) -> bool:
    """True for identity/system-prompt questions and for the standard scope refusal."""
    q, a = _norm(question), _norm(answer)
    if any(p.search(q) for p in META_QUESTION_PATTERNS):
        return True
    return any(m in a for m in META_ANSWER_MARKERS)


# ── Cosine-distance guard ─────────────────────────────────────────────────────
_cosine_cache: dict = {}


def collection_is_cosine(get_distance, key="default") -> bool:
    """
    Cached check that the Qdrant collection uses Cosine distance (the thresholds
    assume cosine similarity). `get_distance` is a zero-arg callable returning the
    collection's distance (enum or string). Definitive answers are cached; a lookup
    error disables grounding for this call only (retried next time).
    """
    if key in _cosine_cache:
        return _cosine_cache[key]
    try:
        dist = get_distance()
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read Qdrant collection distance (%s); grounding disabled.", e)
        return False
    name = str(getattr(dist, "value", dist)).lower()
    ok = name == "cosine"
    if not ok:
        logger.warning("Qdrant collection distance is %r, not Cosine; grounding disabled.", name)
    _cosine_cache[key] = ok
    return ok


def reset_cosine_cache():
    _cosine_cache.clear()
