"""
v6.5.1 COMMIT 4 — several BESS in one study (one file, one DBAR/DLIN block each).

Run from repo root:  python3 test_multi_bess_v651.py
"""
import copy
import re

import _harness_v650 as H
from _harness_v650 import ss, EV, check, section, fresh, run, events, last_assistant, sim_state, svc, SCRIPT
from agents.pwf_agent import generate_dbar_block, generate_bess_block
from utils.anarede_lib import COUPLING_LINE_X_PCT

LOADED = {"sim_type": "BESS", "db": "ONS", "years": [2028], "year_idx": 0, "year": 2028,
          "scenario": "Inverno Máxima Diurna"}


def setup(step, data):
    fresh(None, step=step, data=data, status="active")
    env = run()
    env["_append_system_assistant_message"](env["_current_step_question"]() or "Pergunta do passo.")
    run()
    return env


def option_buttons():
    return [e for e in events("button") if e[2] and e[2].startswith("opt_")]


def click_option(label):
    b = next(e for e in option_buttons() if e[1] == label)
    b[3](*b[4])
    run()


def enter_bess(bus, mode, mva, p, new_bus):
    """STEP7 (bus question) → STEP8 more-question, typing like a user."""
    run(bus); run(mode); run(f"{mva} MVA"); run(str(p)); run(str(new_bus))


def code_blocks(text):
    return re.findall(r"```\n(.*?)\n```", text, re.S)


def downloads():
    return [(e[2], e[3]) for e in events("download")]


def dev(bus, new, typ, s, p):
    return {"bus_number": str(bus), "bess_bus_number": str(new), "bus_type": typ, "S_mva": float(s), "P_mw": float(p)}


def section_lines(block, code):
    lines = block.splitlines()
    i = lines.index(code)
    out = []
    for ln in lines[i + 1:]:
        if ln == "99999":
            break
        if not ln.startswith("("):
            out.append(ln)
    return out


# ═════════════════════════════════════════════════════════════════════════════
section("1 BESS: same output as after COMMIT 1")
# ═════════════════════════════════════════════════════════════════════════════
setup("STEP7", LOADED)
enter_bess("1001", "1", 500, 417, 91000)
m = last_assistant()
check("after the new bus: 'Deseja inserir outra BESS neste estudo?' (still STEP8)",
      "**Deseja inserir outra BESS neste estudo?**" in m["content"] and ss["sim_step"] == "STEP8")
check("buttons 'Gerar arquivo agora' and 'Adicionar outra BESS'",
      [b[1] for b in option_buttons()] == ["Gerar arquivo agora", "Adicionar outra BESS"])
click_option("Gerar arquivo agora")
m = last_assistant()
single = generate_dbar_block(bus_number="1001", bess_bus_number="91000", bus_type="1", S_mva=500.0, P_mw=417.0)
check("STEP9 with the COMMIT 1 block (acceptance case)",
      ss["sim_step"] == "STEP9" and code_blocks(m["content"]) == [single], m["content"][:300])
check("message identical to the single-BESS message",
      m["content"].startswith("Barra da BESS: **91000** — Potência nominal: **500 MVA**.\n\n"
                              "Copie as linhas abaixo em um editor de texto")
      and "Confirme quando o caso estiver salvo." in m["content"])
check("DLIN line of the single BESS", " ".join(section_lines(single, "DLIN")[0].split())
      == "1001 A 91000 1L 0.0000 0.0001 0.0000")
check("one download, bytes == block with CRLF",
      downloads() == [("BESS_modificacao.pwf", single.replace("\n", "\r\n").encode("ascii"))])
check("generate_bess_block([one]) == generate_dbar_block(one)",
      generate_bess_block([dev(1001, 91000, "1", 500, 417)]) == single)

# typed answers work too
setup("STEP7", LOADED); enter_bess("1001", "1", 500, 417, 91000); run("gerar arquivo agora")
check("typed 'gerar arquivo agora' == button", ss["sim_step"] == "STEP9" and code_blocks(last_assistant()["content"]) == [single])
setup("STEP7", LOADED); enter_bess("1001", "1", 500, 417, 91000); run("não")
check("typed 'não' → generate", ss["sim_step"] == "STEP9")
setup("STEP7", LOADED); enter_bess("1001", "1", 500, 417, 91000); run("talvez")
check("unrecognised answer → asks again, state unchanged",
      ss["sim_step"] == "STEP8" and "Deseja inserir outra BESS" in last_assistant()["content"]
      and "bess_extra" not in ss["sim_data"])

# ═════════════════════════════════════════════════════════════════════════════
section("3 BESS at 3 buses → one file")
# ═════════════════════════════════════════════════════════════════════════════
setup("STEP7", LOADED)
enter_bess("1001", "1", 500, 417, 91000)
click_option("Adicionar outra BESS")
check("'Adicionar outra BESS' → STEP7 bus question for BESS 2",
      ss["sim_step"] == "STEP7" and "**BESS 2.**" in last_assistant()["content"]
      and len(ss["sim_data"]["bess_extra"]) == 1 and "bess_bus" not in ss["sim_data"])
enter_bess("1002", "2", 100, 80, 91001)
click_option("Adicionar outra BESS")
enter_bess("1003", "1", 200, 150, 91002)
snap3 = copy.deepcopy(dict(ss))
click_option("Gerar arquivo agora")
m = last_assistant()
exp3 = generate_bess_block([dev(1001, 91000, "1", 500, 417), dev(1002, 91001, "0", 100, 80),
                            dev(1003, 91002, "1", 200, 150)])
blocks = code_blocks(m["content"])
check("one code block with the 3 BESS", blocks == [exp3], blocks)
dbar, dlin = section_lines(exp3, "DBAR"), section_lines(exp3, "DLIN")
check("DBAR: 3 new buses, tipo PV=1 / PQ=0", [ln[:8] for ln in dbar] == ["91000AL1", "91001AL0", "91002AL1"], dbar)
check("DLIN: 3 coupling lines, existing → new bus, X = COUPLING_LINE_X_PCT, no TAP",
      [" ".join(ln.split()) for ln in dlin] == [f"{a} A {b} 1L 0.0000 0.0001 0.0000"
                                                for a, b in ((1001, 91000), (1002, 91001), (1003, 91002))]
      and all(float(ln[27:35]) == COUPLING_LINE_X_PCT and ln[42:].strip() == "" for ln in dlin))
check("one 99999 per block, FIM at the end", exp3.count("99999") == 2 and exp3.rstrip().endswith("FIM")
      and exp3.count("FIM") == 1 and exp3.count("DBAR") == 1 and exp3.count("DLIN") == 1)
check("one .pwf download; bytes == code block with CRLF",
      downloads() == [("BESS_modificacao.pwf", exp3.replace("\n", "\r\n").encode("ascii"))])
check("message lists the 3 BESS", m["content"].startswith("**3 BESS** neste estudo:")
      and all(f"BESS {i}:" in m["content"] for i in (1, 2, 3)))
params = run()["_study_params"](ss["sim_data"])
labels = [p[1] for p in params]
check("study panel lists each BESS with its parameters",
      all(f"BESS {i} · {l}" in labels for i in (1, 2, 3) for l in ("Barra", "Modo", "S", "P", "Nova barra")), labels)
check("every BESS row has ✏️", all(f"edit_bess_mva#{i}" in [e[2] for e in events("button")] for i in (0, 1))
      and "edit_bess_mva" in [e[2] for e in events("button")])

# ═════════════════════════════════════════════════════════════════════════════
section("2 BESS at the same existing bus")
# ═════════════════════════════════════════════════════════════════════════════
setup("STEP7", LOADED)
enter_bess("1001", "1", 100, 80, 91000); click_option("Adicionar outra BESS")
enter_bess("1001", "2", 50, 40, 91001); click_option("Gerar arquivo agora")
exp2 = generate_bess_block([dev(1001, 91000, "1", 100, 80), dev(1001, 91001, "0", 50, 40)])
check("same existing bus, different new buses → accepted, both coupling lines from 1001",
      code_blocks(last_assistant()["content"]) == [exp2]
      and [ln.split()[0] for ln in section_lines(exp2, "DLIN")] == ["1001", "1001"])

# ═════════════════════════════════════════════════════════════════════════════
section("bus numbers validated")
# ═════════════════════════════════════════════════════════════════════════════
setup("STEP7", LOADED)
enter_bess("1001", "1", 100, 80, 91000); click_option("Adicionar outra BESS")
run("1002"); run("1"); run("100 MVA"); run("80")
before = sim_state()
run("91000")
check("duplicate new bus rejected with a clear message, nothing stored",
      "já é a nova barra da **BESS 1**" in last_assistant()["content"] and sim_state() == before)
run("1001")
check("new bus equal to an existing bus of this study rejected",
      "barra existente informada neste estudo" in last_assistant()["content"] and sim_state() == before)
run("1002")
check("new bus equal to its own connection bus rejected", sim_state() == before)
run("91001")
check("a free number is accepted", ss["sim_data"].get("bess_bus_number") == "91001")
setup("STEP7", LOADED)
enter_bess("1001", "1", 100, 80, 91000); click_option("Adicionar outra BESS")
run("91000")
check("BESS 2 cannot connect to BESS 1's new bus", "bess_bus" not in ss["sim_data"] and ss["sim_step"] == "STEP7"
      and "já é a nova barra da **BESS 1**" in last_assistant()["content"])

data9 = dict(LOADED, bess_extra=[{"bess_bus": "1001", "bess_mode": "PV", "bess_mva": "10", "bess_p_mw": "5",
                                  "bess_bus_number": str(91000 + i)} for i in range(9)],
             bess_bus="1001", bess_mode="PV", bess_mva="10", bess_p_mw="5", bess_bus_number="91009")
setup("STEP8", data9)
click_option("Adicionar outra BESS")
check("limit of 10 BESS: 11th refused, state unchanged",
      ss["sim_step"] == "STEP8" and len(ss["sim_data"]["bess_extra"]) == 9
      and "Limite de **10 BESS**" in last_assistant()["content"])
click_option("Gerar arquivo agora")
check("…the 10 BESS are generated in one file",
      len(section_lines(code_blocks(last_assistant()["content"])[0], "DBAR")) == 10)

# ═════════════════════════════════════════════════════════════════════════════
section("pause / resume and logout keep every BESS")
# ═════════════════════════════════════════════════════════════════════════════
setup("STEP7", LOADED)
enter_bess("1001", "1", 500, 417, 91000); click_option("Adicionar outra BESS")
enter_bess("1002", "2", 100, 80, 91001); click_option("Adicionar outra BESS")
run("1003")
SCRIPT["press"] = {"⏸️ Pausar simulação"}; run(); SCRIPT["press"] = set()
paused = svc.load_paused_state("userA")
check("paused state in the DB keeps both confirmed BESS and the current one",
      paused and len(paused["sim_data"]["bess_extra"]) == 2 and paused["sim_data"]["bess_bus"] == "1003"
      and paused["sim_step"] == "STEP7", paused)
SCRIPT["press"] = {"▶️ Retomar"}; run(); SCRIPT["press"] = set()
check("resume (same session) keeps the device list", len(ss["sim_data"]["bess_extra"]) == 2 and ss["sim_status"] == "active")
SCRIPT["press"] = {"⏸️ Pausar simulação"}; run(); SCRIPT["press"] = set()
paused = svc.load_paused_state("userA")
# logout → login: a new session restores the paused state
fresh(None, session_id="sessB"); ss["_pending_resume"] = paused; run()
check("after logout/login the study comes back with every BESS",
      ss["sim_step"] == "STEP7" and len(ss["sim_data"]["bess_extra"]) == 2 and ss["sim_data"]["bess_bus"] == "1003")
run("1"); run("200 MVA"); run("150"); run("91002"); run("Gerar arquivo agora")
check("…and the file has the 3 BESS", code_blocks(last_assistant()["content"]) == [exp3])

# ═════════════════════════════════════════════════════════════════════════════
section("✏️ edit one device without corrupting the others")
# ═════════════════════════════════════════════════════════════════════════════
ss.clear(); ss.update(copy.deepcopy(snap3)); run(); click_option("Gerar arquivo agora")
extras_before = copy.deepcopy(ss["sim_data"]["bess_extra"])
e = next(e for e in events("button") if e[2] == "edit_bess_mva#1"); e[3](*e[4]); run()
check("✏️ on BESS 2 asks for BESS 2's value", "Alterar potência nominal da bess 2" in last_assistant()["content"]
      and "atual: **100 MVA**" in last_assistant()["content"], last_assistant()["content"][:200])
run("150 MVA")
d = ss["sim_data"]
check("only BESS 2 changed", d["bess_extra"][1]["bess_mva"] == "150" and d["bess_extra"][0] == extras_before[0]
      and d["bess_mva"] == "200" and d["bess_bus_number"] == "91002")
exp_e = generate_bess_block([dev(1001, 91000, "1", 500, 417), dev(1002, 91001, "0", 150, 80),
                             dev(1003, 91002, "1", 200, 150)])
check("block regenerated with every BESS (STEP9)", ss["sim_step"] == "STEP9"
      and code_blocks(last_assistant()["content"]) == [exp_e])
e = next(e for e in events("button") if e[2] == "edit_bess_bus_number#0"); e[3](*e[4]); run()
before = copy.deepcopy(ss["sim_data"])
run("91001")
check("✏️ new bus of BESS 1 to BESS 2's new bus → rejected, nothing changed",
      ss["sim_data"] == before and "já é a nova barra da **BESS 2**" in last_assistant()["content"])
run("91005")
check("…a free number is accepted for BESS 1 only",
      ss["sim_data"]["bess_extra"][0]["bess_bus_number"] == "91005"
      and ss["sim_data"]["bess_extra"][1]["bess_bus_number"] == "91001")
e = next(e for e in events("button") if e[2] == "edit_bess_mode"); e[3](*e[4]); run()
run("2")
check("✏️ on the current (last) BESS still edits the flat keys",
      ss["sim_data"]["bess_mode"] == "PQ" and ss["sim_data"]["bess_extra"][0]["bess_mode"] == "PV")

# ═════════════════════════════════════════════════════════════════════════════
section("rest of the flow")
# ═════════════════════════════════════════════════════════════════════════════
ss.clear(); ss.update(copy.deepcopy(snap3)); run(); click_option("Gerar arquivo agora")
run("salvo"); run("convergido"); run("nada"); run("não")
check("contingency / results flow unchanged up to STEP12", ss["sim_step"] == "STEP12")
run("2030")
kept = [ln for ln in last_assistant()["content"].splitlines() if ln.startswith("Mantendo")]
check("year change keeps every BESS (one confirmation line)", len(kept) == 1 and "**3 BESS**" in kept[0], kept)
run("convergido")
check("…new case: file regenerated with the 3 BESS", ss["sim_step"] == "STEP9"
      and code_blocks(last_assistant()["content"]) == [exp3])
run("salvo"); run("convergido"); run("nada"); run("não")
run("Verão Máxima Noturna")
check("scenario change clears every BESS", "bess_extra" not in ss["sim_data"] and "bess_bus" not in ss["sim_data"])

H.finish()
