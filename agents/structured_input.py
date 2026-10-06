"""
Structured input for the guided simulation (v6.5.0).

Pure module: no Streamlit. For the current simulation step it describes the
option buttons and forms shown under the latest assistant message, validates
form values and composes the CANONICAL TEXT that the existing state-machine
parsers already accept. The app feeds that text through the same handler as a
typed message, so a click or a form submit produces exactly the same state as
typing it. Nothing here changes simulation state.

Control specs:
  {"kind": "buttons", "options": [{"label", "text", "term"}]}
  {"kind": "form", "id", "title", "fields": [field], "submit",
   "selector": {"label", "options": [(value, label)], "default"} | None,
   "fields_by": {selector_value: [field]} | None}
  field: {"key", "label", "type": "int"|"float"|"text", "min", "max",
          "required", "placeholder", "term"}
"""

import re

# Substrings the state machine treats as commands anywhere in a message (global
# encerrar / restart checks, NET "ajuda" detection, line-definition guard). A
# free-text form value containing one would trigger the command instead of being
# stored, so forms block them inline.
_RESERVED = ("encerra", "finaliza", "terminar", "fim", "sair",            # encerrar
             "quero simular", "iniciar simulação", "nova simulação",       # restart
             "começar de novo", "quero inserir um",
             "ajuda", "help", "não sei", "nao sei", "como", "o que é", "o que e",  # NET help
             "circuito")                                                   # line definition
_BACK_WORDS = ("voltar", "volta", "anterior", "back")                     # NET voltar (exact)


# ── formatting / validation helpers ───────────────────────────────────────────

def fmt_num(v) -> str:
    """Shortest plain decimal text for a number (no exponent): 100 → '100', 0.5 → '0.5'."""
    if float(v).is_integer():
        return str(int(v))
    return ("%.10f" % float(v)).rstrip("0").rstrip(".")


def _f(key, label, typ="float", mn=None, mx=None, required=True, placeholder="", term=None):
    return {"key": key, "label": label, "type": typ, "min": mn, "max": mx,
            "required": required, "placeholder": placeholder, "term": term}


def parse_field(field, raw):
    """(value or None, error or None) for one field value typed in a form."""
    s = ("" if raw is None else str(raw)).strip()
    label = field["label"]
    if s == "":
        return (None, f"Informe {label}.") if field["required"] else (None, None)
    if field["type"] == "text":
        return s, None
    s2 = s.replace(",", ".").replace("−", "-")
    if field["type"] == "int":
        if not re.fullmatch(r"[-+]?\d+", s2):
            return None, f"{label}: use um número inteiro."
        v = int(s2)
    else:
        if not re.fullmatch(r"[-+]?(\d+(\.\d*)?|\.\d+)", s2):
            return None, f"{label}: número inválido."
        v = float(s2)
    if field["min"] is not None and v < field["min"]:
        return None, f"{label}: deve ser no mínimo {fmt_num(field['min'])}."
    if field["max"] is not None and v > field["max"]:
        return None, f"{label}: deve ser no máximo {fmt_num(field['max'])}."
    return v, None


def _reserved_error(label, text):
    low = text.lower()
    hit = next((w for w in _RESERVED if w in low), None)
    if hit is None and low.strip() in _BACK_WORDS:
        hit = low.strip()
    return f"{label}: não use “{hit}” (é um comando do guia)." if hit else None


# ── option sets ───────────────────────────────────────────────────────────────

def _opt(label, text=None, term=None):
    return {"label": label, "text": text or label, "term": term}


def _buttons(*opts):
    return {"kind": "buttons", "options": list(opts)}


CONVERGED = _opt("🟢 Verde, convergiu", "Verde, convergiu")
NOT_CONVERGED = _opt("Não convergiu", "Não convergiu")
YELLOW = _opt("🟡 Amarelo (limite de iterações)", "Amarelo (limite de iterações)")
RED = _opt("🔴 Vermelho (divergiu)", "Vermelho (divergiu)")
DB_OPTIONS = [_opt("EPE (PDE)"), _opt("ONS (PAR/PEL)")]
MODE_OPTIONS = [_opt("Modo PV (controle de tensão)", term="PV"),
                _opt("Modo PQ (despacho fixo)", term="PQ")]
LINE_MODES = [("1", "por km"), ("2", "pu"), ("3", "%/Mvar")]
BUS_TYPES = [("0", "PQ (carga)"), ("1", "PV (geração)"), ("2", "Referência (slack)")]


def scenario_options(names):
    return _buttons(*[_opt(n) for n in names])


# ── forms ─────────────────────────────────────────────────────────────────────

def _form(fid, title, fields=None, submit="Enviar", selector=None, fields_by=None):
    return {"kind": "form", "id": fid, "title": title, "fields": fields or [],
            "submit": submit, "selector": selector, "fields_by": fields_by}


F_YEARS = _f("years", "Ano(s)", "text", placeholder="ex: 2028 ou 2027, 2028")
F_BUS = _f("bus", "Número da barra", "int", 10, 99999, placeholder="ex: 1001")
F_MVA = _f("mva", "Potência nominal (MVA)", "float", 0.000001, 100000, term="MVA")
# 0 ≤ P ≤ S. PENDING EXPERT DECISION: charging BESS as negative Pg or as load (Pl).
F_P = _f("p", "Potência ativa (MW)", "float", 0, 100000, placeholder="0 a S")
F_NEW_BUS = _f("bus", "Número da nova barra da BESS", "int", 1000, 99999,
               placeholder="número que não existe no caso")
F_QMIN = _f("qmin", "Qmin (Mvar)", "float", -100000, 100000, placeholder="ex: -100", term="Mvar")
F_QMAX = _f("qmax", "Qmax (Mvar)", "float", -100000, 100000, placeholder="ex: 100", term="Mvar")
F_REMOTE = _f("bus", "Barra remota a controlar", "int", 1000, 99999)
F_TITLE = _f("title", "Título do caso", "text", required=False, placeholder="ex: LT 230kV Teste")
F_BASE = _f("base", "Base (MVA)", "float", 0.000001, 100000, required=False, placeholder="100", term="MVA")
F_TITLE_REQ = dict(F_TITLE, required=True)

NET2_FIELDS = {
    "count": _f("v", "Número de barras", "int", 2, 20),
    "name": _f("v", "Nome da barra (até 12 caracteres)", "text"),
    "kv": _f("v", "Tensão nominal (kV)", "float", 0.1, 2000),
    "pg": _f("v", "Geração ativa (MW)", "float", 0, 100000),
    "v_pu": _f("v", "Tensão setpoint (pu)", "float", 0.5, 1.5, term="pu"),
    "qmin": _f("v", "Qmin (Mvar)", "float", -100000, 100000, term="Mvar"),
    "qmax": _f("v", "Qmax (Mvar)", "float", -100000, 100000, term="Mvar"),
    "pl": _f("v", "Carga ativa (MW)", "float", 0, 100000),
    "ql": _f("v", "Carga reativa (Mvar)", "float", 0, 100000, term="Mvar"),
}

_BUS_COMMON = [_f("number", "Número da barra", "int", 1, 99999),
               _f("name", "Nome (até 12 caracteres)", "text"),
               _f("kv", "Tensão nominal (kV)", "float", 0.1, 2000)]
BUS_FIELDS_BY_TYPE = {
    "2": _BUS_COMMON + [_f("v_pu", "Tensão de referência (pu)", "float", 0.5, 1.5, term="pu")],
    "1": _BUS_COMMON + [_f("pg", "Geração ativa (MW)", "float", 0, 100000),
                        _f("v_pu", "Tensão setpoint (pu)", "float", 0.5, 1.5, term="pu"),
                        _f("qmin", "Qmin (Mvar)", "float", -100000, 100000, term="Mvar"),
                        _f("qmax", "Qmax (Mvar)", "float", -100000, 100000, term="Mvar")],
    "0": _BUS_COMMON + [_f("pl", "Carga ativa (MW)", "float", 0, 100000),
                        _f("ql", "Carga reativa (Mvar)", "float", 0, 100000, term="Mvar")],
}

LINE_FIELDS_BY_MODE = {
    "1": [_f("r", "R (Ω/km)", "float", 0, 1000), _f("x", "X (Ω/km)", "float", 0.0000001, 1000),
          _f("b", "B (μS/km)", "float", 0, 100000), _f("l", "Comprimento (km)", "float", 0.001, 100000)],
    "2": [_f("r", "R (pu)", "float", 0, 1000, term="pu"), _f("x", "X (pu)", "float", 0.0000001, 1000, term="pu"),
          _f("b", "B (pu)", "float", 0, 1000, term="pu")],
    "3": [_f("r", "R (%)", "float", 0, 100000), _f("x", "X (%)", "float", 0.0000001, 100000),
          _f("q", "Q (Mvar)", "float", 0, 100000, term="Mvar")],
}


def _line_mode_selector():
    return {"label": "Modo dos parâmetros", "options": LINE_MODES, "default": "1"}


def _bus_type_selector():
    return {"label": "Tipo da barra", "options": BUS_TYPES, "default": "0"}


# ── controls per step ─────────────────────────────────────────────────────────

def controls_for(step, data, parpel_scenarios=(), pde_scenarios=()):
    """List of control specs for the current step (empty → typing only)."""
    data = data or {}
    sim_type = data.get("sim_type", "BESS")
    if step == "IDLE_LT_CONFIRM":
        return [_buttons(_opt("Sim, iniciar simulação guiada", "Sim"),
                         _opt("Não, só quero uma resposta técnica", "Não"))]
    if step == "IDLE_LT_NET_CHOICE":
        return [_buttons(_opt("Montar uma rede nova do zero"),
                         _opt("Inserir em caso existente (PAR/PEL/PDE)"))]
    if step == "STEP1":
        return [_buttons(*DB_OPTIONS, _opt("Minha própria rede (montar do zero)"))]
    if step == "STEP2":
        return [_form("years", "Ano(s) do estudo", [F_YEARS])]
    if step == "STEP3":
        names = parpel_scenarios if data.get("db", "ONS") in ("ONS", "PARPEL") else pde_scenarios
        return [scenario_options(names)]
    if step == "STEP4":
        return [_buttons(CONVERGED, NOT_CONVERGED)]
    if step == "STEP6":
        return [_buttons(_opt("Opção A — tenho o arquivo LST", term="LST"),
                         _opt("Opção B — vou desenhar a região", term="LST"))]
    if step == "STEP7":
        if sim_type == "STATCOM":
            return [_form("statcom_bus", "Barra do STATCOM", [F_BUS])]
        if "bess_bus" not in data:
            return [_form("bess_bus", "Barra de inserção da BESS", [F_BUS])]
        return [_buttons(*MODE_OPTIONS)]
    if step == "STEP8":
        if "bess_mva" not in data:
            return [_form("bess_power", "Potência da BESS", [F_MVA, dict(F_P, required=False)])]
        if "bess_p_mw" not in data:
            return [_form("bess_p", "Potência ativa da BESS", [F_P])]
        return [_form("bess_new_bus", "Nova barra da BESS", [F_NEW_BUS])]
    if step == "STATCOM_STEP_Q":
        return [_form("statcom_q", "Capacidade reativa do STATCOM", [F_QMIN, F_QMAX])]
    if step == "STATCOM_STEP_CBUS":
        return [_buttons(_opt("Barra local (padrão)", "Barra local")),
                _form("statcom_remote", "…ou controlar uma barra remota", [F_REMOTE])]
    if step == "STEP9":
        return [_buttons(_opt("✅ Caso salvo", "Salvo"))]
    if step == "STEP10":
        if data.get("divergence_color") == "unknown":
            return [_buttons(RED, YELLOW)]
        return [_buttons(CONVERGED, NOT_CONVERGED)]
    if step == "STEP11B":
        stage = data.get("contingency_stage")
        if stage is None:
            return [_buttons(_opt("Sim, analisar contingências N-1", "Sim", term="N-1"),
                             _opt("Não, seguir para os próximos passos", "Não"))]
        if stage == "done":
            return [_buttons(_opt("▶️ Executar agora", "Executar agora"),
                             _opt("➕ Adicionar mais contingências", "Adicionar mais contingências"),
                             _opt("Seguir para os próximos passos"))]
        return []
    if step == "STEP12":
        return [_buttons(_opt("Outro cenário"), _opt("Encerrar"))]
    if step == "NET1_SETUP":
        return [_buttons(_opt("Confirmar (Meu Caso, 100 MVA)", "confirmar")),
                _form("net_setup", "…ou defina título e base", [F_TITLE, F_BASE])]
    if step == "NET2_BUSES":
        net2 = data.get("net2") or {}
        field = net2.get("field", "count")
        if field == "count" or net2.get("total") is None:
            return [_form("net2_count", "Número de barras", [NET2_FIELDS["count"]])]
        if field == "number":
            return [_form("net_bus", "Dados da barra", selector=_bus_type_selector(),
                          fields_by=BUS_FIELDS_BY_TYPE, submit="Registrar barra")]
        if field == "tipo":
            return [_buttons(*[_opt(lbl, lbl, term=lbl.split()[0]) for _, lbl in BUS_TYPES])]
        if field in NET2_FIELDS:
            return [_form(f"net2_{field}", NET2_FIELDS[field]["label"], [NET2_FIELDS[field]])]
        return []
    if step == "NET3_LINES":
        net3 = data.get("net3") or {}
        field = net3.get("field", "count")
        buses = [b["number"] for b in (data.get("network") or {}).get("buses", [])]
        if field == "count" or net3.get("total") is None:
            return [_form("net3_count", "Número de linhas", [_f("v", "Número de linhas", "int", 1, 50)])]
        if field == "from_bus":
            return [_buttons(*[_opt(f"Barra {n}", str(n)) for n in buses])]
        if field == "to_bus":
            frm = (net3.get("current") or {}).get("from_bus")
            return [_buttons(*[_opt(f"Barra {n}", str(n)) for n in buses if n != frm])]
        if field == "circuit":
            return [_form("net3_circuit", "Circuito", [_f("v", "Número do circuito", "int", 1, 9)])]
        if field == "mode":
            return [_form("net_line_mode", "Parâmetros da linha", selector=_line_mode_selector(),
                          fields_by=LINE_FIELDS_BY_MODE)]
        if field == "values":
            mode = {"per_km": "1", "pu": "2", "pct": "3"}.get((net3.get("current") or {}).get("param_mode"), "1")
            return [_form(f"net_line_values_{mode}", "Parâmetros da linha", LINE_FIELDS_BY_MODE[mode])]
        return []
    if step == "NET4_REVIEW":
        return [_buttons(_opt("✅ Confirmar e gerar o PWF", "confirmar", term="PWF"),
                         _opt("Adicionar barra"), _opt("Adicionar linha"))]
    if step == "NET5_GENERATE":
        return [_buttons(_opt("Continuar"))]
    if step == "NET6_RUN":
        return [_buttons(CONVERGED, YELLOW, RED)]
    if step == "NET7_RESULTS":
        color = data.get("net7_color", "unknown")
        if color == "green":
            return [_buttons(_opt("Contingências N-1", term="N-1"), _opt("Inserir BESS"),
                             _opt("Inserir STATCOM"), _opt("Encerrar"))]
        if color == "unknown":
            return [_buttons(CONVERGED, YELLOW, RED)]
        return [_buttons(_opt("Editar rede"), _opt("Encerrar"))]
    return []


def controls_for_edit(field, data, parpel_scenarios=(), pde_scenarios=()):
    """Controls for re-asking ONE parameter from the study panel."""
    data = data or {}
    if field == "db":
        return [_buttons(*DB_OPTIONS)]
    if field == "years":
        return [_form("years", "Novo(s) ano(s)", [F_YEARS])]
    if field == "scenario":
        names = parpel_scenarios if data.get("db", "ONS") in ("ONS", "PARPEL") else pde_scenarios
        return [scenario_options(names)]
    if field in ("bess_bus", "statcom_bus"):
        return [_form("edit_bus", "Nova barra", [F_BUS])]
    if field == "bess_mode":
        return [_buttons(*MODE_OPTIONS)]
    if field == "bess_mva":
        return [_form("edit_mva", "Nova potência nominal", [F_MVA])]
    if field == "bess_p_mw":
        return [_form("bess_p", "Nova potência ativa", [F_P])]
    if field == "bess_bus_number":
        return [_form("bess_new_bus", "Nova barra da BESS", [F_NEW_BUS])]
    if field == "statcom_q":
        return [_form("statcom_q", "Nova capacidade reativa", [F_QMIN, F_QMAX])]
    if field == "net_title":
        return [_form("edit_title", "Novo título", [F_TITLE_REQ])]
    return []


def form_fields(spec, selector_value=None):
    if spec.get("fields_by"):
        return spec["fields_by"].get(selector_value or spec["selector"]["default"], [])
    return spec["fields"]


# ── compose canonical text ────────────────────────────────────────────────────

def compose(spec, raw_values, selector_value=None, data=None):
    """
    Validate a submitted form and build the canonical message(s).
    Returns (errors, texts). `texts` is a list: most forms answer one question,
    a few answer a short sequence of questions the handler asks one at a time
    (each is processed as its own turn, stopping if one is not accepted).
    """
    data = data or {}
    fid = spec["id"]
    fields = form_fields(spec, selector_value)
    vals, errors = {}, []
    for f in fields:
        v, err = parse_field(f, raw_values.get(f["key"]))
        if err:
            errors.append(err)
        vals[f["key"]] = v
    if errors:
        return errors, []
    n = fmt_num

    if fid == "years":
        years = re.findall(r"\b(20\d\d)\b", vals["years"])
        rest = re.sub(r"\b20\d\d\b|[\s,;e/]+", "", vals["years"])
        if not years or rest:
            return ["Ano(s): use anos com 4 dígitos, ex: 2028 ou 2027, 2028."], []
        return [], [", ".join(years)]
    if fid in ("bess_bus", "statcom_bus", "edit_bus", "bess_new_bus"):
        return [], [str(vals["bus"])]
    if fid == "bess_power":
        if vals["p"] is not None and vals["p"] > vals["mva"]:
            return ["A potência ativa não pode ser maior que a potência nominal (MVA)."], []
        txt = f"{n(vals['mva'])} MVA"
        if vals["p"] is not None:
            txt += f", potência ativa {n(vals['p'])} MW"
        return [], [txt]
    if fid == "edit_mva":
        return [], [f"{n(vals['mva'])} MVA"]
    if fid == "bess_p":
        try:
            s = float(data.get("bess_mva")) if data.get("bess_mva") is not None else None
        except (TypeError, ValueError):
            s = None
        if s is not None and vals["p"] > s:
            return [f"A potência ativa não pode ser maior que a potência nominal ({n(s)} MVA)."], []
        return [], [f"potência ativa {n(vals['p'])} MW"]
    if fid == "statcom_q":
        if vals["qmin"] >= vals["qmax"]:
            return ["Qmin deve ser menor que Qmax."], []
        return [], [f"Qmin {n(vals['qmin'])} Mvar, Qmax {n(vals['qmax'])} Mvar"]
    if fid == "statcom_remote":
        return [], [f"barra remota {vals['bus']}"]
    if fid == "net_setup":
        title, base = vals["title"], vals["base"]
        if title:
            if "," in title or re.search(r"\d\s*mva", title, re.I):
                return ["Título: não use vírgulas nem o texto “MVA”."], []
            err = _reserved_error("Título", title)
            if err:
                return [err], []
        if not title and base is None:
            return ["Informe o título e/ou a base, ou use “Confirmar”."], []
        if base is None:
            return [], [title]
        return [], [f"{title}, {n(base)} MVA" if title else f"{n(base)} MVA"]
    if fid == "edit_title":
        err = _reserved_error("Título", vals["title"])
        return ([err], []) if err else ([], [vals["title"][:50]])
    if fid == "net_bus":
        return _compose_bus(vals, selector_value or "0", data)
    if fid.startswith("net2_") or fid in ("net3_count", "net3_circuit"):
        v = vals["v"]
        if fid == "net2_name":
            err = _name_error(v)
            if err:
                return [err], []
            return [], [v]
        return [], [n(v)]
    if fid == "net_line_mode":
        mode = selector_value or "1"
        return [], [mode, _line_values_text(mode, vals)]
    if fid.startswith("net_line_values_"):
        return [], [_line_values_text(fid[-1], vals)]
    return [f"Formulário desconhecido: {fid}"], []


def _name_error(name):
    if not re.fullmatch(r"[A-Za-z0-9_]{1,12}", name or ""):
        return "Nome: até 12 caracteres, apenas letras sem acento, números e “_”."
    return _reserved_error("Nome", name)


def _compose_bus(vals, tipo, data):
    errs = []
    err = _name_error(vals["name"])
    if err:
        errs.append(err)
    existing = {b["number"] for b in (data.get("network") or {}).get("buses", [])}
    if vals["number"] in existing:
        errs.append(f"Número da barra: {vals['number']} já existe.")
    if tipo == "1" and vals["qmin"] > vals["qmax"]:
        errs.append("Qmin deve ser menor ou igual a Qmax.")
    if errs:
        return errs, []
    n = fmt_num
    head = f"{vals['number']}, {vals['name']}, {n(vals['kv'])} kV"
    if tipo == "2":
        return [], [f"{head}, Referência, V={n(vals['v_pu'])}"]
    if tipo == "0":
        return [], [f"{head}, PQ, {n(vals['pl'])} MW, {n(vals['ql'])} Mvar"]
    # PV: the compact record has no Qmin/Qmax, so register the identity and let
    # the handler ask the remaining fields one at a time (same as typing them).
    return [], [f"{head}, PV", n(vals["pg"]), n(vals["v_pu"]), n(vals["qmin"]), n(vals["qmax"])]


def _line_values_text(mode, vals):
    n = fmt_num
    if mode == "1":
        return f"R={n(vals['r'])} X={n(vals['x'])} B={n(vals['b'])} L={n(vals['l'])}"
    if mode == "2":
        return f"R={n(vals['r'])} X={n(vals['x'])} B={n(vals['b'])}"
    return f"R={n(vals['r'])} X={n(vals['x'])} Q={n(vals['q'])}"


# ── progress ("Passo N de M") ────────────────────────────────────────────────

STEP_SEQUENCES = {
    "BESS": ["STEP1", "STEP2", "STEP3", "STEP4", "STEP6", "STEP7", "STEP8",
             "STEP9", "STEP10", "STEP11", "STEP11B", "STEP12"],
    "STATCOM": ["STEP1", "STEP2", "STEP3", "STEP4", "STEP6", "STEP7", "STATCOM_STEP_Q",
                "STATCOM_STEP_CBUS", "STEP9", "STEP10", "STEP11", "STEP11B", "STEP12"],
    "NETWORK": ["NET1_SETUP", "NET2_BUSES", "NET3_LINES", "NET4_REVIEW",
                "NET5_GENERATE", "NET6_RUN", "NET7_RESULTS"],
}


def progress(sim_type, step):
    """(n, m) for 'Passo n de m', or (None, None) when the step is outside the sequence."""
    seq = STEP_SEQUENCES.get(sim_type or "BESS")
    if not seq or step not in seq:
        return None, None
    return seq.index(step) + 1, len(seq)
