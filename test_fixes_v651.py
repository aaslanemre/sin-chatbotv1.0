"""
v6.5.1 COMMIT 1 — DLIN/DBAR/DCER/DCTG numeric fields (max 4 decimals, fit to
width, no exponent), non-zero coupling reactance, 'modelar' intent, coupling-line
wording.

Run from repo root:  python3 test_fixes_v651.py
"""
import ast
import glob
import re

import _harness_v650 as H
from _harness_v650 import ss, check, section, fresh, run, last_assistant, StreamChain, scores
from agents import ux
from agents import structured_input as SI
from agents.pwf_agent import generate_dbar_block, generate_statcom_block, generate_contingency_block
from agents.network_builder import convert_line_params, build_full_pwf, validate_network, format_network_summary
from utils.anarede_lib import (format_ansi_field, field_text, rounds_to_zero, COUPLING_LINE_X_PCT,
                               DLIN_R_WIDTH, DLIN_X_WIDTH, DLIN_S_WIDTH)

NUM_RE = re.compile(r"^-?\d+(\.\d*)?$")


def decimals(s):
    s = s.strip()
    return len(s.split(".")[1]) if "." in s else 0


def field_ok(s, width, value=None):
    """(ok, why) for one written field."""
    if len(s) != width:
        return False, f"width {len(s)} != {width}: {s!r}"
    t = s.strip()
    if t == "":
        return True, ""
    if "e" in t.lower():
        return False, f"exponent: {s!r}"
    if not NUM_RE.match(t):
        return False, f"not a plain number: {s!r}"
    if decimals(t) > 4:
        return False, f"more than 4 decimals: {s!r}"
    if value is not None:
        tol = 0.5 * 10 ** -decimals(t) + 1e-12
        if abs(float(t) - float(value)) > tol:
            return False, f"round-trip {t} vs {value}"
    return True, ""


# ── Column layouts (0-based [start, end)) ────────────────────────────────────
# DBAR: derived from the ruler printed by Script_Inclui_DBAR.
DBAR_RULER = "(Num)OETGb(   nome   )Gl( V)( A)( Pg)( Qg)( Qn)( Qm)(Bc  )( Pl)( Ql)( Sh)Are(Vf)"


def ruler_spans(ruler):
    spans, i = {}, 0
    for tok in re.findall(r"\([^)]*\)|Are|Gb|Gl|[A-Z]", ruler):
        name = tok.strip("() ") or tok
        spans[name] = (i, i + len(tok))
        i += len(tok)
    return spans


DBAR = ruler_spans(DBAR_RULER)
DBAR_NUMERIC = ["Pg", "Qg", "Qn", "Qm", "Bc", "Pl", "Ql", "Sh"]

# DLIN line (LT) as written by Script_adiciona_LT — no ruler exists for DLIN in the
# repo (OPEN QUESTION in the report); these spans follow the library widths.
_r0 = 20
DLIN = {"De": (0, 5), "Para": (10, 15), "Circ": (15, 17),
        "R": (_r0, _r0 + DLIN_R_WIDTH),
        "X": (_r0 + DLIN_R_WIDTH + 1, _r0 + DLIN_R_WIDTH + 1 + DLIN_X_WIDTH),
        "S": (_r0 + DLIN_R_WIDTH + DLIN_X_WIDTH + 2, _r0 + DLIN_R_WIDTH + DLIN_X_WIDTH + 2 + DLIN_S_WIDTH)}
DLIN_LINE_LEN = 82


def block_lines(block, code):
    lines = block.splitlines()
    i = lines.index(code)
    out = []
    for ln in lines[i + 1:]:
        if ln == "99999":
            break
        if ln.startswith("("):  # ruler
            continue
        out.append(ln)
    return out


def sl(line, span):
    return line[span[0]:span[1]]


# ═════════════════════════════════════════════════════════════════════════════
section("1A. format_ansi_field — edge values")
# ═════════════════════════════════════════════════════════════════════════════
EDGE = [0.0001, 0.3781, 0.378072, 18.515, 51.93, 123.456, 1e-7, 0, 0.0]
for width in (4, 5, 6, 8, 10):
    for v in EDGE:
        try:
            s = format_ansi_field(v, width)
        except ValueError as e:
            check(f"w={width} v={v}: fits", False, e)
            continue
        ok, why = field_ok(s, width, v)
        check(f"w={width} v={v!r} → {s!r}", ok and ("." in s or isinstance(v, int)), why)

check("0.378072 (tester's 6-decimal value) → 0.3781 in a 6-col field", format_ansi_field(0.378072, 6) == "0.3781")
check("0.000010 (old coupling X) → 0.0000 in an 8-col field, never 6 decimals",
      format_ansi_field(0.00001, 8) == "  0.0000")
check("1e-7 → 0.0000, never scientific notation", format_ansi_field(1e-7, 6) == "0.0000")
check("-1e-7 → 0.0000 (no '-0.0000')", format_ansi_field(-1e-7, 6) == "0.0000")
check("123.456 rounds to fit 6 cols → 123.46", format_ansi_field(123.456, 6) == "123.46")
check("18.515 in 5 cols → 18.52 or 18.51 (rounded, 5 chars)", format_ansi_field(18.515, 5).strip() in ("18.52", "18.51"))
check("rounding carry: 9.99996 in 6 cols → 10.000", format_ansi_field(9.99996, 6) == "10.000")
check("integers stay integers: 417 → '  417', '-276' → ' -276'",
      format_ansi_field(417, 5) == "  417" and format_ansi_field("-276", 5) == " -276")
check("float with no room for decimals keeps the point: 1234.6 in 5 → '1235.'", format_ansi_field(1234.6, 5) == "1235.")
check("max_decimals is capped at 4", decimals(format_ansi_field(0.123456, 10, max_decimals=6)) == 4)
check("blank → spaces", format_ansi_field("", 6) == " " * 6 and format_ansi_field(None, 4) == " " * 4)
for bad, w in ((123456.7, 6), (123456, 5), ("abc", 6), (float("nan"), 6)):
    try:
        format_ansi_field(bad, w)
        check(f"{bad!r} in {w} cols raises ValueError (never overflows)", False)
    except ValueError:
        check(f"{bad!r} in {w} cols raises ValueError (never overflows)", True)
check("rounds_to_zero(1e-7) True, (0) False, (0.0001) False",
      rounds_to_zero(1e-7, 6) and not rounds_to_zero(0, 6) and not rounds_to_zero(0.0001, 8))

# ═════════════════════════════════════════════════════════════════════════════
section("1A. BESS acceptance case (bus 1001, new 91000, 500 MVA, P 417 MW, PV)")
# ═════════════════════════════════════════════════════════════════════════════
blk = generate_dbar_block(bus_number=1001, bess_bus_number=91000, bus_type="1", S_mva=500, P_mw=417)
dbar, dlin = block_lines(blk, "DBAR"), block_lines(blk, "DLIN")
norm = lambda s: " ".join(s.split())
check("DLIN line == '1001 A 91000 1L 0.0000 0.0001 0.0000'", norm(dlin[0]) == "1001 A 91000 1L 0.0000 0.0001 0.0000",
      dlin)
check("old value 0.000010 is gone", "0.000010" not in blk and "0.00001" not in blk)
check("DBAR line unchanged (91000AL1 BESS 417 -276 276), byte for byte",
      dbar[0] == "91000AL1          BESS            417      -276  276                            ", repr(dbar[0]))
check("DLIN line length unchanged (82)", len(dlin[0]) == DLIN_LINE_LEN, len(dlin[0]))
check("coupling X field (cols 28-35) is exactly the constant",
      float(sl(dlin[0], DLIN["X"])) == COUPLING_LINE_X_PCT and sl(dlin[0], DLIN["X"]).strip() == "0.0001")
check("R and S of the coupling line stay 0", float(sl(dlin[0], DLIN["R"])) == 0 and float(sl(dlin[0], DLIN["S"])) == 0)
check("no tap (cols after S blank)", dlin[0][DLIN["S"][1]:].strip() == "")
check("COUPLING_LINE_X_PCT == 0.0001 and is non-zero when written",
      COUPLING_LINE_X_PCT == 0.0001 and not rounds_to_zero(COUPLING_LINE_X_PCT, DLIN_X_WIDTH))

for args in [(1001, 9999, "0", 100, 80), (5, 91000, "1", 0.5, 0.2), (99999, 10000, "1", 1000, 999.6)]:
    b = generate_dbar_block(*args)
    ln = block_lines(b, "DLIN")[0]
    check(f"coupling line never zero {args}", float(sl(ln, DLIN["X"])) > 0)

# ═════════════════════════════════════════════════════════════════════════════
section("1A. every numeric field fits and has ≤ 4 decimals (BESS, STATCOM, NETWORK)")
# ═════════════════════════════════════════════════════════════════════════════


def check_dbar(block, tag):
    for ln in block_lines(block, "DBAR"):
        for f in DBAR_NUMERIC:
            ok, why = field_ok(sl(ln, DBAR[f]).rjust(DBAR[f][1] - DBAR[f][0]), DBAR[f][1] - DBAR[f][0])
            if not ok:
                check(f"{tag} DBAR {f}", False, why)
                return
    check(f"{tag}: DBAR numeric fields aligned to the ruler columns, ≤ 4 decimals", True)


def check_dlin(block, tag, expect=None):
    for i, ln in enumerate(block_lines(block, "DLIN")):
        for f in ("R", "X", "S"):
            w = DLIN[f][1] - DLIN[f][0]
            ok, why = field_ok(sl(ln, DLIN[f]), w, None if expect is None else expect[i][f])
            if not ok:
                check(f"{tag} DLIN {f}", False, why)
                return
    check(f"{tag}: DLIN R/X/S fit their widths ({DLIN_R_WIDTH}/{DLIN_X_WIDTH}/{DLIN_S_WIDTH}), ≤ 4 decimals,"
          " round-trip", True)


check_dbar(blk, "BESS")
check_dlin(blk, "BESS", [{"R": 0, "X": COUPLING_LINE_X_PCT, "S": 0}])

st_blk = generate_statcom_block(1001, -100, 100)
check_dbar(st_blk, "STATCOM")
dcer = block_lines(st_blk, "DCER")[0]
for name, span in (("inclinação", (20, 26)), ("Qg", (27, 32)), ("Qmin", (32, 37)), ("Qmax", (37, 42))):
    ok, why = field_ok(dcer[span[0]:span[1]], span[1] - span[0])
    check(f"STATCOM DCER {name} fits, ≤ 4 decimals", ok, why)
check("STATCOM block unchanged", st_blk.splitlines()[2] == " 1001AL1       STATCOM              0      -100  100  1001                      "
      and dcer == " 1001 A  1  1  1001 0.0000     0 -100  100 I L L", (st_blk.splitlines()[2], dcer))

conv = convert_line_params(230, "per_km", {"R": 0.0257, "X": 0.2995, "B": 5.4542}, 180)
net = {"title": "T", "base_mva": 100.0,
       "buses": [{"number": 1, "name": "A", "kv": 230, "tipo": 2, "v_pu": 1.02},
                 {"number": 2, "name": "B", "kv": 230, "tipo": 0, "p_load_mw": 100, "q_load_mvar": 50}],
       "lines": [{"id": 1, "from_bus": 1, "to_bus": 2, "circuit": 1,
                  "r_pct": conv["r_pct"], "x_pct": conv["x_pct"], "q_mvar": conv["q_mvar"]}]}
pwf = build_full_pwf(net)
check_dbar(pwf, "NETWORK")
check_dlin(pwf, "NETWORK", [{"R": conv["r_pct"], "X": conv["x_pct"], "S": conv["q_mvar"]}])
nl = block_lines(pwf, "DLIN")[0]
check("NETWORK X 10.190926… is written 10.1909 (was 10.19093)", sl(nl, DLIN["X"]).strip() == "10.1909", nl)

edge_net = dict(net, lines=[{"id": i + 1, "from_bus": 1, "to_bus": 2, "circuit": i + 1,
                             "r_pct": v, "x_pct": max(v, 0.01), "q_mvar": v}
                            for i, v in enumerate([0.0001, 0.3781, 0.378072, 18.515, 51.93, 123.456, 1e-7, 0])])
epwf = build_full_pwf(edge_net)
check_dlin(epwf, "NETWORK edge table",
           [{"R": l["r_pct"], "X": l["x_pct"], "S": l["q_mvar"]} for l in edge_net["lines"]])
check("no exponent anywhere in generated blocks",
      not any(re.search(r"\d[eE][-+]?\d", b) for b in (blk, st_blk, pwf, epwf)))
check("DCTG numbers formatted to their widths",
      generate_contingency_block([{"id": 1, "name": "LT", "type": "line", "bus_from": 1001, "bus_to": 1002}])
      .splitlines()[2] == "CIRD  1001  1002  1")

# ═════════════════════════════════════════════════════════════════════════════
section("1A. NETWORK: user sees the values that are written")
# ═════════════════════════════════════════════════════════════════════════════
written = {f: sl(nl, DLIN[f]).strip() for f in ("R", "X", "S")}
final = [ln for ln in conv["calc_str"].splitlines() if ln.startswith("**Valores para o DLIN:**")][0]
check("'Valores para o DLIN' shows the written R, X, Q",
      final == f"**Valores para o DLIN:** R = {written['R']} %, X = {written['X']} %, Q = {written['S']} Mvar", final)
check("Passo 3 bold results are the written values",
      f"**{written['R']} %**" in conv["calc_str"] and f"**{written['X']} %**" in conv["calc_str"]
      and f"**{written['S']} Mvar**" in conv["calc_str"])
check("step-by-step keeps higher-precision intermediates (Zbase 529.0000 Ω, B_total e-notation)",
      "529.0000" in conv["calc_str"] and "9.817560e-04" in conv["calc_str"])
row = [ln for ln in format_network_summary(net).splitlines() if ln.startswith("| 1 | 1 | 2")][0]
check("review table shows the written values", f"| {written['R']} | {written['X']} | {written['S']} |" in row, row)
pu = convert_line_params(230, "pu", {"R": 0.00874480, "X": 0.10190926, "B": 0.519348924})
check("pu mode final line uses written values", "X = 10.1909 %" in pu["calc_str"] and "Q = 51.935 Mvar" in pu["calc_str"])

tiny = convert_line_params(230, "pct", {"R": 0.00001, "X": 0.00001, "Q": 0})
check("non-zero value written as 0 → visible warning in the conversion text",
      "valor R arredondado para 0 — verifique" in tiny["calc_str"]
      and "valor X arredondado para 0 — verifique" in tiny["calc_str"], tiny["calc_str"])
tnet = dict(net, lines=[dict(net["lines"][0], r_pct=0.00001, x_pct=0.00001, q_mvar=0)])
warns = [i["message"] for i in validate_network(tnet) if i["severity"] == "warning"]
check("…and in the review (validate_network)", any("valor X arredondado para 0 — verifique" in w for w in warns), warns)
check("…and the file gets 0.0000", sl(block_lines(build_full_pwf(tnet), "DLIN")[0], DLIN["X"]).strip() == "0.0000")
hint = [i["how_to_fix"] for i in validate_network(tnet) if "acoplamento" in i["how_to_fix"]]
check("validation hint for coupling lines quotes the constant", hint and "X = 0.0001 %" in hint[0], hint)

# ═════════════════════════════════════════════════════════════════════════════
section("1B. 'modelar' + equipment enters the guided flow")
# ═════════════════════════════════════════════════════════════════════════════
for msg, typ in [("quero modelar uma bess", "BESS"), ("modelar bess", "BESS"), ("quero simular uma bess", "BESS"),
                 ("quero modelar um statcom", "STATCOM"), ("Gostaria de inserir uma bateria na barra 1001", "BESS"),
                 ("oi, modele uma BESS por favor", "BESS")]:
    ch = StreamChain(["resposta"], scores(("a.pdf", 0.8)))
    fresh(ch); run(); run(msg)
    m = last_assistant()
    check(f"'{msg}' → STEP1, sim_type {typ}, deterministic intro, no LLM",
          ss["sim_step"] == "STEP1" and ss["sim_data"].get("sim_type") == typ and m.get("deterministic")
          and m["content"].startswith("Vou te guiar pelo processo") and ch.retrieve_calls == 0,
          (ss["sim_step"], ss["sim_data"], m["content"][:60]))

for msg in ["como modelar uma BESS no ANAREDE?", "o que é uma BESS?", "como modelar uma bess no anarede",
            "quero saber como modelar uma bess", "não quero modelar uma bess agora", "qual a melhor forma de instalar bateria"]:
    ch = StreamChain(["Uma BESS é um sistema de armazenamento."], scores(("a.pdf", 0.8)))
    fresh(ch); run(); run(msg)
    check(f"'{msg}' stays a free question (RAG)",
          ss["sim_step"] == "IDLE" and ch.retrieve_calls == 1 and not last_assistant().get("deterministic"),
          (ss["sim_step"], ch.retrieve_calls))

fresh(None); env = run()
check("existing triggers unchanged", all(env["_is_simulation_intent"](t) for t in env["_SIMULATION_INTENT_TRIGGERS"]))

fresh(StreamChain(["x"], scores(("a.pdf", 0.8)))); run()
run("quero modelar uma bess"); run("2")
check("session repro: 'quero modelar uma bess' then '2' → ONS selected (not a free question about years)",
      ss["sim_step"] == "STEP2" and ss["sim_data"].get("db") == "ONS"
      and last_assistant()["content"].startswith("Base selecionada"), (ss["sim_step"], ss["sim_data"]))

# Guard: an LLM answer imitating the guided-flow intro is discarded when idle.
for fake in ["Ótimo! Vou te guiar pelo processo de simulação.\n\n1. EPE", "Claro, vou guiá-lo no estudo",
             "Vamos começar a simulação!"]:
    ch = StreamChain([fake], scores(("a.pdf", 0.8)))
    fresh(ch); run(); run("me ajuda com armazenamento no SIN")
    m = last_assistant()
    check(f"guard: LLM '{fake[:30]}…' discarded → deterministic intro, STEP1",
          ss["sim_step"] == "STEP1" and m.get("deterministic") and m["content"].startswith("Vou te guiar pelo processo")
          and "Ótimo" not in m["content"] and not m.get("grounding_level") and not ch.remembered,
          (ss["sim_step"], m["content"][:80]))
check("is_guided_intro ignores normal answers",
      not ux.is_guided_intro("Uma BESS é um sistema de baterias. Vou te guiar se quiser.")
      and ux.is_guided_intro("**Ótimo!** Vou te guiar passo a passo"))
ch = StreamChain(["Vou te guiar: abra Histórico > Operações."], scores(("a.pdf", 0.8)))
fresh(ch, step="STEP4", data={"sim_type": "BESS", "db": "ONS", "years": [2028], "year_idx": 0,
                              "year": 2028, "scenario": "Inverno Máxima Diurna"}, status="active")
run(); run("como encontro essa opção?")
check("guard does not apply while a simulation is active", ss["sim_step"] == "STEP4"
      and "Histórico > Operações" in last_assistant()["content"])

# ═════════════════════════════════════════════════════════════════════════════
section("1C. coupling-line wording")
# ═════════════════════════════════════════════════════════════════════════════


def string_literals(path):
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            out.append((node.lineno, "".join(v.value for v in node.values
                                             if isinstance(v, ast.Constant) and isinstance(v.value, str))))
    return out


STALE = re.compile(r"(?<![\d.])0?\.00001(?!\d)")
PU_SMALL = re.compile(r"(?<![\d.])0?\.000\d*\s*\**\s*pu\b")
files = ["app.py"] + sorted(glob.glob("agents/*.py") + glob.glob("config/*.py") + glob.glob("utils/*.py"))
hits, pu_hits = [], []
for path in files:
    if path.endswith("ANAREDE_Lib_siemens.py"):
        continue
    for lineno, s in string_literals(path):
        if STALE.search(s):
            hits.append((path, lineno))
        if PU_SMALL.search(s) or re.search(r"reat[âa]ncia de[^.\n]{0,40}\bpu\b", s):
            pu_hits.append((path, lineno))
prompt_src = open("prompts/system_prompt.py", encoding="utf-8").read()
check("no '0.00001' / '.00001' in user-visible text (app.py, agents/, config/, utils/, prompt)",
      not hits and not STALE.search(prompt_src), hits)
check("no small coupling value / 'reatância de …' labelled 'pu'",
      not pu_hits and not PU_SMALL.search(prompt_src)
      and not re.search(r"reat[âa]ncia de[^.\n]{0,40}\bpu\b", prompt_src), pu_hits)
lits = re.findall(r"(?<![\d.])0?\.000\d+", prompt_src)
check("every coupling literal in the system prompt equals COUPLING_LINE_X_PCT",
      lits and all(float(x) == COUPLING_LINE_X_PCT for x in lits), lits)
code = [(p, n) for p in files for n, s in string_literals(p) if "0.0001" in s and not p.endswith("siemens.py")]
check("0.0001 is not hardcoded in user-visible code text (comes from the constant)", not code, code)

LOADED = {"sim_type": "BESS", "db": "ONS", "years": [2028], "year_idx": 0, "year": 2028,
          "scenario": "Inverno Máxima Diurna"}
fresh(None, step="STEP7", data=LOADED, status="active"); run()
run("1001")
m = last_assistant()
shown = re.search(r"reatância de \*\*([\d.]+) %\*\*", m["content"])
check("STEP7 states the coupling reactance in %", bool(shown), m["content"])
main = m.get("main", m["content"])
check("STEP7: each option once, explanation inline",
      main.count("Controle de tensão") == 1 and main.count("Despacho fixo") == 1
      and "GFM" in main and m["content"].count("Controle de tensão") == 1, m["content"])
run("1"); run("500 MVA"); run("417"); run("91000"); run("Gerar arquivo agora")
gen = re.search(r"```\n(.*?)\n```", ss.messages[-1]["content"], re.S).group(1)
x_written = sl(block_lines(gen, "DLIN")[0], DLIN["X"]).strip()
check("value shown to the user == value in the generated DLIN",
      shown and shown.group(1) == x_written and float(x_written) == COUPLING_LINE_X_PCT, (shown and shown.group(1), x_written))
check("guided flow output == acceptance block", gen == blk)

# ═════════════════════════════════════════════════════════════════════════════
section("Investigation: admin transcript of long messages")
# ═════════════════════════════════════════════════════════════════════════════
import importlib.util
from _harness_v650 import svc, EV
fresh(None, step="IDLE", data={}, status=None, session_id="sessL"); run()
long_msg = "**Qual base de dados deseja utilizar?**\n\n" + ("x" * 1100) + "\n\n3. **Minha própria rede** (montar do zero)"
svc.log_chat_message("userA", "sessL", "assistant", long_msg, "STEP1", message_id="mL")
logs = [r for r in svc.get_chat_logs(user_id="userA") if r["session_id"] == "sessL"]
check("chat_logs stores the full text (no length cap)", logs and logs[-1]["message"] == long_msg)
spec = importlib.util.spec_from_file_location("admin_panel_t", "admin/panel.py")
panel = importlib.util.module_from_spec(spec); spec.loader.exec_module(panel)
EV.clear()
panel._render_transcript(svc.get_session_summary("sessL"), logs, [], lambda *a: None)
check("admin: long message → bubble preview + 'Ver mensagem completa' expander with the full markdown",
      ("expander", "Ver mensagem completa (formatada)") in EV
      and any(e[0] == "markdown" and e[1] == long_msg for e in EV))
EV.clear()
short = [dict(logs[-1], message="curta **ok**")]
panel._render_transcript(svc.get_session_summary("sessL"), short, [], lambda *a: None)
check("admin: short message → no extra expander", ("expander", "Ver mensagem completa (formatada)") not in EV)

H.finish()
