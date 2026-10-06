"""
v6.5.0 PART A — streaming answers, message cleanup, PT-BR badges, deduplicated
sources, .pwf download, one-click feedback, release-notes banner.

Run from repo root:  python3 test_ux_v650.py
"""
import copy
import bcrypt

import _harness_v650 as H
from _harness_v650 import (ss, EV, SCRIPT, svc, check, section, fresh, run, events,
                           last_assistant, assistants, sim_state, rows, StreamChain, scores)
from agents import grounding as G
from agents import ux
from agents.pwf_agent import generate_dbar_block, generate_statcom_block, generate_contingency_block
from agents.network_builder import build_full_pwf
from config.version import APP_VERSION, RELEASE_NOTES

GUIDE = "Deseja que eu te guie pelo processo de simulação passo a passo?"
BADGES = set(G.BADGE_LABELS.values())


def idx(pred):
    return next((i for i, e in enumerate(EV) if pred(e)), None)


def final_slot_text():
    md = [e for e in EV if e[0] == "slot_md"]
    return md[-1][2] if md else None


# ═════════════════════════════════════════════════════════════════════════════
section("1. streaming: stored == shown, badge before stream, red disclosure, fallback")
# ═════════════════════════════════════════════════════════════════════════════
ch = StreamChain(["O STATCOM ", "é um dispositivo ", "FACTS."], scores(("manual.pdf", 0.81)))
fresh(ch); run(); run("O que é um STATCOM?")
m = last_assistant()
check("retrieval ran exactly once, generation streamed (no non-streaming call)",
      ch.retrieve_calls == 1 and ch.generate_calls == 0)
check("stream rendered with st.write_stream", events("stream") and "FACTS." in events("stream")[-1][1])
check("final shown text == stored message content", final_slot_text() == m["content"], (final_slot_text(), m["content"]))
i_badge = idx(lambda e: e[0] == "caption" and e[1] in BADGES)
i_stream = idx(lambda e: e[0] == "stream")
check("badge rendered BEFORE the stream starts", i_badge is not None and i_stream is not None and i_badge < i_stream)
check("green badge level/score stored", m["grounding_level"] == "green" and abs(m["grounding_score"] - 0.81) < 1e-9)
db_row = rows("SELECT * FROM chat_logs WHERE message_id = ?", (m["message_id"],))[0]
check("chat_logs row: same text, grounding level/score", db_row["message"] == m["content"]
      and db_row["grounding_level"] == "green" and abs(db_row["grounding_score"] - 0.81) < 1e-6, db_row)
check("chain history updated once with the raw answer",
      ch.remembered == [("O que é um STATCOM?", "O STATCOM é um dispositivo FACTS.")], ch.remembered)

ch = StreamChain(["Resposta geral."], scores(("x.pdf", 0.40)))
fresh(ch); run(); run("O que é a curva de capabilidade?")
m = last_assistant()
i_disc = idx(lambda e: e[0] == "markdown" and e[1].startswith(G.DISCLOSURE))
i_stream = idx(lambda e: e[0] == "stream")
check("red: disclosure shown first, then the streamed answer",
      i_disc is not None and i_stream is not None and i_disc < i_stream)
check("red: stored text starts with the disclosure and equals the shown text",
      m["content"].startswith(G.DISCLOSURE) and m["content"] == final_slot_text() and m["grounding_level"] == "red")

ch = StreamChain(["Texto ", "completo."], scores(("a.pdf", 0.8)), fail_stream=True)
fresh(ch); run(); run("O que é SIN?")
m = last_assistant()
check("stream error → non-streaming fallback (same retrieval, one search)",
      ch.generate_calls == 1 and ch.retrieve_calls == 1 and m["content"] == "Texto completo." == final_slot_text())
ch = StreamChain(["Parte 1. ", "Parte 2."], scores(("a.pdf", 0.8)), fail_after=1)
fresh(ch); run(); run("O que é SIN?")
m = last_assistant()
check("stream breaking mid-way → fallback answer is complete and stored",
      ch.generate_calls == 1 and m["content"] == "Parte 1. Parte 2." == final_slot_text(), m["content"])
check("fallback keeps the grounding badge and level", m.get("grounding_level") == "green")

ch = StreamChain(["Sou o Assistente SIN, desenvolvido pelo GESEL/UFRJ."], scores(("a.pdf", 0.3)))
fresh(ch); run(); run("Que tipo de assistente é você")
m = last_assistant()
check("meta reply detected after streaming: badge slot cleared, no grounding stored, no disclosure",
      events("slot_clear") and "grounding_level" not in m and G.DISCLOSURE not in m["content"])

ch = StreamChain(["Resposta."], scores(("a.pdf", 0.3)))
fresh(ch, step="STEP7", data={"sim_type": "BESS"}, status="active"); run(); run("o que é uma barra PQ?")
m = last_assistant()
check("mid-simulation: disclosure first, nudge last, state untouched",
      m["content"].startswith(G.DISCLOSURE) and m["content"].endswith("para continuar a simulação.")
      and ss["sim_step"] == "STEP7" and ss["sim_status"] == "active")


# ═════════════════════════════════════════════════════════════════════════════
section("2. 'Deseja que eu te guie…' never during a simulation; ≤1 per 5 otherwise")
# ═════════════════════════════════════════════════════════════════════════════
def guide_chain():
    return StreamChain(["O BESS armazena energia.", "\n\n", "Deseja que eu te ", "guie pelo processo de simulação passo a passo?"],
                       scores(("a.pdf", 0.8)))

for label, step, status in [("active", "STEP7", "active"), ("paused", "STEP8", "paused"),
                            ("NET active", "NET2_BUSES", "active")]:
    fresh(guide_chain(), step=step, data={"sim_type": "BESS" if not step.startswith("NET") else "NETWORK"}, status=status)
    run(); run("o que é um BESS?")
    m = last_assistant()
    streamed = events("stream")[-1][1] if events("stream") else ""
    check(f"{label}: not in stored text, not in shown text, not even while streaming",
          GUIDE not in m["content"] and "Deseja que eu" not in (final_slot_text() or "") and "Deseja que eu" not in streamed,
          (m["content"], streamed))

fresh(guide_chain()); run()
kept = []
for i in range(6):
    run(f"pergunta livre {i}?")
    kept.append(GUIDE in last_assistant()["content"])
check("no simulation: shown on 1st, removed on 2nd–5th, shown again on 6th", kept == [True, False, False, False, False, True], kept)
check("removed version ends cleanly (no dangling blank lines)",
      assistants()[1]["content"] == "O BESS armazena energia.", assistants()[1]["content"])

out = "".join(ux.filter_guide_stream(iter(["Texto.\n\nDes", "eja que eu te gu", "ie pelo processo de simulação passo a passo?"]), False))
check("stream filter: offer split across chunks never reaches the screen", "Deseja" not in out and out.startswith("Texto."), out)
out = "".join(ux.filter_guide_stream(iter(["Quer mais? ", "Deseja que eu explique melhor?", " Fim."]), False))
check("stream filter: other 'Deseja que eu …?' questions pass through", out == "Quer mais? Deseja que eu explique melhor? Fim.", out)
check("strip handles bold and inline variants",
      ux.strip_guide_offer("A.\n\n**Deseja que eu te guie pelo processo de simulação passo a passo?**") == "A."
      and ux.strip_guide_offer("A. Deseja que eu o guie pela simulação? B.") == "A. B.")
check("deterministic simulation messages never carry the offer",
      not any(GUIDE in (m.get("content") or "") for m in assistants()
              if m.get("deterministic")))


# ═════════════════════════════════════════════════════════════════════════════
section("3. SINTEGRE/EPE download block once per session")
# ═════════════════════════════════════════════════════════════════════════════
FULL = "Você pode ir baixando enquanto respondemos"
fresh(None); run()
run("quero simular um BESS")
first = last_assistant()["content"]
check("first intro: full block with both links", FULL in first and "ons.org.br" in first and "epe.gov.br" in first)
run("encerrar"); run("quero simular um STATCOM")
second = last_assistant()["content"]
check("second intro in the same session: one-line reminder (still links), no full block",
      FULL not in second and "Lembrete" in second and "ons.org.br" in second and "epe.gov.br" in second)
run("2"); run("2028")
run("quero simular")  # restart mid-flow
third = last_assistant()["content"]
check("restart mid-flow: reminder only", FULL not in third and "Lembrete" in third and ss["sim_step"] == "STEP1")
check("full block appears exactly once in the whole session",
      sum(FULL in m["content"] for m in assistants()) == 1)
fresh(None, step="STEP7", data={"sim_type": "BESS", "db": "ONS"}, status="active"); run()
run("quero simular")
check("restart as the FIRST intro of a session shows the full block", FULL in last_assistant()["content"])
fresh(None); run(); run("quero simular um BESS")
check("a new session shows the full block again", FULL in last_assistant()["content"])
check("openers removed: intro starts with the content",
      last_assistant()["content"].startswith("Vou te guiar") and "Ótimo!" not in last_assistant()["content"])
run("2")
check("STEP1 answer has no 'Ótimo' opener", "Ótimo" not in last_assistant()["content"]
      and last_assistant()["content"].startswith("Base selecionada"))
src = open("app.py", encoding="utf-8").read()
check("no 'Ótimo!'/'Perfeito!'/'Certo!' openers left in deterministic step messages",
      not any(w in src for w in ('"Ótimo!', '"Perfeito!', '"Certo!', 'f"Ótimo')))


# ═════════════════════════════════════════════════════════════════════════════
section("3b. secondary text in 'Detalhes'; question always visible")
# ═════════════════════════════════════════════════════════════════════════════
fresh(None, step="STEP6", data={"sim_type": "BESS", "db": "ONS"}, status="active"); run()
run("vou desenhar")
m = last_assistant()
check("STEP7 bus question visible, tip in details",
      "Qual é a barra onde deseja inserir o BESS?" in m["main"] and m["details"].startswith("Dica:"))
check("rendered: question in main markdown, details inside an expander 'Detalhes'",
      ("expander", "Detalhes") in EV and any(e[0] == "markdown" and "Qual é a barra" in e[1] for e in EV))
check("stored/logged text is the full plain text (no separator), main first",
      m["content"] == m["main"] + "\n\n" + m["details"] and ux.DETAILS_SEP not in m["content"]
      and rows("SELECT message FROM chat_logs WHERE message_id=?", (m["message_id"],))[0]["message"] == m["content"])
run("1001")
m = last_assistant()
check("mode question: both options visible, explanations in details",
      "1. **Controle de tensão (barra PV — tipo 1)**" in m["main"] and "2. **Despacho fixo" in m["main"]
      and "GFM" in m["details"] and "0.00001 pu" in m["details"])
check("state machine order unchanged (STEP6 → STEP7 → STEP7 mode)", ss["sim_step"] == "STEP7" and ss["sim_data"]["bess_bus"] == "1001")


# ═════════════════════════════════════════════════════════════════════════════
section("4. PT-BR badges, tooltip, stored level keys unchanged")
# ═════════════════════════════════════════════════════════════════════════════
check("labels", G.BADGE_LABELS == {"green": "🟢 Baseado nos documentos",
                                   "yellow": "🟡 Parcialmente baseado nos documentos",
                                   "red": "🔴 Conhecimento geral"})
for v, level in [(0.8, "green"), (0.7, "yellow"), (0.5, "red")]:
    fresh(StreamChain(["R."], scores(("a.pdf", v)))); run(); run("O que é X?")
    m = last_assistant()
    cap = [e for e in EV if e[0] == "caption" and e[1] == G.BADGE_LABELS[level]]
    db_lvl = rows("SELECT grounding_level FROM chat_logs WHERE message_id=?", (m["message_id"],))[0]["grounding_level"]
    check(f"{level}: PT-BR label with help tooltip; stored key '{level}' (message + chat_logs)",
          cap and cap[0][2] == G.BADGE_HELP and m["grounding_level"] == level and db_lvl == level)
    run()
    check(f"{level}: history replay shows the same label + tooltip",
          any(e[0] == "caption" and e[1] == G.BADGE_LABELS[level] and e[2] == G.BADGE_HELP for e in EV))
check("tooltip text", G.BADGE_HELP == "Indica a relevância dos documentos encontrados, não garante que a resposta esteja correta.")
admin_src = open("admin/panel.py", encoding="utf-8").read()
check("admin grounding table uses the PT-BR labels", "BADGE_LABELS.get(r[\"level\"]" in admin_src)


# ═════════════════════════════════════════════════════════════════════════════
section("5. sources deduplicated per file, best score, excerpts")
# ═════════════════════════════════════════════════════════════════════════════
items = [{"source": "docs/a.pdf", "score": 0.78, "excerpt": "x" * 500, "page": 7},
         {"source": "docs/b.pdf", "score": 0.76, "excerpt": "b1"},
         {"source": "docs/a.pdf", "score": 0.81, "excerpt": "a2", "page": 3},
         {"source": "a.pdf", "score": 0.70, "excerpt": "a3", "page": 3}]
g = ux.group_sources(items)
check("one entry per file, ordered by best score", [x["file"] for x in g] == ["a.pdf", "b.pdf"], g)
check("best score and excerpt count per file", (g[0]["best"], g[0]["count"], g[1]["best"], g[1]["count"]) == (0.81, 3, 0.76, 1))
check("pages listed once, sorted", g[0]["pages"] == [3, 7] and ux.source_label(g[0]) == "a.pdf — 0.81 · 3 trechos · p. 3, 7")
check("excerpts trimmed to ~200 chars", all(len(e) <= 200 for e in g[0]["excerpts"]) and len(g[0]["excerpts"]) == 3)
check("old items without excerpt/page still group", ux.group_sources([{"source": "z.pdf", "score": 0.7}])[0]["count"] == 1)
fresh(StreamChain(["R."], [{"source": "docs/a.pdf", "score": 0.80, "excerpt": "e1"},
                           {"source": "docs/a.pdf", "score": 0.77, "excerpt": "e2"},
                           {"source": "docs/b.pdf", "score": 0.76, "excerpt": "e3"}])); run(); run("O que é Y?")
exps = [e[1] for e in events("expander") if e[1] not in ("📖 Glossário", "📖 Termos desta mensagem")]
check("rendered: one expander per file with best score + count", exps == ["a.pdf — 0.80 · 2 trechos", "b.pdf — 0.76 · 1 trecho"], exps)
check("excerpts shown inside the file entries", any(e[0] == "caption" and "e2" in e[1] for e in EV))
fresh(StreamChain(["R."], scores(("a.pdf", 0.5), ("a.pdf", 0.4)))); run(); run("O que é Z?")
check("red: single panel with the best result below the limit",
      [e for e in events("expander") if e[1] not in ("📖 Glossário", "📖 Termos desta mensagem")] == [("expander", "📄 Fontes consultadas")]
      and any(e[0] == "caption" and "a.pdf** — 0.50" in e[1] for e in EV))


# ═════════════════════════════════════════════════════════════════════════════
section("6. .pwf download == code block text with CRLF (BESS, STATCOM, DCTG, NETWORK)")
# ═════════════════════════════════════════════════════════════════════════════
def code_blocks(text):
    return [m.group(1) for m in ux.FENCE_RE.finditer(text)]


def downloads():
    return [(e[2], e[3]) for e in events("download")]


bess_data = {"sim_type": "BESS", "db": "ONS", "years": [2028], "year_idx": 0, "year": 2028,
             "scenario": "Inverno Máxima Diurna", "bess_bus": "1001", "bess_mode": "PV",
             "bess_mva": "100", "bess_p_mw": "80"}
fresh(None, step="STEP8", data=bess_data, status="active"); run(); run("9999")
m = last_assistant()
expected = generate_dbar_block(bus_number="1001", bess_bus_number="9999", bus_type="1", S_mva=100.0, P_mw=80.0)
blocks = code_blocks(m["content"])
dl = downloads()
check("BESS: code block unchanged (generator output inside ``` fences)",
      blocks == [expected] and f"```\n{expected}\n```" in m["content"])
check("BESS: one download, BESS_modificacao.pwf, bytes == block with CRLF (ASCII)",
      dl == [("BESS_modificacao.pwf", expected.replace("\n", "\r\n").encode("ascii"))], dl[:1])
i_md = idx(lambda e: e[0] == "markdown" and e[1].startswith("```") and "DBAR" in e[1])
i_dl = idx(lambda e: e[0] == "download")
check("BESS: download button rendered right below the code block", i_md is not None and i_dl == i_md + 1)
check("BESS: label", events("download")[0][1] == "⬇️ Baixar arquivo .pwf")
run()
check("BESS: history replay renders the same download", downloads() == dl)

fresh(None, step="STATCOM_STEP_CBUS", data={"sim_type": "STATCOM", "statcom_bus": "1500",
                                            "statcom_q_min": -100.0, "statcom_q_max": 100.0}, status="active")
run(); run("1")
exp = generate_statcom_block(bus_number=1500, q_min=-100.0, q_max=100.0, controlled_bus=None)
check("STATCOM: STATCOM_modificacao.pwf == block with CRLF",
      downloads() == [("STATCOM_modificacao.pwf", exp.replace("\n", "\r\n").encode("ascii"))]
      and code_blocks(last_assistant()["content"]) == [exp])

fresh(None, step="STEP11B", data={"sim_type": "BESS", "contingency_stage": "guide"}, status="active")
run(); run("linha 1001-1002 circuito 1 e gerador barra 1005")
exp = generate_contingency_block([{"id": 1, "name": "LT 1001-1002", "type": "line", "bus_from": 1001, "bus_to": 1002, "circuit": 1},
                                  {"id": 2, "name": "GER 1005", "type": "generator", "bus": 1005}])
check("DCTG: DCTG_contingencias.pwf == block with CRLF",
      downloads() == [("DCTG_contingencias.pwf", exp.replace("\n", "\r\n").encode("ascii"))], downloads())

net = {"title": "Rede Teste 3 Barras", "base_mva": 100.0,
       "buses": [{"number": 1, "name": "REF", "kv": 230.0, "tipo": 2, "v_pu": 1.05, "angle_deg": 0.0, "p_gen_mw": 0.0,
                  "q_min_mvar": 0.0, "q_max_mvar": 0.0, "p_load_mw": 0.0, "q_load_mvar": 0.0},
                 {"number": 2, "name": "CARGA", "kv": 230.0, "tipo": 0, "v_pu": 1.0, "angle_deg": 0.0, "p_gen_mw": 0.0,
                  "q_min_mvar": 0.0, "q_max_mvar": 0.0, "p_load_mw": 100.0, "q_load_mvar": 30.0}],
       "lines": [{"id": 1, "from_bus": 1, "to_bus": 2, "circuit": 1, "r_pct": 0.5, "x_pct": 5.0, "q_mvar": 10.0}]}
fresh(None, step="NET4_REVIEW", data={"sim_type": "NETWORK", "network": copy.deepcopy(net)}, status="active")
run(); run("confirmar")
exp = build_full_pwf(net)
m = last_assistant()
check("NETWORK: file named from the case title, bytes == full PWF with CRLF",
      downloads() == [("rede_teste_3_barras.pwf", exp.replace("\n", "\r\n").encode("ascii"))] and code_blocks(m["content"]) == [exp])
check("NETWORK: save instruction names the same file", "rede_teste_3_barras.pwf" in m["content"])
run("voltar")
check("NETWORK: re-shown PWF (voltar) also downloadable with the same bytes",
      downloads()[-1] == ("rede_teste_3_barras.pwf", exp.replace("\n", "\r\n").encode("ascii")))

net2 = copy.deepcopy(net); net2["buses"][1]["name"] = "SÃO_JOSÉ"
fresh(None, step="NET4_REVIEW", data={"sim_type": "NETWORK", "network": net2}, status="active")
run(); run("confirmar")
exp = build_full_pwf(net2)
check("non-ASCII block: latin-1 bytes + caption reporting it",
      downloads() == [("rede_teste_3_barras.pwf", exp.replace("\n", "\r\n").encode("latin-1"))]
      and any(e[0] == "caption" and "latin-1" in e[1] for e in EV))
check("slug fallback", ux.slugify("") == "minha_rede" and ux.slugify("Meu Caso") == "meu_caso")
fresh(StreamChain(["Exemplo:\n```\nDBAR\n 1 ...\n99999\n```"], scores(("a.pdf", 0.8)))); run(); run("Como é o DBAR?")
check("LLM answers containing DBAR text get no download button", not events("download"))


# ═════════════════════════════════════════════════════════════════════════════
section("7. one-click 👍/👎: upsert, comment after 👎 on the same row, state untouched")
# ═════════════════════════════════════════════════════════════════════════════
fresh(None); run(); run("quero simular um BESS")
m = last_assistant(); mid = m["message_id"]
run()
fbs = [e for e in events("feedback")]
check("👍/👎 always visible under each assistant message, not under the welcome",
      len(fbs) == len(assistants()) and all(e[1].startswith("fb_thumbs_") for e in fbs)
      and not any(ss.messages[0].get("message_id") and ss.messages[0]["message_id"] in e[1] for e in fbs))
check("no comment box before any rating", not any(e[0] == "popover" for e in EV))
before, n_logs, n_msgs = sim_state(), len(rows("SELECT * FROM chat_logs")), len(ss.messages)
key = f"fb_thumbs_{mid}"
_, _, on_change, args = next(e for e in fbs if e[1] == key)
ss[key] = 0; on_change(*args)                     # click 👎
fb = rows("SELECT * FROM feedback WHERE message_id = ?", (mid,))
check("one click on 👎 records the rating immediately", len(fb) == 1 and fb[0]["rating"] == "down" and fb[0]["app_version"] == APP_VERSION)
run()
check("after 👎: optional category + comment box appears", ("popover", "✍️ Contar o que deu errado (opcional)") in EV)
SCRIPT["values"].update({f"fb_cat_{mid}": "passo", f"fb_comment_{mid}": "não entendi o passo"}); SCRIPT["submit"] = True
run(); SCRIPT["submit"] = False
fb = rows("SELECT * FROM feedback WHERE message_id = ?", (mid,))
check("saving the comment updates the SAME row", len(fb) == 1 and (fb[0]["rating"], fb[0]["category"], fb[0]["comment"]) == ("down", "passo", "não entendi o passo"), fb)
ss[key] = 1; on_change(*args)                     # change to 👍
fb = rows("SELECT * FROM feedback WHERE message_id = ?", (mid,))
check("switching to 👍 keeps one row and the comment already sent", len(fb) == 1 and fb[0]["rating"] == "up" and fb[0]["comment"] == "não entendi o passo")
ss[key] = None; on_change(*args)
check("un-selecting does not delete or change the stored rating", rows("SELECT rating FROM feedback WHERE message_id = ?", (mid,))[0]["rating"] == "up")
check("simulation state, messages and chat_logs untouched by feedback",
      sim_state() == before and len(ss.messages) == n_msgs and len(rows("SELECT * FROM chat_logs")) == n_logs)
check("one row per user per message overall", rows("SELECT COUNT(*) n FROM feedback WHERE message_id = ?", (mid,))[0]["n"] == 1)

_fb = H.st.feedback; del H.st.feedback               # older Streamlit: two small buttons
fresh(None); run(); run("quero simular um BESS"); m = last_assistant(); run()
btns = {e[2]: e for e in events("button") if e[2] and e[2].startswith("fb_")}
check("fallback: 👍 and 👎 buttons when st.feedback is unavailable",
      f"fb_up_{m['message_id']}" in btns and f"fb_down_{m['message_id']}" in btns)
e = btns[f"fb_down_{m['message_id']}"]; e[3](*e[4])
check("fallback 👎 click records immediately", rows("SELECT rating FROM feedback WHERE message_id = ?", (m["message_id"],))[0]["rating"] == "down")
H.st.feedback = _fb

fresh(None); run(); run("quero simular um BESS"); m = last_assistant(); run()
H.DB_FAIL["on"] = True
_, _, on_change, args = next(e for e in events("feedback") if m["message_id"] in e[1])
ss[f"fb_thumbs_{m['message_id']}"] = 1
try:
    on_change(*args); crashed = False
except Exception:
    crashed = True
H.DB_FAIL["on"] = False
check("DB failure: no exception, friendly toast, nothing marked as sent",
      not crashed and any(e[0] == "toast" and "Não foi possível" in e[1] for e in EV)
      and m["message_id"] not in ss["_feedback_cache"])


# ═════════════════════════════════════════════════════════════════════════════
section("8. 'Novidades da versão' banner once per version per user")
# ═════════════════════════════════════════════════════════════════════════════
notes = RELEASE_NOTES[APP_VERSION]
check("APP_VERSION v6.5.0 with PT-BR draft notes (novidades + o que testar), marked DRAFT",
      APP_VERSION == "v6.5.0" and notes["novidades"] and notes["o_que_testar"] and "DRAFT" in notes["status"])
pw = bcrypt.hashpw(b"segredo1", bcrypt.gensalt()).decode()
H.lite.execute("INSERT INTO users (id, email, password_hash, full_name) VALUES ('userN','n@t',?,'N')", (pw,)); H.lite.commit()
u = svc.login("n@t", "segredo1")
check("login returns last_seen_version (NULL for a user who never dismissed)", "last_seen_version" in u and u["last_seen_version"] is None)
fresh(None, user=u); run()
check("banner shown after login when last_seen_version != APP_VERSION",
      any(e[0] == "markdown" and f"Novidades da versão {APP_VERSION}" in e[1] for e in EV))
ok = next(e for e in events("button") if e[1] == "Entendi")
ok[3](*ok[4])
check("'Entendi' stores last_seen_version", rows("SELECT last_seen_version v FROM users WHERE id='userN'")[0]["v"] == APP_VERSION)
run()
check("banner gone on the next rerun", not any(e[0] == "markdown" and "Novidades da versão" in str(e[1]) for e in EV))
u2 = svc.login("n@t", "segredo1")
fresh(None, user=u2); run()
check("next login: no banner (same version)", not any(e[0] == "markdown" and "Novidades da versão" in str(e[1]) for e in EV))
fresh(None, user=dict(u2, last_seen_version="v6.4.1")); run()
check("user who saw an older version gets the banner", any(e[0] == "markdown" and "Novidades da versão" in str(e[1]) for e in EV))
H.DB_FAIL["on"] = True
ok = next(e for e in events("button") if e[1] == "Entendi"); ok[3](*ok[4])
H.DB_FAIL["on"] = False
run()
check("DB failure on 'Entendi': banner still hidden for the session, no crash",
      not any(e[0] == "markdown" and "Novidades da versão" in str(e[1]) for e in EV))

H.finish()
