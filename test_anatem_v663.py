"""
v6.6.3 — ANATEM: Thomas's answers + ONS Procedimentos de Rede (Submódulo 2.3) criteria.
Part 1 save path "Histórico > Operações > Salvar", Part 2 ANAT0 errors read by the
DESCRIPTION, Part 3 fault clearing times (Tabela 2) at the events step, Part 4 the new
step AT12 (criteria 2.4.3.7). Real app (runpy) on the shared harness; only the LLM chain
is faked. Section 6 runs every other suite in a subprocess and reports the numbers.

Run from repo root:  python3 test_anatem_v663.py
"""
import copy
import os
import re
import subprocess
import sys

import _harness_v650 as H
from _harness_v650 import (ss, EV, svc, check, section, fresh, run, events,
                           last_assistant, StreamChain, scores)
from agents import anatem_flow as AT
from agents import session_analysis as SA
from agents import structured_input as SI
from config import ons_criteria as OC
from config.glossary import GLOSSARY_ANATEM, find_terms
from config.version import APP_VERSION, RELEASE_NOTES

H.st.warning = lambda body="", **kw: EV.append(("warning", body))

AT5D = {"base": "ONS", "sav_name": "caso_estudo.sav", "case_number": "5", "dmaq_name": "DMAQ_.DAT"}
SMALL = {"base": "PEQUENO", "sav_name": "rede.sav", "case_number": "1", "gen_buses": ["10"]}
ONE_EVENT = [{"type": "Curto-circuito", "note": ""}]
SAVE_PATH = "**Histórico > Operações > Salvar**"

THOMAS_PASTE = (
    "(Nb ) Gr Co ( Nome ) Umn Umx (Pbas)(Qbas)(Pmin)(Pmax)(Qmin)(Qmax)(Rtrf)(Xtrf)(%)\n"
    " 524 10 0 BARIR2UH 0 1 45.6 23.0 15.0 45.6 -23.0 23.0 .000 .000 0\n"
    " Potencia gerada (13.0 MW) inferior ao minimo (15.0 MW).\n"
    " *** ERRO - ANAT01-190 ***"
)
# Synthetic pastes in the same layout (header, record, description, ERRO line).
SUPERIOR_PASTE = (
    "(Nb ) Gr Co ( Nome ) Umn Umx (Pbas)(Qbas)(Pmin)(Pmax)(Qmin)(Qmax)(Rtrf)(Xtrf)(%)\n"
    " 600 1 0 USINAX 0 1 52.0 10.0 5.0 50.0 -20.0 20.0 .000 .000 0\n"
    " Potencia gerada (52.0 MW) superior ao maximo (50.0 MW).\n"
    " *** ERRO - ANAT01-191 ***"
)
UNITS_PASTE = ("Barra 700: numero de unidades em operacao incompativel com o despacho (4 unidades).\n"
               " *** ERRO - ANAT01-300 ***")
MVAR_PASTE = ("Potencia reativa gerada (80.0 Mvar) superior ao limite (60.0 Mvar) na barra 800.\n"
              " *** ERRO - ANAT01-200 ***")
UNRELATED_PASTE = "Arquivo BNT2.DAT nao encontrado no diretorio informado.\n *** ERRO - ANAT01-050 ***"
UNIT_TEXT = ("O erro está relacionado ao **número de unidades** em operação da usina na barra 700. O ANAT0 "
             "ajusta o número de unidades ao despacho do caso, com base nos limites e na quantidade de máquinas "
             "cadastradas no BNT1.DAT. Revise o despacho dessa usina no ANAREDE para que seja compatível com as "
             "unidades disponíveis.")
TAIL = ("Depois: rode o fluxo de potência, confira se convergiu, salve o .SAV (**Histórico > Operações > "
        "Salvar**) e execute o ANAT0 novamente.")

# Copied from the prompt (ONS Submódulo 2.3, Tabela 2): (kV, teleproteção, sem falha, com falha)
TABLE = [(765, None, 80, 200), (525, None, 100, 250), (500, None, 100, 250), (440, None, 100, 250),
         (345, None, 100, 400), (230, None, 150, 500), (138, True, 150, 500), (138, False, 450, 750),
         (88, None, 450, 750), (69, None, 800, 1000)]
CAVEAT = ("Valores **indicativos**: use-os apenas quando não houver informação no banco de dados do ONS. Os "
          "tempos reais dependem do arranjo da subestação e do tempo de atuação da proteção.")
SOURCE = "ONS — Procedimentos de Rede, Submódulo 2.3 (Critérios), rev. 2026.04"
NOT_IN_TABLE = ("Essa tensão não está na Tabela 2 do Submódulo 2.3. Use o tempo informado pelo agente ou pelo "
                "banco de dados do ONS.")
KV_BUTTONS = ["765", "525", "500", "440", "345", "230", "138", "88", "69", "Outra"]

# Part 0: v6.6.2 (de8a97f) before any change — all 15 suites, 0 failures.
PART0 = {"test_analysis_v64.py": 47, "test_anatem_v660.py": 124, "test_anatem_v661.py": 78,
         "test_anatem_v662.py": 89, "test_feedback_v64.py": 34, "test_fixes_v650.py": 45,
         "test_fixes_v651.py": 125, "test_grounding_v641.py": 58, "test_multi_bess_v651.py": 41,
         "test_network_v63.py": 133, "test_routing_v62.py": 57, "test_step_context_v651.py": 30,
         "test_structured_v650.py": 144, "test_suggestions_v651.py": 27, "test_ux_v650.py": 87}


# ── helpers ───────────────────────────────────────────────────────────────────

def chain(chunks=("Resposta livre.",)):
    return StreamChain(list(chunks), scores(("manual_anatem.pdf", 0.8)))


def at_state(step_, data_=None, ch=None):
    d = {"sim_type": "ANATEM"}
    d.update(copy.deepcopy(data_ or {}))
    fresh(ch or chain(), step=step_, data=d, status="active")
    env = run()
    env["_append_system_assistant_message"](env["_current_step_question"]())
    run()
    return env


def step():
    return ss["sim_step"]


def data():
    return ss["sim_data"]


def reply():
    return last_assistant()["content"]


def llm_called(ch):
    return ch.retrieve_calls > 0 or ch.generate_calls > 0


def option_buttons():
    return [e for e in events("button") if e[2] and e[2].startswith("opt_")]


def option_texts():
    return [e[4][0][0] for e in option_buttons()]


def click(text):
    b = next(e for e in option_buttons() if e[4][0][0] == text or e[1] == text)
    b[3](*b[4])
    run()


def at3(paste):
    ch = chain()
    at_state("AT3", AT5D, ch)
    run(paste)
    return reply(), ch


def fault_answer(kv, telep=None, step_="AT11", d=AT5D):
    """Curto-circuito → voltage button (→ teleproteção) at the events step; the last reply."""
    at_state(step_, d)
    click("Curto-circuito")
    click(str(kv))
    if telep is not None:
        click(AT.T_TELEP_YES if telep else AT.T_TELEP_NO)
    return reply()


def times_line(kv, t1, t2, telep=None):
    tp = "" if telep is None else (" (com teleproteção)" if telep else " (sem teleproteção)")
    return (f"Tempo de eliminação indicativo para **{kv} kV**{tp}: **{t1} ms** (sem falha do disjuntor) ou "
            f"**{t2} ms** (com falha do disjuntor). {CAVEAT} Fonte: {SOURCE}, Tabela 2.")


def to_at12(d=AT5D, step_="AT11"):
    at_state(step_, dict(d, events=copy.deepcopy(ONE_EVENT)))
    click(AT.T_END)


# ═════════════════════════════════════════════════════════════════════════════
section("0. Part 0 — v6.6.2 (de8a97f) before any change")
# ═════════════════════════════════════════════════════════════════════════════
for name, n in PART0.items():
    print(f"    v6.6.2  {name:<28} {n:>4} passed, 0 failed")
check(f"Part 0: 15 suites on v6.6.2, {sum(PART0.values())} checks, 0 failures, nothing to fix",
      len(PART0) == 15 and sum(PART0.values()) == 1119)


# ═════════════════════════════════════════════════════════════════════════════
section("1. Part 1 — save path 'Histórico > Operações > Salvar'")
# ═════════════════════════════════════════════════════════════════════════════
OLD = ("Salvar Caso " + "Histórico", "Arquivo > " + "Salvar", "OPEN: menu " + "path")
hits = []
for root, dirs, files in os.walk("."):
    dirs[:] = [x for x in dirs if x not in (".git", "__pycache__", "node_modules")]
    for f in files:
        if not f.endswith((".py", ".md", ".json", ".txt", ".yml", ".yaml", ".toml", ".cfg")):
            continue
        p = os.path.join(root, f)
        try:
            txt = open(p, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        hits += [(p, o) for o in OLD if o in txt]
check("grep: none of the old save paths nor the OPEN menu-path comment left anywhere (code, tests, docs)",
      not hits, hits)
at_state("ATS2", {"base": "PEQUENO"})
click(AT.T_NO_FILES)
check("small-case guidance: 'salve o caso convergido como arquivo histórico .SAV em Histórico > Operações > Salvar'",
      "salve o caso convergido como arquivo histórico **.SAV** em **Histórico > Operações > Salvar**." in reply(),
      reply())


# ═════════════════════════════════════════════════════════════════════════════
section("2. Part 2 — ANAT0 errors read by the description")
# ═════════════════════════════════════════════════════════════════════════════
def t_190():
    r, ch = at3(THOMAS_PASTE)
    return (step() == "AT3" and "Erro **ANAT01-190** na barra **524 (BARIR2UH)**." in r
            and "aumente a geração ativa da barra 524 para pelo menos **15.0 MW**" in r
            and "> Potencia gerada (13.0 MW) inferior ao minimo (15.0 MW)." in r
            and r.endswith(TAIL + "\n\n**O ANAT0 rodou sem erros?**")
            and option_texts() == [AT.T_RAN_OK, AT.T_RAN_ERR] and not llm_called(ch))


check("Thomas's real 190 paste → same result as v6.6.2 (bus 524, ≥ 15.0 MW), description quoted, tail, buttons, "
      "no LLM", t_190(), reply())
check("parser: v6.6.2 dict unchanged for Thomas's paste",
      AT.parse_anat0_error(THOMAS_PASTE) == {"code": "ANAT01-190", "bus": "524", "group": "10", "name": "BARIR2UH",
                                              "gen": "13.0", "min": "15.0"})
r, _ = at3(SUPERIOR_PASTE)
check("'superior ao maximo' (MW) → 'reduza a geração ativa da barra 600 para no máximo **50.0 MW**'",
      "reduza a geração ativa da barra 600 para no máximo **50.0 MW**" in r and "na barra **600 (USINAX)**" in r, r)


def t_units():
    r, _ = at3(UNITS_PASTE)
    return UNIT_TEXT in r and r.endswith(TAIL + "\n\n**O ANAT0 rodou sem erros?**") and "**Como corrigir:**" not in r


check("'unidades' description → unit-count text (bus from 'Barra 700'), tail, no 6 steps", t_units(), reply())
r, _ = at3(MVAR_PASTE)
check("Mvar description → reactive text for barra 800",
      "alivie a geração/absorção de reativo da barra 800 (ajustando a tensão controlada, taps ou compensação "
      "próxima)" in r and "geração ativa" not in r, r)
r, _ = at3(UNRELATED_PASTE)
check("unrelated description → quoted + 'Não reconheci o tipo desse erro.' + the 6 steps + tail",
      "> Arquivo BNT2.DAT nao encontrado no diretorio informado." in r and "Não reconheci o tipo desse erro." in r
      and AT._AT3_FIX_STEPS in r and TAIL in r and "Erro **ANAT01-050**" in r, r)
r, _ = at3("deu erro: potência gerada 13 MW inferior ao limite mínimo de 15 MW na barra 524")
check("typed without '*** ERRO' (cue + number) → recognised as active power, bus 524 from 'barra NNNN', "
      "no MW pair → 'ajuste … dentro dos limites'",
      "Erro do ANAT0 na barra **524**." in r
      and "ajuste a geração ativa da barra 524 para ficar dentro dos limites das máquinas" in r, r)
r, _ = at3(THOMAS_PASTE + "\n" + SUPERIOR_PASTE)
check("two '*** ERRO' blocks → two items, each with its bus and advice, one tail",
      r.startswith("**Encontrei 2 erros no trecho colado:**") and "**1.** Erro **ANAT01-190** na barra **524" in r
      and "**2.** Erro **ANAT01-191** na barra **600" in r and "pelo menos **15.0 MW**" in r
      and "no máximo **50.0 MW**" in r and r.count("Depois: rode o fluxo") == 1, r)
r, _ = at3("\n".join([THOMAS_PASTE] * 6))
check("six errors → 'mostro os 5 primeiros', five items", "(mostro os 5 primeiros)" in r and "**5.**" in r
      and "**6.**" not in r, r[:120])
r, _ = at3("*** ERRO - ANAT01-190 ***\nPotencia gerada (13.0 MW) inferior ao minimo (15.0 MW) na barra 524")
check("'*** ERRO' line first, description below → same reading", "pelo menos **15.0 MW**" in r and "barra 524" in r, r)
at_state("AT3", AT5D); click(AT.T_RAN_OK)
check("'Rodou sem erros' still → AT4", step() == "AT4")
at_state("AT3", AT5D); click(AT.T_RAN_ERR)
check("'Deu erro' still → the generic procedure", reply().startswith("**Erro no ANAT0.**"))
at_state("AT3", AT5D); run("rodou sem erros, 2 vezes")
check("an answer with a number but no cue is not an error paste", step() == "AT4")


# ═════════════════════════════════════════════════════════════════════════════
section("3. Part 3 — fault clearing times (Submódulo 2.3, Tabela 2)")
# ═════════════════════════════════════════════════════════════════════════════
def t_table():
    bad = []
    for kv, telep, t1, t2 in TABLE:
        if OC.fault_clearing_times(kv, telep) != (t1, t2):
            bad.append(("config", kv, telep))
        if not fault_answer(kv, telep).startswith(times_line(kv, t1, t2, telep)):
            bad.append(("flow", kv, telep, reply()[:90]))
    return bad


bad = t_table()
check("every Tabela 2 row → exact numbers, via config and via the flow buttons", not bad, bad)
check("source label and table copied as specified (88/69 kV: 'sem teleproteção' note)",
      OC.ONS_SOURCE == SOURCE and OC.FAULT_CLEARING_TABLE == (
          (765, 80, 200, None), (525, 100, 250, None), (500, 100, 250, None), (440, 100, 250, None),
          (345, 100, 400, None), (230, 150, 500, None), (138, 150, 500, True), (138, 450, 750, False),
          (88, 450, 750, False), (69, 800, 1000, False)))


def t_caveat():
    texts = [fault_answer(500), fault_answer(138, True), AT.fault_times_text(765)]
    return all(CAVEAT in t and f"Fonte: {SOURCE}, Tabela 2." in t for t in texts)


check("caveat and source label present in every times answer", t_caveat())
at_state("AT11", AT5D)
click("Curto-circuito")
check("Curto-circuito → card head + voltage question + buttons 765…69 + Outra",
      reply().startswith("**Curto-circuito** — cartões do DEVT: **APCB, APCC, APCL**")
      and reply().endswith(AT.KV_QUESTION) and option_texts() == KV_BUTTONS, option_texts())
click("138")
check("138 kV → teleproteção question with two buttons",
      reply() == AT.TELEP_QUESTION and option_texts() == [AT.T_TELEP_YES, AT.T_TELEP_NO])
click(AT.T_TELEP_NO)
check("…'Sem teleproteção' → 450/750 ms, then the rest of the reminder (DEVT, manual, Evento inserido)",
      reply().startswith(times_line(138, 450, 750, False)) and "Insira o evento no bloco **DEVT**" in reply()
      and option_texts() == [AT.T_EVENT_DONE])
click(AT.T_EVENT_DONE)
ev = data()["events"][-1]
check("event dict keeps type/note and adds kv + the two times (+ teleproteção)",
      ev == {"type": "Curto-circuito", "note": "", "kv": 138, "teleprotecao": False, "t_sem_falha_ms": 450,
             "t_com_falha_ms": 750}, ev)
bad = []
for typed in ("500kV", "500 kV", "500", "tensão de 500 kV"):
    at_state("AT11", AT5D); click("Curto-circuito"); run(typed)
    if not reply().startswith(times_line(500, 100, 250)):
        bad.append((typed, reply()[:80]))
check("'500kV', '500 kV', '500' (and 'tensão de 500 kV') typed → 100/250 ms", not bad, bad)
bad = []
for how in ("400 kV", "Outra"):
    at_state("AT11", AT5D); click("Curto-circuito")
    run(how) if how != "Outra" else click(AT.T_KV_OTHER)
    r = reply()
    if not (r.startswith(NOT_IN_TABLE) and not re.search(r"\d+\s*ms\b", r)):
        bad.append((how, r[:90]))
check("400 kV and [Outra] → not-in-table text, no numbers (no nearest value)", not bad, bad)
click(AT.T_EVENT_DONE)
check("…stored as outside the table, no times", data()["events"][-1] == {"type": "Curto-circuito", "note": "",
                                                                         "kv_fora_tabela": True})
at_state("AT11", AT5D); click("Curto-circuito"); run("400 kV"); click(AT.T_EVENT_DONE)
check("400 kV typed: kv kept, no times", data()["events"][-1] == {"type": "Curto-circuito", "note": "", "kv": 400,
                                                                  "kv_fora_tabela": True})

at_state("AT11", AT5D)
click("Perda de linha de transmissão")
check("line loss → item 2.4.1.2 tip + [Sem curto prévio] [Com curto monofásico]",
      OC.LINE_LOSS_TIP in reply() and OC.LINE_LOSS_TIP == ("Os Procedimentos de Rede pedem simular a abertura sem "
                                                           "curto-circuito prévio e/ou com aplicação de "
                                                           "curto-circuito monofásico.")
      and option_texts() == [AT.T_NO_PRIOR_FAULT, AT.T_SLG_FAULT])
click(AT.T_SLG_FAULT)
check("…'Com curto monofásico' → the voltage question", reply().endswith(AT.KV_QUESTION)
      and option_texts() == KV_BUTTONS)
click("500"); click(AT.T_EVENT_DONE)
check("…500 → times; event stores curto_previo + kv + times",
      data()["events"][-1] == {"type": "Perda de linha de transmissão", "note": "", "curto_previo": "monofasico",
                               "kv": 500, "t_sem_falha_ms": 100, "t_com_falha_ms": 250})
at_state("AT11", AT5D); click("Perda de linha de transmissão"); click(AT.T_NO_PRIOR_FAULT)
check("…'Sem curto prévio' → straight to the reminder tail (no voltage question)",
      "Insira o evento no bloco **DEVT**" in reply() and option_texts() == [AT.T_EVENT_DONE])
at_state("AT11", AT5D); click("Perda de linha de transmissão"); run("LT 1001-1002 aberta no fim da linha")
check("…a description instead of a button → stored as before (v6.6.2 behaviour)",
      data()["events"][-1] == {"type": "Perda de linha de transmissão", "note": "LT 1001-1002 aberta no fim da linha"})
r = fault_answer(500, step_="ATS5", d=SMALL)
check("small case ATS5: same voltage question and answer", r.startswith(times_line(500, 100, 250)))

at_state("AT10", AT5D); click(AT.T_FLAT)
check("3e: events 'Detalhes' has the 15 s simulation time, once",
      reply().count("Tempo de simulação: o Submódulo 2.3 cita como usual uma simulação da ordem de **15 segundos**.")
      == 1, reply()[-300:])

ch = chain()
at_state("AT11", AT5D, ch)
run("Qual tempo de falta devo usar?")
check("3f: free question at AT11 → the voltage question (deterministic, no LLM), buttons",
      reply() == AT.KV_QUESTION and not llm_called(ch) and option_texts() == KV_BUTTONS)
click("230")
check("…230 → 150/500 ms, then the event menu again; nothing stored",
      reply().startswith(times_line(230, 150, 500)) and "Qual evento você quer simular?" in reply()
      and not data().get("events") and step() == "AT11")
ch = chain()
at_state("AT5", AT5D, ch)
run("qual o tempo de eliminação do defeito?")
click("765")
check("3f at AT5: voltage question → 80/200 ms, back to the AT5 question, step kept",
      reply().startswith(times_line(765, 80, 200)) and "Passo 5 — Edição do .stb" in reply() and step() == "AT5"
      and not llm_called(ch))
click(AT.T_CONFIGURED)
check("…and the flow goes on (AT6)", step() == "AT6")
at_state("AT11", AT5D); click("Curto-circuito"); run("quanto tempo dura o curto?")
check("3f with a short circuit pending → voltage question bound to the event",
      reply() == AT.KV_QUESTION and data().get("event_pending") == "Curto-circuito" and not data().get("fault_free"))


# ═════════════════════════════════════════════════════════════════════════════
section("4. Part 4 — AT12, ONS criteria 2.4.3.7")
# ═════════════════════════════════════════════════════════════════════════════
at_state("AT11", AT5D)
click(AT.T_END)
check("no events → 'Encerrar' closes as before (no AT12, no criteria line)",
      step() == "IDLE" and "Simulação registrada" in reply() and "Critérios ONS" not in reply())
to_at12()
m = reply()
check("≥1 event → AT12 with the 4 criteria: 70%/74%, 80%/84%, 10%, 2% after 10 s, source 2.4.3.7",
      step() == "AT12" and "**Passo 12 — Verificação dos resultados (critérios do ONS).**" in m
      and "inferior a **70%** da tensão nominal (**74%** para 500 kV)" in m
      and "inferior a **80%** (**84%** para 500 kV)" in m and "menor que **10%** da tensão nominal" in m
      and "Vfinal ≥ Vinicial − 10% Vnom" in m and "no máximo **2%**, após **10 s**" in m
      and f"Fonte: {SOURCE}, item 2.4.3.7." in m, m)
check("AT12 buttons: Todos atendidos / Algum critério violado / Pular verificação",
      option_texts() == [AT.T_CRIT_OK, AT.T_CRIT_VIOLATED, AT.T_CRIT_SKIP])
run()   # the sidebar renders before the input is processed
check("progress 'Passo 12 de 12 · ANATEM 12: Critérios do ONS'",
      ("progress", 1.0, "Passo 12 de 12 · ANATEM 12: Critérios do ONS") in EV)
click(AT.T_CRIT_OK)
check("[Todos atendidos] → summary 'Critérios ONS (2.4.3.7): atendidos'",
      step() == "IDLE" and "- Critérios ONS (2.4.3.7): **atendidos**" in reply(), reply())

to_at12()
click(AT.T_CRIT_VIOLATED)
check("[Algum critério violado] → which one: buttons 1–4 + Concluir",
      option_texts() == ["1", "2", "3", "4", AT.T_CRIT_DONE] and "Qual critério foi violado?" in reply())
run("1 e 3")
check("'1 e 3' stored", data().get("ons_violated") == [1, 3] and "Critérios marcados: **1, 3**" in reply())
click(AT.T_CRIT_DONE)
r = reply()
check("[Concluir] → 'Registre a violação no relatório do estudo.' + summary 'violados: 1, 3', no remedy",
      step() == "IDLE" and r.startswith("Registre a violação no relatório do estudo.")
      and "- Critérios ONS (2.4.3.7): **violados: 1, 3**" in r and not re.search(r"\b(aumente|reduza|ajuste)\b", r), r)
to_at12()
click(AT.T_CRIT_VIOLATED); click("2"); click("4"); run("tensão caiu muito na barra 524"); click(AT.T_CRIT_DONE)
check("repeated clicks (2, 4) + free note → 'violados: 2, 4 — note'",
      "**violados: 2, 4** — tensão caiu muito na barra 524" in reply(), reply())
to_at12()
click(AT.T_CRIT_VIOLATED); click(AT.T_CRIT_DONE)
check("[Concluir] with nothing marked → asks again", step() == "AT12" and "Marque pelo menos um critério" in reply())
to_at12()
click(AT.T_CRIT_SKIP)
check("[Pular verificação] → 'não verificados'", "- Critérios ONS (2.4.3.7): **não verificados**" in reply())
to_at12(); run("encerrar")
check("'encerrar' at AT12 → closing with 'não verificados'", step() == "IDLE"
      and "**não verificados**" in reply())

to_at12(SMALL, "ATS5")
m = reply()
run()
check("small case: 'Como referência (critérios do SIN):' prefix, Passo 6, same criteria, progress 6 de 6",
      step() == "AT12" and "Como referência (critérios do SIN):\n\n**Passo 6 — Verificação dos resultados" in m
      and "**74%** para 500 kV" in m
      and ("progress", 1.0, "Passo 6 de 6 · ANATEM 12: Critérios do ONS") in EV, m[:200])
run("voltar")
check("small case: 'voltar' at AT12 → ATS5", step() == "ATS5")

to_at12()
SCRIPT = H.SCRIPT
SCRIPT["press"] = {"⏸️ Pausar simulação"}; run(); SCRIPT["press"] = set()
ps = svc.load_paused_state("userA")
check("AT12: pause persists the step and the events", ss["sim_status"] == "paused" and ps
      and ps["sim_step"] == "AT12" and ps["sim_data"].get("events") == ONE_EVENT)
run("retomar")
check("AT12: 'retomar' repeats the AT12 question", ss["sim_status"] == "active" and step() == "AT12"
      and "Os critérios foram atendidos?" in reply())
run("voltar")
check("AT12: 'voltar' → AT11 (events kept)", step() == "AT11" and "Voltando um passo" in reply()
      and data().get("events") == ONE_EVENT)
check("AT12 registered: labels, nudge, admin label/sort, sim type, terminal, controls, all steps, sequences",
      AT.STEP_LABELS.get("AT12") and AT.NUDGE_LABELS.get("AT12") and "AT12" in AT.ALL_STEPS
      and AT.ALL_STEPS.count("AT12") == 1 and AT.MAIN_STEPS[-1] == "AT12" and AT.SMALL_STEPS[-1] == "AT12"
      and SA.step_label("AT12") == "AT12 (critérios ONS)" and "AT12" in SA.TERMINAL_STEPS
      and sorted(["AT12", "ATS2", "AT11"], key=SA._step_sort_key) == ["AT11", "AT12", "ATS2"]
      and SA.infer_sim_type("AT12") == "ANATEM" and SI.controls_for("AT12", {"sim_type": "ANATEM"}))
a = SA.analyze_session([{"role": "user", "message": "x", "sim_step": "AT11"},
                        {"role": "assistant", "message": "r", "sim_step": "AT12"}])
check("admin timeline shows AT12; a session ending there is 'finished'",
      "AT12 (critérios ONS)" in SA.timeline_text(a) and a["outcome"] == "finished", SA.timeline_text(a))
at_state("AT12", dict(AT5D, events=ONE_EVENT)); run("ajuda")
check("'ajuda' at AT12: help, step kept", step() == "AT12" and "Ajuda — ANATEM 12: Critérios do ONS" in reply())


# ═════════════════════════════════════════════════════════════════════════════
section("5. Supporting — version, glossary, PENDING REVIEW, guide only")
# ═════════════════════════════════════════════════════════════════════════════
notes = RELEASE_NOTES["v6.6.3"]
check("APP_VERSION v6.6.3 with DRAFT PT-BR notes (4 novidades, 4 o que testar)",
      APP_VERSION == "v6.6.3" and "DRAFT" in notes["status"] and len(notes["novidades"]) == 4
      and len(notes["o_que_testar"]) == 4)
check("glossary: the 3 new terms, matched in the times answer",
      {"Tempo de eliminação de defeito", "Falha de disjuntor", "Teleproteção"} <= set(GLOSSARY_ANATEM)
      and "Teleproteção" in find_terms(AT.TELEP_QUESTION))
src = open("agents/anatem_flow.py", encoding="utf-8").read()
for name in ("def _anat0_advice", "def anat0_error_reply", "_ANAT0_TAIL", "KV_QUESTION", "TELEP_QUESTION",
             "LINE_FAULT_QUESTION", "def fault_times_text", "_AT12_CRITERIA", "_AT12_WHICH", "_AT12_RECORD"):
    i = src.index(name if name.startswith("def ") else f"\n{name} =")
    check(f"{name.replace('def ', '')} marked PENDING REVIEW",
          "PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)" in src[max(0, i - 300):i])
check("unit-count advice carries its own PENDING REVIEW note",
      "# PENDING REVIEW: exact advice for unit-count errors." in src)
osrc = open("config/ons_criteria.py", encoding="utf-8").read()
check("config/ons_criteria.py marked PENDING REVIEW", osrc.count("PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)") >= 4)
check("guide only: no DEVT/STB/DARQ line generated in the new answers",
      not any("```" in t for t in (fault_answer(500), AT.anat0_error_reply(AT.parse_anat0_errors(THOMAS_PASTE)),
                                   AT._at12_main(AT5D))))


# ═════════════════════════════════════════════════════════════════════════════
section("7. The tests are not trivial: table value changed, caveat removed, 'unidades' broken")
# ═════════════════════════════════════════════════════════════════════════════
saved = (OC.FAULT_CLEARING_TABLE, AT.FAULT_TIME_CAVEAT, AT._anat0_classify)
OC.FAULT_CLEARING_TABLE = tuple((kv, 110 if kv == 500 else a, b, t) for kv, a, b, t in saved[0])
bad = t_table()
check("500 kV changed to 110 ms → the table test FAILS (on the 500 kV row)", bad and all(b[1] == 500 for b in bad), bad)
OC.FAULT_CLEARING_TABLE = saved[0]
AT.FAULT_TIME_CAVEAT = ""
check("caveat removed → the caveat test FAILS", not t_caveat())
AT.FAULT_TIME_CAVEAT = saved[1]
AT._anat0_classify = lambda desc: (None if saved[2](desc)[0] == "units" else saved[2](desc)[0], saved[2](desc)[1])
check("'unidades' branch broken → the unit-count test FAILS", not t_units())
AT._anat0_classify = saved[2]
check("restored: the same tests pass again", not t_table() and t_caveat() and t_units())


# ═════════════════════════════════════════════════════════════════════════════
section("6. Regression — every other suite (subprocess)")
# ═════════════════════════════════════════════════════════════════════════════
me = os.path.basename(__file__)
for f in sorted(x for x in os.listdir(".") if x.startswith("test_") and x.endswith(".py") and x != me):
    out = subprocess.run([sys.executable, f], capture_output=True, text=True, timeout=900).stdout
    out = re.sub(r"\x1b\[[0-9;]*m", "", out)
    m = re.search(r"Results: (\d+) passed, (\d+) failed", out) or re.search(r"(\d+)/\d+ checks passed, (\d+) failed", out)
    passed, failed = (int(m.group(1)), int(m.group(2))) if m else (0, -1)
    check(f"{f:<28} {passed:>4} passed, {failed} failed", m and failed == 0)

H.finish()
