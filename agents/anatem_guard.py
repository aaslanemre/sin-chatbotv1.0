"""
ANATEM guard for free (RAG/LLM) answers (v6.6.2, feedback items 9–15).

Pure module: no Streamlit and no DB imports. The free chat invented ANATEM card
syntax (fake DARQ/DCDU lines, a 'devt.ctg' file with CONT/TEMPO/ABRE,
'ABCI 1000 2000 1 0.1'). Rule: explain in words, never show card syntax.

  is_anatem_context(text, sim_type) → add RULE to the request's study_context
                                       (prompts/system_prompt.py is NOT edited:
                                       the rule travels in {study_context})
  filter_answer(text)               → (filtered text, number of removed items):
                                       fenced code blocks and card-record lines
  filter_stream(chunks)             → the same filter, line by line, while streaming

Applied to LLM answers only — never to deterministic flow messages, and fenced
blocks with ANAREDE cards (DBAR/DLIN/DCER/DCTG…) are always kept.
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# 1a: card / program names that make a question "ANATEM context".
CONTEXT_WORDS = ("anatem", "anat0", "stb", "devt", "darq", "dcdu", "acdu", "dmaq", "dplt", "dfnt",
                 "dcnv", "dcne", "ulog", "cdu", "plotcepel", "abci", "apcb", "apcc", "apcl", "rmgr",
                 "mdlp", "mdlq")
_CONTEXT_RE = re.compile(r"\b(?:" + "|".join(CONTEXT_WORDS) + r")\b")

MANUAL_URL = "https://see.cepel.br/manual/anatem/codigos_execucao/devt.html"

# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
RULE = (
    "REGRA ANATEM: explique em palavras. Não escreva blocos de código, linhas de cartões do ANATEM "
    "(DARQ, DCDU, DEVT, ABCI etc.) nem exemplos de sintaxe ou colunas, mesmo que o usuário peça. "
    "Você pode citar o NOME do cartão e descrever seus campos em uma frase ou tabela curta, com base "
    "no manual. Para a sintaxe exata, indique o manual do ANATEM (CEPEL): "
    f"{MANUAL_URL}"
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
# 4b: extra instruction for the "Outro / descrever o que quero analisar" event.
OTHER_EVENT_RULE = (
    "Sugira qual tipo de evento do DEVT aplicar e o NOME do cartão correspondente, com base no "
    "manual. Não escreva a sintaxe. Se não tiver certeza do cartão, diga isso e indique o manual."
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
FILTER_NOTE = ("ℹ️ Exemplos de sintaxe do ANATEM não são exibidos aqui; confira a sintaxe exata no "
               "manual do ANATEM (CEPEL).")

# Card names of 1a (upper case) + the record keywords of the invented 'devt.ctg'
# (CONT/TEMPO/ABRE) + DARQ file-type records (SAV/DAT). A line whose first token is
# one of these, followed by nothing or by digits / a file name / a path / another
# upper-case code, looks like a card record.
RECORD_TOKENS = frozenset(w.upper() for w in CONTEXT_WORDS
                          if w not in ("anatem", "anat0", "stb", "plotcepel", "cdu")) | {
    "CONT", "TEMPO", "ABRE", "SAV", "DAT"}
# Fenced blocks with ANAREDE execution codes are ANAREDE output: always kept.
ANAREDE_TOKENS = frozenset({"DBAR", "DLIN", "DCER", "DCTG", "DGER", "DBSH", "EXLF"})

_FENCE_RE = re.compile(r"^\s*(```|~~~)")
_LIST_PREFIX_RE = re.compile(r"^\s*(?:>\s*)?(?:[-*+]\s+|\d+[.)]\s+)?`?")
_ARG_RE = re.compile(r"""^(?:
      [-+]?\d[\d.,]*                     # digits
    | \S*[\\/]\S*                        # a path
    | [\w.-]+\.[A-Za-z0-9]{2,4}          # a file name
    | [A-Z][A-Z0-9_]{1,7}                # another upper-case code (DARQ SAV …)
)`?[,;]?$""", re.X)

# 1d: grep on the VM: "anatem_code_filter removed="
FILTER_HITS = {"answers": 0, "removed": 0}


def _norm(text) -> str:
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def is_anatem_context(text, sim_type=None) -> bool:
    """ANATEM flow (active or paused), or the question names ANATEM / one of its cards."""
    return sim_type == "ANATEM" or bool(_CONTEXT_RE.search(_norm(text)))


def is_record_line(line) -> bool:
    """'DARQ', 'ABCI 1000 2000 1 0.1', 'CONT 1 TEMPO 0.1' — not prose that names a card."""
    rest = _LIST_PREFIX_RE.sub("", line, count=1).rstrip().rstrip("`")
    toks = rest.split()
    if not toks or toks[0] not in RECORD_TOKENS:
        return False
    return len(toks) == 1 or bool(_ARG_RE.match(toks[1]))


def _is_anarede_block(lines) -> bool:
    return any((ln.split() or [""])[0] in ANAREDE_TOKENS for ln in lines)


class _LineFilter:
    """Line-by-line state machine shared by filter_answer and filter_stream."""

    def __init__(self):
        self.removed = 0
        self.block = None   # lines of the fenced block being read (fence included)

    def feed(self, line):
        """Lines to output for one input line (newline-terminated or not)."""
        if self.block is not None:
            self.block.append(line)
            if _FENCE_RE.match(line):
                return self._close()
            return []
        if _FENCE_RE.match(line):
            self.block = [line]
            return []
        if is_record_line(line.rstrip("\n")):
            self.removed += 1
            return []
        return [line]

    def _close(self):
        block, self.block = self.block, None
        if _is_anarede_block(block[1:-1]):
            return block
        self.removed += 1
        return []

    def finish(self):
        """An unclosed fence at the end: dropped (unless ANAREDE)."""
        if self.block is None:
            return []
        block, self.block = self.block, None
        if _is_anarede_block(block[1:]):
            return block
        self.removed += 1
        return []


def _tidy(text) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


def _count(removed):
    if removed:
        FILTER_HITS["answers"] += 1
        FILTER_HITS["removed"] += removed
        # WARNING: the app configures no logging, so INFO would never reach the VM journal
        logger.warning("anatem_code_filter removed=%d", removed)


def filter_answer(text):
    """(text without fenced blocks / card-record lines [+ FILTER_NOTE], removed count)."""
    f = _LineFilter()
    out = []
    for line in (text or "").splitlines(keepends=True):
        out += f.feed(line)
    out += f.finish()
    if not f.removed:
        return text, 0
    _count(f.removed)
    body = _tidy("".join(out))
    return (f"{body}\n\n{FILTER_NOTE}" if body else FILTER_NOTE), f.removed


def filter_stream(chunks):
    """Streaming version: yields only complete, kept lines (no counting — the final
    stored text goes through filter_answer)."""
    f, buf = _LineFilter(), ""
    for c in chunks:
        buf += c
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            for kept in f.feed(line + "\n"):
                yield kept
    if buf:
        yield from f.feed(buf)
    yield from f.finish()
