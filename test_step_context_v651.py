"""
v6.5.1 COMMIT 2 — free questions asked mid-simulation are answered about the
CURRENT step: the LLM gets the step label, the full text of the guide message(s)
shown at that step and a per-request instruction (the LLM is faked; the test
asserts on the context it receives).

Run from repo root:  python3 test_step_context_v651.py
"""
import _harness_v650 as H
from _harness_v650 import ss, check, section, fresh, run, last_assistant, StreamChain, scores, SCRIPT, EV
from agents import ux

TESTER_Q = "nao to achando na interface essa opcao que voce indicou. como encontrar ?"
STEP1_Q = "Qual base de dados deseja utilizar?"


def guide_msg(step):
    """Last deterministic (non-notice) message shown at `step`."""
    return [m for m in ss.messages if m.get("role") == "assistant" and m.get("deterministic")
            and not m.get("notice") and m.get("sim_step_after") == step][-1]["content"]


def ask(question, level=0.8):
    ch = StreamChain(["Resposta sobre o passo atual."], scores(("manual.pdf", level)))
    ss["chain"] = ch
    run(question)
    return ch


def press(label):
    SCRIPT["press"] = {label}
    run()
    SCRIPT["press"] = set()


def to_step4():
    fresh(StreamChain(["x"], scores(("a.pdf", 0.8)))); run()
    run("quero simular uma bess")      # STEP1 question
    run("2")                           # ONS → STEP2
    run("2028")                        # STEP3
    run("4")                           # Inverno Máxima Diurna → STEP4
    assert ss["sim_step"] == "STEP4", ss["sim_step"]


# ═════════════════════════════════════════════════════════════════════════════
section("Reproduction: STEP4 (Histórico > Operações > Restabelecer)")
# ═════════════════════════════════════════════════════════════════════════════
to_step4()
step4 = guide_msg("STEP4")
check("STEP4 guide message tells to open Histórico > Operações and click Restabelecer",
      "Histórico > Operações" in step4 and "Restabelecer" in step4)
ch = ask(TESTER_Q)
ctx = (ch.last_inputs or {}).get("study_context", "")
check("the question reaches the LLM unchanged", (ch.last_inputs or {}).get("question") == TESTER_Q)
check("context has the current step label", "Current step: STEP 4: Carregar SAV" in ctx, ctx[:300])
check("context has the FULL STEP4 message", step4 in ctx, ctx)
check("context has the per-request instruction", ux.STEP_CONTEXT_INSTRUCTION in ctx
      and "do not restart earlier steps" in ctx)
check("context does NOT carry the STEP1 database question (EPE/ONS)",
      STEP1_Q not in ctx and "EPE (PDE)" not in ctx, ctx)
check("simulation state untouched (still STEP4)", ss["sim_step"] == "STEP4")
check("the ↩️ nudge is still appended to the answer", "↩️" in last_assistant()["content"])

ch = ask("e depois disso?")
ctx2 = ch.last_inputs["study_context"]
check("second free question at the same step: same STEP4 context (LLM answers are skipped)",
      step4 in ctx2 and "Resposta sobre o passo atual" not in ctx2)

# ═════════════════════════════════════════════════════════════════════════════
section("Same at STEP7 and STEP9")
# ═════════════════════════════════════════════════════════════════════════════
run("convergido")                     # STEP6
run("vou desenhar")                   # STEP7 bus question
run("1001")                           # STEP7 mode question
check("at STEP7 (mode question)", ss["sim_step"] == "STEP7")
ch = ask("o que significa isso?")
ctx = ch.last_inputs["study_context"]
check("STEP7: label + bus question that opened the step + latest mode question",
      "Current step: STEP 7: Barra" in ctx and "Qual é a barra onde deseja inserir o BESS?" in ctx
      and "Qual o modo de operação da BESS?" in ctx, ctx)
check("STEP7: no STEP4 hint, no STEP1 question",
      "Restabelecer" not in ctx and STEP1_Q not in ctx)

run("1"); run("500 MVA"); run("417"); run("91000")
gen = [b for b in ("Gerar arquivo agora",) if ss["sim_step"] == "STEP8"]  # COMMIT 4 adds a choice here
if gen:
    run(gen[0])
check("at STEP9 (save the case)", ss["sim_step"] == "STEP9", ss["sim_step"])
step9 = guide_msg("STEP9")
ch = ask("onde fica o campo Caso?")
ctx = ch.last_inputs["study_context"]
check("STEP9: label + full STEP9 message (block + save instructions)",
      "Current step: STEP 9: Salvar caso" in ctx and step9 in ctx and "Clique em **Salvar**" in ctx)
check("STEP9: nothing from STEP7/STEP4/STEP1",
      "Qual o modo de operação" not in ctx and "Restabelecer" not in ctx and STEP1_Q not in ctx)

# ═════════════════════════════════════════════════════════════════════════════
section("After pause, and after resume")
# ═════════════════════════════════════════════════════════════════════════════
to_step4()
press("⏸️ Pausar simulação")
check("paused at STEP4", ss["sim_status"] == "paused" and ss["sim_step"] == "STEP4")
ch = ask(TESTER_Q)
ctx = ch.last_inputs["study_context"]
check("paused: context still the STEP4 message (pause notice skipped)",
      step4 in ctx and "Simulação pausada" not in ctx and STEP1_Q not in ctx, ctx)
check("paused: still paused after the free question", ss["sim_status"] == "paused")
press("▶️ Retomar")
check("resumed", ss["sim_status"] == "active")
ch = ask(TESTER_Q)
ctx = ch.last_inputs["study_context"]
check("resumed: context is the STEP4 message, not the 'Simulação retomada' notice",
      step4 in ctx and "Simulação retomada" not in ctx and STEP1_Q not in ctx, ctx)
run("retomar")  # typed resume while active: plain text, no state change expected
ch = ask(TESTER_Q)
check("context rebuilt each time (still STEP4)", step4 in ch.last_inputs["study_context"])

# Resumed after logout: the history is gone; the STEP4 instructions are rebuilt
# from the simulation state.
LOADED = {"sim_type": "BESS", "db": "ONS", "years": [2028], "year_idx": 0, "year": 2028,
          "scenario": "Inverno Máxima Diurna"}
fresh(None, step="STEP4", data=LOADED, status="active"); run()
ss["chain"] = None
ch = ask(TESTER_Q)
ctx = ch.last_inputs["study_context"]
check("after logout/login resume (no history): STEP4 instructions rebuilt from state",
      "Histórico > Operações" in ctx and "Restabelecer" in ctx and "2028.SAV" in ctx, ctx)

# The context follows the step when it changes.
run("convergido")
ch = ask("como faço isso?")
ctx = ch.last_inputs["study_context"]
check("after moving on (STEP6), the context is STEP6 — not cached from STEP4",
      "Current step: STEP 6: Diagrama LST" in ctx and "Restabelecer" not in ctx, ctx)

# ═════════════════════════════════════════════════════════════════════════════
section("Low grounding at the current step")
# ═════════════════════════════════════════════════════════════════════════════
to_step4()
ch = ask(TESTER_Q, level=0.3)
m = last_assistant()
from agents import grounding as G
check("red grounding mid-simulation: disclosure, then a brief note that the documents do not cover this step",
      m["content"].startswith(G.DISCLOSURE + "\n\nℹ️ Os documentos consultados não cobrem diretamente o passo atual "
                              "(**STEP 4: Carregar SAV**)."), m["content"][:300])
check("…the LLM is told the same (instruction in context)", "do not cover this step" in ch.last_inputs["study_context"])
fresh(StreamChain(["r"], scores(("a.pdf", 0.3)))); run(); run("O que é uma BESS?")
check("no simulation: no step note, no step context",
      "passo atual" not in last_assistant()["content"]
      and "GUIDED SIMULATION" not in ss["chain"].last_inputs["study_context"])

# ═════════════════════════════════════════════════════════════════════════════
section("Pure builder")
# ═════════════════════════════════════════════════════════════════════════════
check("step_context('', []) is empty", ux.step_context("STEP 4", []) == "")
one = ux.step_context("STEP 4: Carregar SAV", ["Abra Histórico > Operações."])
check("one message → 'Last guide message' + instruction",
      "Last guide message shown to the user:\n<<<\nAbra Histórico > Operações.\n>>>" in one
      and one.endswith(ux.STEP_CONTEXT_INSTRUCTION))
two = ux.step_context("STEP 7: Barra", ["Qual barra?", "Qual modo?"])
check("two messages → opening + latest", "opened this step:\n<<<\nQual barra?" in two and "Latest guide message" in two)
check("system prompt not edited in this commit (placeholder still {study_context})",
      "{study_context}" in open("prompts/system_prompt.py", encoding="utf-8").read())

H.finish()
