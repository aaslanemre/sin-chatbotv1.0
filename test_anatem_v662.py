"""
v6.6.2 — ANATEM fixes from Thomas's feedback (sessions of 11–12 Nov):
Part 1 no invented ANATEM code in free answers (REGRA ANATEM in study_context + output
filter), Part 2 typed text inside the flow (pasted ANAT0 error, DMAQ path question,
'CDU … não está no DMAQ', 4+ words → free chat), Part 3 flow texts (AT3 error, DARQ by
columns, GOV/AVR/PSS, AT10B), Part 4 events (card names, manual link, 'Outro', no fault
times). Real app (runpy) on the shared harness; only the LLM chain is faked.

Run from repo root:  python3 test_anatem_v662.py
"""
import copy
import logging
import re

import _harness_v650 as H
from _harness_v650 import (ss, EV, svc, check, section, fresh, run, events,
                           last_assistant, assistants, StreamChain, scores)
from agents import anatem_flow as AT
from agents import anatem_guard as AG
from agents import session_analysis as SA
from agents import structured_input as SI
from config.version import APP_VERSION, RELEASE_NOTES

H.st.warning = lambda body="", **kw: EV.append(("warning", body))

AT5D = {"base": "ONS", "sav_name": "caso_estudo.sav", "case_number": "5", "dmaq_name": "DMAQ_.DAT"}
AT9D = dict(AT5D, cdu_return="AT8")
SMALL = {"base": "PEQUENO", "sav_name": "rede.sav", "case_number": "1", "gen_buses": ["10"]}

THOMAS_PASTE = (
    "(Nb ) Gr Co ( Nome ) Umn Umx (Pbas)(Qbas)(Pmin)(Pmax)(Qmin)(Qmax)(Rtrf)(Xtrf)(%)\n"
    " 524 10 0 BARIR2UH 0 1 45.6 23.0 15.0 45.6 -23.0 23.0 .000 .000 0\n"
    " Potencia gerada (13.0 MW) inferior ao minimo (15.0 MW).\n"
    " *** ERRO - ANAT01-190 ***"
)
THOMAS_AT5 = ("O arquivo DMAQ_.DAT foi salvo na pasta ANAT0, eu identifiquei a linha "
              "' DAT .\\BDados\\DMAQ_PAR2030.dat' no STB como faço para configurar adequadamente o "
              "arquivo dmaq_")
THOMAS_AT9 = ("Durante a simulação no ANATEM, ocorreu um erro de inicialização no CDU 1042. No entanto, "
              "não encontrei esse CDU no arquivo DMAQ...")
# v6.6.3: description quoted back, 'geração ativa', and the tail with the confirmed save path
FIX_190 = ("Erro **ANAT01-190** na barra **524 (BARIR2UH)**.\n\nDescrição lida:\n"
           "> Potencia gerada (13.0 MW) inferior ao minimo (15.0 MW).\n\n"
           "A potência gerada (**13.0 MW**) está abaixo do mínimo das máquinas (**15.0 MW**). No ANAREDE, "
           "aumente a geração ativa da barra 524 para pelo menos **15.0 MW** (ou ajuste o despacho das "
           "máquinas).\n\nDepois: rode o fluxo de potência, confira se convergiu, salve o .SAV "
           "(**Histórico > Operações > Salvar**) e execute o ANAT0 novamente.")
UNMATCHED_LONG = "Onde fica essa janela de mensagens no programa"   # 8 words, matches no answer

# Shaped like the bad free answers of 11–12 Nov (invented card syntax).
BAD_ANSWER = (
    "Para declarar os arquivos, use o cartão DARQ no .stb. O cartão ABCI abre um circuito.\n"
    "```\n"
    "DARQ\n"
    "SAV 5 caso_estudo.sav\n"
    "999999\n"
    "```\n"
    "Exemplo do arquivo devt.ctg:\n"
    "CONT 1\n"
    "TEMPO 0.1 ABRE 10 20\n"
    "ABCI 1000 2000 1 0.1\n"
    "DCDU 1 C:\\ANATEM\\bess.cdu\n"
    "- DARQ SAV 5 caso.sav\n"
    "DARQ\n"
    "ABCI é o cartão de abertura de circuito; confira os campos no manual.\n"
)
DBAR_BLOCK = ("```\nDBAR\n(Num)OETGb(   nome   )Gl( V)( A)( Pg)( Qg)( Qn)( Qm)(Bc  )( Pl)( Ql)\n"
              " 9001 L1 1BESS-9001    1000  0.  80.\n99999\n```")


# ── helpers ───────────────────────────────────────────────────────────────────

def chain(chunks=("Resposta livre.",)):
    return StreamChain(list(chunks), scores(("manual_anatem.pdf", 0.8)))


def at_state(step, data=None, ch=None):
    d = {"sim_type": "ANATEM"}
    d.update(copy.deepcopy(data or {}))
    fresh(ch or chain(), step=step, data=d, status="active")
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


def ctx(ch):
    return (ch.last_inputs or {}).get("study_context", "")


def option_buttons():
    return [e for e in events("button") if e[2] and e[2].startswith("opt_")]


def option_texts():
    return [e[4][0][0] for e in option_buttons()]


def click(text):
    b = next(e for e in option_buttons() if e[4][0][0] == text or e[1] == text)
    b[3](*b[4])
    run()


def strip_md(t):
    return t.replace("**", "")


# ═════════════════════════════════════════════════════════════════════════════
section("1. 2a — ANAT0 error pasted at AT3")
# ═════════════════════════════════════════════════════════════════════════════
err = AT.parse_anat0_error(THOMAS_PASTE)
check("parser: code ANAT01-190, bus 524, group 10, name BARIR2UH, X=13.0, Y=15.0",
      err == {"code": "ANAT01-190", "bus": "524", "group": "10", "name": "BARIR2UH",
              "gen": "13.0", "min": "15.0"}, err)


def t_190():
    ch = chain()
    at_state("AT3", AT5D, ch)
    click(AT.T_RAN_ERR)
    run(THOMAS_PASTE)
    return (step() == "AT3" and reply().startswith(FIX_190) and reply().endswith("**O ANAT0 rodou sem erros?**")
            and not llm_called(ch) and set(option_texts()) == {AT.T_RAN_OK, AT.T_RAN_ERR}
            and last_assistant().get("deterministic"))


check("Thomas's paste → exact fix text, then 'O ANAT0 rodou sem erros?' with the usual buttons, no LLM",
      t_190(), reply())
ch = chain()
at_state("AT3", AT5D, ch)
run(THOMAS_PASTE + "\nO que significa isso?")
check("…also when the paste ends with a question ('?' routing does not win)",
      reply().startswith(FIX_190) and not llm_called(ch))
at_state("AT3", AT5D)
run("Potência gerada (13,0 MW) inferior ao mínimo (15,0 MW).\n*** ERRO - ANAT01-190 ***")
r = reply()
check("accents + decimal comma accepted; without the '(Nb' header → no bus shown",
      r.startswith("Erro **ANAT01-190**.") and "A potência gerada (**13,0 MW**)" in r and "na barra **" not in r
      and "aumente a geração ativa da barra indicada no erro para pelo menos **15,0 MW**" in r, r)
at_state("AT3", AT5D)
run("*** ERRO - ANAT01-999 ***")
r = reply()
check("unknown code ANAT01-999, no description → code + 'Não reconheci' + generic procedure (no invented meaning)",
      r == (f"Erro **ANAT01-999**.\n\nNão encontrei a descrição do erro no trecho colado.\n\n"
            f"Não reconheci o tipo desse erro.\n\n**Como corrigir:**\n{AT._AT3_FIX_STEPS}\n\n{AT._ANAT0_TAIL}"
            "\n\n**O ANAT0 rodou sem erros?**")
      and step() == "AT3", r)
run(THOMAS_PASTE.replace("ANAT01-190", "ANAT01-123"))
check("v6.6.3: other code, same description → read by the description (code is only a label)",
      reply().startswith("Erro **ANAT01-123** na barra **524 (BARIR2UH)**.")
      and "pelo menos **15.0 MW**" in reply())
at_state("AT3", AT5D)
run("deu erro de novo")
check("an error report WITHOUT '*** ERRO - ANAT01-' still gets the 'Deu erro' text", reply().startswith("**Erro no ANAT0.**"))


# ═════════════════════════════════════════════════════════════════════════════
section("2. 2b — question about the DMAQ path at AT5")
# ═════════════════════════════════════════════════════════════════════════════
DAT_ANSWER = (
    "No cartão **DARQ**, procure a linha cujo tipo de arquivo (primeira coluna) é **DAT** e que aponta para o "
    "arquivo DMAQ original da base (por exemplo, um arquivo DMAQ_xxx.dat dentro da pasta da base). Troque o "
    "caminho dessa linha pelo caminho do novo arquivo gerado pelo ANAT0 (**DMAQ_.DAT**), incluindo a pasta "
    "onde ele foi salvo (por exemplo, a pasta ANAT0).\n\nResponda **Configurado** quando terminar.")
for label, text in (("Thomas's question", THOMAS_AT5), ("…ending with '?'", THOMAS_AT5 + "?"),
                    ("'qual o caminho do dmaq?'", "qual o caminho do dmaq?")):
    ch = chain()
    at_state("AT5", AT5D, ch)
    run(text)
    check(f"{label} → deterministic DAT answer, stays at AT5, no LLM",
          reply() == DAT_ANSWER and step() == "AT5" and not llm_called(ch), reply())
at_state("AT5", AT5D)
click(AT.T_CONFIGURED)
check("'Configurado' still advances to AT6", step() == "AT6")
at_state("AT5", AT5D)
run("Configurei o caminho do DMAQ")
check("'Configurei o caminho do DMAQ' (done, not a question) advances to AT6", step() == "AT6")


# ═════════════════════════════════════════════════════════════════════════════
section("3. 2c — 'CDU … não está no DMAQ' typed at AT9")
# ═════════════════════════════════════════════════════════════════════════════
def t_2c():
    ch = chain()
    at_state("AT9", AT9D, ch)
    run(THOMAS_AT9)
    r = "\n".join(m["content"] for m in assistants()[-1:])
    return (not llm_called(ch) and "CDU **1042**" in r and "**DFNT**" in r and "**DCNV**" in r
            and "**DCNE**" in r and step() == "AT8")


check("Thomas's AT9 text → CDU 1042 stored, DFNT/DCNV/DCNE branch, back at AT8, no LLM", t_2c(), reply())
ch = chain()
at_state("AT9", dict(AT9D, cdu={"number": "77"}), ch)
run("O CDU 1042 está no DMAQ, é de máquina síncrona?")
check("'CDU 1042 está no DMAQ / máquina síncrona' → DMAQ branch (Passo A with 1042), no LLM",
      step() == "AT9" and data()["cdu"] == {"number": "1042", "where": "dmaq"} and "**1042**" in reply()
      and "Passo A" in reply() and not llm_called(ch))
check("…Passo C offers GOV / AVR / PSS", option_texts() == [AT.T_GOV, AT.T_AVR, AT.T_PSS])
at_state("AT9", dict(AT9D, cdu={"number": "55"}))
click(AT.T_NOT_DMAQ)
check("the 'Não está no DMAQ' button still works", step() == "AT8" and "CDU **55**" in "\n".join(
    m["content"] for m in assistants()[-1:]))


# ═════════════════════════════════════════════════════════════════════════════
section("4. 2d — unmatched typed text at button steps")
# ═════════════════════════════════════════════════════════════════════════════
CASES = [("AT5", AT5D), ("AT6", AT5D), ("AT8", AT5D), ("AT10", AT5D), ("AT10B", dict(AT5D, ctrl_return="AT10")),
         ("AT3", AT5D), ("AT7", AT5D), ("ATS3", SMALL), ("ATS4", SMALL)]
bad = []
for s_, d_ in CASES:
    ch = chain()
    at_state(s_, d_, ch)
    before = len(assistants())
    run(UNMATCHED_LONG)
    r = reply()
    if not (llm_called(ch) and step() == s_ and AG.RULE in ctx(ch) and "↩️ Quando terminar" in r
            and r.startswith("Resposta livre.") and len(assistants()) == before + 1
            and not last_assistant().get("deterministic")):
        bad.append((s_, step(), r[:80]))
check("4+ unmatched words at AT5/AT6/AT8/AT10 (+AT3/AT7/AT10B/ATS3/ATS4) → LLM with REGRA ANATEM, step kept, nudge",
      not bad, bad)
bad = []
for s_, d_, head in [("AT5", AT5D, "Quando terminar os três ajustes"), ("AT8", AT5D, "Responda **Rodou sem erros**"),
                     ("AT10", AT5D, "Não identifiquei o resultado.")]:
    ch = chain()
    at_state(s_, d_, ch)
    run("talvez depois")
    if llm_called(ch) or step() != s_ or not reply().startswith(head):
        bad.append((s_, reply()[:60]))
check("2-word unmatched message → clarification as before (no LLM)", not bad, bad)
check("handle() contract: unmatched 4+ words → (same step, None)",
      AT.handle("AT5", dict(AT5D), UNMATCHED_LONG) == ("AT5", None)
      and AT.handle("AT7", dict(AT5D), "pronto")[0] == "AT8")


# ═════════════════════════════════════════════════════════════════════════════
section("5. Part 1 — REGRA ANATEM + output filter")
# ═════════════════════════════════════════════════════════════════════════════
yes = [("Como uso o cartão DARQ?", None), ("o que vai no .stb", "BESS"), ("Qual a função do ANAT0", None),
       ("qualquer coisa", "ANATEM"), ("Abrir o PLOTCEPEL", None), ("erro no cdu 10", None),
       ("sintaxe do ábci", None), ("DMAQ", None), ("como usar mdlq", None)]
no = [("Como inserir um BESS no ANAREDE?", "BESS"), ("O que é o DBAR?", None),
      ("estabilidade de tensão no SIN", None), ("cdus", None), ("", "STATCOM")]
check("is_anatem_context: true cases", all(AG.is_anatem_context(t, s) for t, s in yes),
      [t for t, s in yes if not AG.is_anatem_context(t, s)])
check("is_anatem_context: false cases", not any(AG.is_anatem_context(t, s) for t, s in no),
      [t for t, s in no if AG.is_anatem_context(t, s)])

before_hits = dict(AG.FILTER_HITS)
logs = []


class _Cap(logging.Handler):
    def emit(self, record):
        logs.append(record.getMessage())


logging.getLogger("agents.anatem_guard").addHandler(_Cap())
out, n = AG.filter_answer(BAD_ANSWER)


def t_filter(out_, n_):
    lines = out_.splitlines()
    return (n_ > 0 and "```" not in out_
            and not any(re.match(r"\s*(?:- )?(DARQ|ABCI|DCDU|CONT|TEMPO|SAV|999999)(\s+[-\d.A-Z\\/]|\s*$)", ln)
                        for ln in lines)
            and "O cartão ABCI abre um circuito." in out_
            and "ABCI é o cartão de abertura de circuito; confira os campos no manual." in out_
            and "use o cartão DARQ no .stb" in out_
            and out_.count(AG.FILTER_NOTE) == 1 and out_.endswith(AG.FILTER_NOTE))


check("filter removes fenced blocks + card-record lines (DARQ, ABCI 1000 2000 1 0.1, CONT, TEMPO, DCDU path, "
      "'- DARQ SAV 5 caso.sav'), keeps prose naming ABCI/DARQ, appends the note once", t_filter(out, n), out)
check("filter is idempotent (note never duplicated)", AG.filter_answer(out) == (out, 0))
check("filter hits counted + log line 'anatem_code_filter removed=N'",
      AG.FILTER_HITS["answers"] == before_hits["answers"] + 1 and f"anatem_code_filter removed={n}" in logs, logs)
check("clean prose → untouched, no note", AG.filter_answer("O DARQ declara os arquivos.\nUse o manual.")
      == ("O DARQ declara os arquivos.\nUse o manual.", 0))
check("ANAREDE DBAR fenced block → unchanged by the filter", AG.filter_answer(DBAR_BLOCK) == (DBAR_BLOCK, 0))
chunks = [BAD_ANSWER[i:i + 7] for i in range(0, len(BAD_ANSWER), 7)]
streamed = "".join(AG.filter_stream(iter(chunks)))
check("stream filter: no fenced block / record line ever shown while streaming",
      "```" not in streamed and "ABCI 1000" not in streamed and "CONT 1" not in streamed
      and "O cartão ABCI abre um circuito." in streamed)

# in the app: free question at an ANATEM step
ch = chain([BAD_ANSWER[:40], BAD_ANSWER[40:]])
at_state("AT5", AT5D, ch)
run("Como é a sintaxe do DARQ? Me dê um exemplo.")
stored = reply()
check("app: free question at AT5 → REGRA ANATEM in study_context (system prompt untouched)",
      AG.RULE in ctx(ch) and "REGRA ANATEM" not in open("prompts/system_prompt.py", encoding="utf-8").read())
check("app: stored answer filtered (no ``` / record lines, note once) + ↩️ nudge after it",
      "```" not in stored and "ABCI 1000 2000" not in stored and stored.count(AG.FILTER_NOTE) == 1
      and "↩️ Quando terminar, responda sobre **a edição do .stb**" in stored, stored)
check("app: streamed text filtered too", all("```" not in e[1] for e in events("stream")))
ch = chain(["Veja:\n", DBAR_BLOCK])
fresh(ch); run(); run("Como escrevo o DBAR de uma barra PV no ANAREDE?")
check("app: ANAREDE free question → no REGRA ANATEM, DBAR block unchanged",
      AG.RULE not in ctx(ch) and DBAR_BLOCK in reply())
ch = chain(["Veja:\n", DBAR_BLOCK])
fresh(ch); run(); run("Como passo esse DBAR para o ANATEM depois?")
check("app: ANATEM-context question whose answer is an ANAREDE DBAR block → block kept",
      AG.RULE in ctx(ch) and DBAR_BLOCK in reply())
ch = chain(["Veja:\n```\nDARQ\n```"])
fresh(ch); run(); run("O que é o DARQ do ANATEM?")
check("app: IDLE question naming DARQ → rule + filter even outside the flow",
      AG.RULE in ctx(ch) and "```" not in reply() and AG.FILTER_NOTE in reply())

calls = []
_orig_filter = AG.filter_answer
AG.filter_answer = lambda t: (calls.append(t), _orig_filter(t))[1]
at_state("AT10", AT5D)
click(AT.T_VARYING)
fresh(chain(), step="STEP8", data={"sim_type": "BESS", "db": "ONS", "years": [2028], "year_idx": 0,
                                   "year": 2028, "scenario": "Inverno Máxima Diurna", "bess_bus": "1001",
                                   "bess_mode": "PV", "bess_mva": "100"}, status="active")
run(); run("80"); run("9001"); run("não")
bess_out = reply()
AG.filter_answer = _orig_filter
check("filter never runs on deterministic flow messages (ANATEM step, BESS DBAR output)",
      calls == [] and "DBAR" in bess_out, bess_out[:200])
check("…and the BESS DBAR block itself would pass the filter unchanged",
      all(AG.filter_answer(b)[1] == 0 for b in re.findall(r"```.*?```", bess_out, re.S)))


# ═════════════════════════════════════════════════════════════════════════════
section("6. Part 3 — flow texts (3a, 3b, 3c, 3d)")
# ═════════════════════════════════════════════════════════════════════════════
at_state("AT3", AT5D)
click(AT.T_RAN_ERR)
m = last_assistant()["content"]
check("3a: 'Deu erro' → Thomas's 6 steps + paste invitation + question; no 'Volte ao ANAREDE'",
      all(x in m for x in ["**Erro no ANAT0.** Como corrigir:",
                           "1. Abra o **relatório de execução da Etapa 1** do ANAT0.",
                           "2. Use **Localizar (Ctrl+F)** e busque a palavra **Erro**. Pode haver um ou mais erros.",
                           "3. Analise cada erro e corrija alterando o **despacho das máquinas** ou ajustando melhor o caso.",
                           "4. Rode o **fluxo de potência** novamente e confira se está **convergido**.",
                           "5. Salve o **.SAV**.", "6. Execute o **ANAT0** novamente.",
                           "Se quiser, cole aqui o trecho do erro que eu te ajudo a interpretar.",
                           "**O ANAT0 rodou sem erros?**"])
      and "Volte ao ANAREDE" not in m and "volte ao ANAREDE" not in m, m)
check("3a: 'Detalhes' keeps why the ANAT0 fails", "capacidade das máquinas cadastradas" in m.split("Detalhes")[-1]
      or "capacidade das máquinas cadastradas" in m)
q5 = AT.question("AT5", AT5D)
check("3b: AT5 items 1–2 by columns (SAV line; 2nd column case; 3rd column file with path)",
      "identifique a linha cujo tipo de arquivo (primeira coluna) é **SAV**" in q5
      and "A segunda coluna é o **número do caso** e a terceira é o **nome do arquivo com o caminho**" in q5
      and "Altere a **terceira coluna** para o seu arquivo .SAV (**caso_estudo.sav**)" in q5
      and "altere a **segunda coluna** para o número do caso convergido no ANAREDE e processado no ANAT0 (**5**)" in q5
      and "é **DAT**" in q5 and "(**DMAQ_.DAT**)" in q5, q5)
ats2 = AT._ats2_done(dict(SMALL))
check("3b: ATS2 same column wording, without the ANAT0",
      "primeira coluna) é **SAV**" in ats2 and "altere a **segunda coluna**" in ats2 and "ANAT0" not in ats2, ats2)


def t_ctrl_buttons():
    at_state("AT9", dict(AT9D, cdu={"number": "7", "where": "dmaq"}))
    return option_texts() == [AT.T_GOV, AT.T_AVR, AT.T_PSS]


check("3c: Passo C has three buttons GOV / AVR / PSS", t_ctrl_buttons(), option_texts())
bad = []
for btn, advice in ((AT.T_GOV, AT._GOV_ADVICE), (AT.T_AVR, AT._AVR_ADVICE), (AT.T_PSS, AT._PSS_ADVICE)):
    at_state("AT9", dict(AT9D, cdu={"number": "7", "where": "dmaq"}))
    click(btn)
    if not (advice in "\n".join(m["content"] for m in assistants()[-1:]) and step() == "AT8"):
        bad.append(btn)
check("3c: each button → its advice, back to AT8", not bad, bad)
check("3c: AVR and PSS share the voltage/reactive advice; GOV = active power",
      "tensão/reativo" in AT._AVR_ADVICE and "tensão/reativo" in AT._PSS_ADVICE and "potência ativa" in AT._GOV_ADVICE)
check("3c: text fallbacks gov/velocidade/avr/tensão/pss/estabilizador",
      [AT.parse_ctrl(t) for t in ("gov", "velocidade", "avr", "tensão", "pss", "estabilizador",
                                  "Regulador de tensão (AVR) ou PSS")]
      == ["gov", "gov", "avr", "avr", "pss", "pss", "avr"])
src = open("agents/anatem_flow.py", encoding="utf-8").read()
check("3c: PSS advice marked 'PENDING REVIEW: PSS-specific advice in v6.6.3'",
      "# PENDING REVIEW: PSS-specific advice in v6.6.3\n_PSS_ADVICE" in src)


def to_at10b(start="AT10", d=AT5D):
    at_state(start, d)
    click(AT.T_VARYING)
    click(AT.T_LARGE_OSC)


to_at10b()
m = reply()
check("3d: AT10 'Oscilação maior' → AT10B with Thomas's text + 2 buttons",
      step() == "AT10B" and m.startswith("Oscilações maiores que 0,001 pu não são efeito numérico.")
      and "**avisos de controles atuando**" in m and "**chaveamento de bancos de reatores/capacitores dos elos HVDC**" in m
      and "**adiantando a manobra**" in m and m.endswith("Encontrou algum controle atuando?")
      and option_texts() == [AT.T_CTRL_ADJUSTED, AT.T_NO_CTRL], m)
click(AT.T_CTRL_ADJUSTED)
check("3d: [Sim, ajustei…] → AT8 with the menu/F5 text", step() == "AT8" and "**F5**" in reply()
      and "Simulação > Executar" in reply())
to_at10b()
click(AT.T_NO_CTRL)
check("3d: [Não há controle atuando] → AT9 (CDU path, returns to AT8)",
      step() == "AT9" and data().get("cdu_return") == "AT8" and "CDU" in reply())
to_at10b("ATS4", SMALL)
check("3d: small case ATS4 'Oscilação maior' → AT10B", step() == "AT10B" and data().get("ctrl_return") == "ATS4")
click(AT.T_CTRL_ADJUSTED)
check("3d: small case [Sim, ajustei…] → ATS4 (run again)", step() == "ATS4")
to_at10b("ATS4", SMALL)
click(AT.T_NO_CTRL)
check("3d: small case [Não há controle] → AT9 returning to ATS4", step() == "AT9" and data().get("cdu_return") == "ATS4")
to_at10b()
run("sim"); check("3d: typed 'sim' → AT8", step() == "AT8")
to_at10b()
run("não"); check("3d: typed 'não' → AT9", step() == "AT9")

to_at10b()
SCRIPT = H.SCRIPT
SCRIPT["press"] = {"⏸️ Pausar simulação"}; run(); SCRIPT["press"] = set()
ps = svc.load_paused_state("userA")
check("AT10B: pause persists the step and ctrl_return", ss["sim_status"] == "paused" and ps
      and ps["sim_step"] == "AT10B" and ps["sim_data"].get("ctrl_return") == "AT10")
run("retomar")
check("AT10B: 'retomar' repeats the AT10B question", ss["sim_status"] == "active" and step() == "AT10B"
      and "Encontrou algum controle atuando?" in reply())
run("voltar")
check("AT10B: 'voltar' → AT10", step() == "AT10" and "Voltando um passo" in reply())
to_at10b("ATS4", SMALL)
run("voltar")
check("AT10B (small case): 'voltar' → ATS4", step() == "ATS4")
check("AT10B registered: labels, nudge, admin label/sort, controls, all steps",
      AT.STEP_LABELS.get("AT10B") and AT.NUDGE_LABELS.get("AT10B") and "AT10B" in AT.ALL_STEPS
      and SA.step_label("AT10B") == "AT10B (controles atuando)"
      and sorted(["AT11", "AT10B", "AT10"], key=SA._step_sort_key) == ["AT10", "AT10B", "AT11"]
      and SA.infer_sim_type("AT10B") == "ANATEM"
      and SI.controls_for("AT10B", {"sim_type": "ANATEM"}))
a = SA.analyze_session([{"role": "user", "message": "x", "sim_step": "AT10"},
                        {"role": "user", "message": "y", "sim_step": "AT10B"},
                        {"role": "user", "message": "z", "sim_step": "AT8"}])
check("admin timeline shows AT10B", "AT10B (controles atuando)" in SA.timeline_text(a), SA.timeline_text(a))
to_at10b()
run("ajuda")
check("'ajuda' at AT10B: help, step kept", step() == "AT10B" and "Ajuda — ANATEM 10B: Controles atuando" in reply())


# ═════════════════════════════════════════════════════════════════════════════
section("7. Part 4 — events (4a, 4b, 4c)")
# ═════════════════════════════════════════════════════════════════════════════
EXPECTED_HEAD = {"Curto-circuito": "**Curto-circuito** — cartões do DEVT: **APCB, APCC, APCL**",
                 "Perda de linha de transmissão": "**Perda de linha de transmissão** — cartão do DEVT: **ABCI**",
                 "Desligamento de unidade geradora": "**Desligamento de unidade geradora** — cartão do DEVT: **RMGR**",
                 "Rejeição de carga": "**Rejeição de carga** — cartões do DEVT: **MDLP, MDLQ**"}
bad = []
FIRST_ANSWER = {"Curto-circuito": "500", "Perda de linha de transmissão": AT.T_NO_PRIOR_FAULT}   # v6.6.3
for label, head in EXPECTED_HEAD.items():
    at_state("AT11", AT5D)
    click(label)
    r = reply()
    if label in FIRST_ANSWER:
        click(FIRST_ANSWER[label])
        r += "\n" + reply()
    if not (r.startswith(head + "\n") and AG.MANUAL_URL in r and "```" not in r and "Para esse evento, defina:" in r):
        bad.append((label, r[:90]))
check("4a: card name(s) on the first line + 'defina' reminder + manual link, per event", not bad, bad)
at_state("AT11", AT5D)
check("4b: 5th button 'Outro / descrever o que quero analisar' (before Encerrar)",
      option_texts() == AT.EVENT_LABELS + [AT.T_OTHER_EVENT, AT.T_END] and "5. **Outro / descrever" in reply())
click(AT.T_OTHER_EVENT)
check("4b: 'Outro' → asks to describe, typing only (no buttons)",
      data().get("event_other") and "Descreva" in reply() and option_texts() == [])
ch = chain(["Para isso, um evento de abertura de linha (cartão ABCI) é o mais indicado."])
ss["chain"] = ch
note = "Quero ver como a usina de Itaipu reage quando perde a interligação?"
run(note)
r = reply()
check("4b: description → free chat with REGRA ANATEM + 'Outro' instruction; tail with the 3 options",
      llm_called(ch) and AG.RULE in ctx(ch) and AG.OTHER_EVENT_RULE in ctx(ch)
      and r.endswith(AT.OTHER_EVENT_TAIL) and "↩️" not in r
      and option_texts() == [AT.T_EVENT_DONE, AT.T_ADD_EVENT, AT.T_END], r)
click(AT.T_EVENT_DONE)
check("4b: 'Evento inserido' stores {'type': 'Outro', 'note': <user text>}",
      data().get("events") == [{"type": "Outro", "note": note}] and step() == "AT11", data().get("events"))
click(AT.T_ADD_EVENT); click(AT.T_OTHER_EVENT)
ss["chain"] = chain()
run("perda de carga grande no Nordeste")
click(AT.T_END)
click(AT.T_CRIT_SKIP)   # v6.6.3: AT12
check("4b: 'Encerrar' after an answered 'Outro' keeps it in the closing summary",
      step() == "IDLE" and "  - Outro — perda de carga grande no Nordeste" in reply(), reply())
at_state("ATS5", SMALL)
run("5")
check("4b: '5' at ATS5 → 'Outro' too", data().get("event_other") is True)

for q in ("Qual o tempo de eliminação do defeito?", "quanto tempo dura o curto", "Que instante de abertura devo usar?"):
    ch = chain()
    at_state("AT11", AT5D, ch)
    click("Curto-circuito")
    run(q)
    check(f"4c → v6.6.3 (3f): '{q}' → the voltage question, no numbers, no LLM",
          reply() == AT.KV_QUESTION and not llm_called(ch) and step() == "AT11"
          and data().get("event_pending") == "Curto-circuito")


def anatem_texts():
    subs = [{}, {"anat0_error": True}, {"osc_pending": True}, {"event_other": True},
            {"event_pending": "Outro", "event_note": "n"}] + [{"event_pending": l} for l in AT.EVENT_LABELS]
    out = []
    for s_ in AT.ALL_STEPS:
        for sub in subs:
            d = dict(AT5D, **sub)
            out += [AT.question(s_, d), AT._entry(s_, copy.deepcopy(d))]
    out += [AT.at3_error_message(), AT.anat0_error_reply(AT.parse_anat0_errors(THOMAS_PASTE)), AT.KV_QUESTION,
            AT.OTHER_EVENT_TAIL, AT.at5_dmaq_answer(AT5D), AG.RULE, AG.OTHER_EVENT_RULE, AG.FILTER_NOTE]
    return out


# v6.6.3: fault times now come only from Tabela 2 AFTER a voltage answer (test_anatem_v663.py);
# the step texts themselves still carry no clearing time.
fault_nums = [t for t in anatem_texts() if re.search(r"\d+(?:[.,]\d+)?\s*(?:ms|ciclos?)\b", t)]
check("4c (v6.6.3): no fault clearing time in the ANATEM step texts", not fault_nums,
      [t[:80] for t in fault_nums])


# ═════════════════════════════════════════════════════════════════════════════
section("8. Version, release notes, PENDING REVIEW markers")
# ═════════════════════════════════════════════════════════════════════════════
notes = RELEASE_NOTES["v6.6.2"]
check("APP_VERSION v6.6.3; v6.6.2 DRAFT PT-BR notes kept (6 novidades, 5 o que testar)",
      APP_VERSION == "v6.6.3" and "DRAFT" in notes["status"] and len(notes["novidades"]) == 6
      and len(notes["o_que_testar"]) == 5)
gsrc = open("agents/anatem_guard.py", encoding="utf-8").read()
for name in ("RULE", "OTHER_EVENT_RULE", "FILTER_NOTE"):
    i = gsrc.index(f"\n{name} =")
    check(f"guard {name} marked PENDING REVIEW", "PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)" in gsrc[i - 200:i])
for name in ("_AT3_FIX_STEPS", "_AT3_ERROR_WHY", "def anat0_error_reply", "def _darq_sav_items", "def at5_dmaq_answer",
             "_AT10B_MAIN", "_OTHER_EVENT_ASK", "OTHER_EVENT_TAIL", "KV_QUESTION", "MANUAL_LINE"):
    i = src.index(name if name.startswith("def ") else f"\n{name} =")
    check(f"{name.replace('def ', '')} marked PENDING REVIEW",
          "PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)" in src[max(0, i - 400):i])


# ═════════════════════════════════════════════════════════════════════════════
section("9. The tests are not trivial: 190 parser broken, fences allowed, PSS button removed")
# ═════════════════════════════════════════════════════════════════════════════
saved = (AT._ANAT0_MW_RE, AG._FENCE_RE, SI.anatem_controls)   # v6.6.3: the MW-values regex
AT._ANAT0_MW_RE = re.compile(r"(?!x)x")
check("broken 190 parser → the 2a test FAILS", not t_190())
AT._ANAT0_MW_RE = saved[0]
AG._FENCE_RE = re.compile(r"(?!x)x")
check("fenced blocks re-allowed in the filter → the Part 1 filter test FAILS",
      not t_filter(*AG.filter_answer(BAD_ANSWER)))
AG._FENCE_RE = saved[1]
SI.anatem_controls = lambda s_, d_: [dict(c, options=[o for o in c.get("options", []) if o["text"] != AT.T_PSS])
                                     for c in saved[2](s_, d_)]
check("PSS button removed → the 3c button test FAILS", not t_ctrl_buttons())
SI.anatem_controls = saved[2]
check("restored: the same tests pass again",
      t_190() and t_filter(*AG.filter_answer(BAD_ANSWER)) and t_ctrl_buttons())

H.finish()
