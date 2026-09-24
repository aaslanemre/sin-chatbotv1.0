"""
Pure functions for building an ANAREDE network from scratch.
No Streamlit imports — fully unit-testable.
"""

import math
from utils.anarede_lib import Script_Inclui_DBAR, Script_Inclui_DLIN


# ── A) Conversion engine ──────────────────────────────────────────────────────

def convert_line_params(kv, mode, values, length_km=None, base_mva=100.0):
    """
    Convert line parameters to ANAREDE DLIN format (R%, X%, Q Mvar).

    Parameters
    ----------
    kv       : float  — nominal voltage in kV
    mode     : str    — "per_km" | "pu" | "pct"
    values   : dict
      per_km : {"R": Ω/km, "X": Ω/km, "B": μS/km}  + length_km required
      pu     : {"R": pu, "X": pu, "B": pu} on base_mva
      pct    : {"R": %, "X": %, "Q": Mvar} — pass-through, validated
    length_km: float — required for mode "per_km"
    base_mva : float — system MVA base (default 100)

    Returns
    -------
    dict with keys: r_pct, x_pct, q_mvar, calc_str (PT-BR step-by-step)
    Raises ValueError on invalid input.
    """
    if kv <= 0:
        raise ValueError(f"Tensão kV inválida: {kv}")
    if base_mva <= 0:
        raise ValueError(f"Base MVA inválida: {base_mva}")

    if mode == "per_km":
        if length_km is None or length_km <= 0:
            raise ValueError("Comprimento em km obrigatório para modo per_km.")
        r_okm = float(values["R"])
        x_okm = float(values["X"])
        b_uskm = float(values["B"])
        L = float(length_km)

        zbase = kv ** 2 / base_mva
        r_total = r_okm * L
        x_total = x_okm * L
        b_total_s = b_uskm * 1e-6 * L      # S (Siemens)

        r_pct = (r_total / zbase) * 100.0
        x_pct = (x_total / zbase) * 100.0
        q_mvar = b_total_s * (kv ** 2) * 1e3  # Mvar: B(S)·kV²·10³ ... wait

        # Correct formula: Q(Mvar) = B(S) × V²(V²) / 10⁶ = B(S)×(kV×10³)²/10⁶
        # = B(S) × kV² × 10⁶/10⁶ = B(S) × kV²
        # B(S) = b_uskm × 10⁻⁶ × L
        # Q = b_uskm × 10⁻⁶ × L × kV²   [Mvar if we divide by 10⁶? let's check]
        # Q(Mvar) = B(MΩ⁻¹) × kV²  where B in Mhos/phase
        # 1 μS = 10⁻⁶ S → b_total_S = b_uskm×10⁻⁶×L [S]
        # Q = b_total_S × (kV×1000)² / 10⁶ = b_total_S × kV² × 10⁶/10⁶ = b_total_S × kV²  [Mvar?]
        # Verification: 5.4542e-6 S/km × 180 km = 9.8176e-4 S
        # Q = 9.8176e-4 × 230² = 9.8176e-4 × 52900 ≈ 51.93 Mvar  ✓
        q_mvar = b_total_s * (kv ** 2)

        calc_str = (
            f"**Conversão de parâmetros por km → DLIN**\n\n"
            f"Dados de entrada:\n"
            f"- Tensão nominal: **{kv} kV**\n"
            f"- Comprimento: **{L} km**\n"
            f"- R = {r_okm} Ω/km, X = {x_okm} Ω/km, B = {b_uskm} μS/km\n"
            f"- Base: **{base_mva} MVA**\n\n"
            f"**Passo 1 — Impedância base:**\n"
            f"Zbase = kV² / Sbase = {kv}² / {base_mva} = **{zbase:.4f} Ω**\n\n"
            f"**Passo 2 — Valores totais da linha:**\n"
            f"R_total = {r_okm} × {L} = **{r_total:.4f} Ω**\n"
            f"X_total = {x_okm} × {L} = **{x_total:.4f} Ω**\n"
            f"B_total = {b_uskm} × 10⁻⁶ × {L} = **{b_total_s:.6e} S**\n\n"
            f"**Passo 3 — Conversão para o DLIN:**\n"
            f"R% = (R_total / Zbase) × 100 = ({r_total:.4f} / {zbase:.4f}) × 100 = **{r_pct:.4f} %**\n"
            f"X% = (X_total / Zbase) × 100 = ({x_total:.4f} / {zbase:.4f}) × 100 = **{x_pct:.4f} %**\n"
            f"Q = B_total × kV² = {b_total_s:.6e} × {kv}² = **{q_mvar:.4f} Mvar**\n\n"
            f"**Valores para o DLIN:** R = {r_pct:.4f} %, X = {x_pct:.4f} %, Q = {q_mvar:.4f} Mvar"
        )

    elif mode == "pu":
        r_pu = float(values["R"])
        x_pu = float(values["X"])
        b_pu = float(values["B"])

        r_pct = r_pu * 100.0
        x_pct = x_pu * 100.0
        q_mvar = b_pu * base_mva

        calc_str = (
            f"**Conversão de parâmetros em pu → DLIN**\n\n"
            f"Dados de entrada (base {base_mva} MVA, {kv} kV):\n"
            f"- R = {r_pu} pu, X = {x_pu} pu, B = {b_pu} pu\n\n"
            f"**Conversão:**\n"
            f"R% = R_pu × 100 = {r_pu} × 100 = **{r_pct:.4f} %**\n"
            f"X% = X_pu × 100 = {x_pu} × 100 = **{x_pct:.4f} %**\n"
            f"Q = B_pu × Sbase = {b_pu} × {base_mva} = **{q_mvar:.4f} Mvar**\n\n"
            f"**Valores para o DLIN:** R = {r_pct:.4f} %, X = {x_pct:.4f} %, Q = {q_mvar:.4f} Mvar"
        )

    elif mode == "pct":
        r_pct = float(values["R"])
        x_pct = float(values["X"])
        q_mvar = float(values["Q"])

        if r_pct < 0:
            raise ValueError("R% não pode ser negativo.")
        if x_pct <= 0:
            raise ValueError("X% deve ser positivo.")

        calc_str = (
            f"**Parâmetros já em formato DLIN (pass-through)**\n\n"
            f"R = **{r_pct} %**, X = **{x_pct} %**, Q = **{q_mvar} Mvar**\n\n"
            f"Nenhuma conversão necessária. Valores utilizados diretamente no DLIN."
        )

    else:
        raise ValueError(f"Modo desconhecido: {mode}. Use 'per_km', 'pu' ou 'pct'.")

    return {"r_pct": r_pct, "x_pct": x_pct, "q_mvar": q_mvar, "calc_str": calc_str}


# ── B) Validation ─────────────────────────────────────────────────────────────

def validate_network(network):
    """
    Validate a network dict. Returns list of issue dicts:
      {severity, message, why_it_matters, how_to_fix, target}
    where severity is "error" or "warning".
    All messages in PT-BR, beginner-friendly.
    """
    issues = []
    buses = network.get("buses", [])
    lines = network.get("lines", [])

    bus_nums = [b["number"] for b in buses]
    bus_map = {b["number"]: b for b in buses}

    # 1 — Exactly one reference bus (tipo 2)
    ref_buses = [b for b in buses if b.get("tipo") == 2]
    if len(ref_buses) == 0:
        issues.append({
            "severity": "error",
            "message": "Nenhuma barra de referência (tipo 2) encontrada.",
            "why_it_matters": "O ANAREDE precisa de exatamente uma barra de referência (slack) para balancear a geração e definir o ângulo de referência angular.",
            "how_to_fix": "Defina uma das barras geradoras como tipo 2 (Referência). Geralmente é a barra com a maior geração ou a barra de interligação principal.",
            "target": None,
        })
    elif len(ref_buses) > 1:
        nums = [b["number"] for b in ref_buses]
        issues.append({
            "severity": "error",
            "message": f"Mais de uma barra de referência: barras {nums}.",
            "why_it_matters": "Ter duas barras de referência cria ambiguidade no balanço de potência — o fluxo de carga não tem solução única.",
            "how_to_fix": f"Mantenha apenas uma barra como tipo 2. Mude as barras {nums[1:]} para tipo 0 (PQ) ou tipo 1 (PV).",
            "target": nums,
        })

    # 2 — Unique bus numbers within 1–99999
    seen_nums = set()
    for b in buses:
        n = b["number"]
        if not (1 <= n <= 99999):
            issues.append({
                "severity": "error",
                "message": f"Barra {n}: número fora do intervalo permitido (1–99999).",
                "why_it_matters": "O ANAREDE aceita apenas números de barra entre 1 e 99999.",
                "how_to_fix": f"Altere o número da barra {n} para um valor entre 1 e 99999.",
                "target": n,
            })
        if n in seen_nums:
            issues.append({
                "severity": "error",
                "message": f"Número de barra duplicado: {n}.",
                "why_it_matters": "Dois elementos com o mesmo número de barra causam leitura incorreta do arquivo pelo ANAREDE.",
                "how_to_fix": f"Altere o número de uma das barras {n} para um valor único.",
                "target": n,
            })
        seen_nums.add(n)

    # 3 — Line endpoints exist; no self-loops
    for line in lines:
        f, t = line["from_bus"], line["to_bus"]
        if f == t:
            issues.append({
                "severity": "error",
                "message": f"Linha {line['id']}: barra origem igual à barra destino ({f}).",
                "why_it_matters": "Uma linha que conecta uma barra a si mesma não tem sentido físico.",
                "how_to_fix": f"Corrija a linha {line['id']} para conectar duas barras diferentes.",
                "target": line["id"],
            })
        if f not in bus_map:
            issues.append({
                "severity": "error",
                "message": f"Linha {line['id']}: barra origem {f} não existe.",
                "why_it_matters": "Uma linha não pode conectar-se a uma barra que não está definida no DBAR.",
                "how_to_fix": f"Adicione a barra {f} ou corrija o número da barra origem na linha {line['id']}.",
                "target": line["id"],
            })
        if t not in bus_map:
            issues.append({
                "severity": "error",
                "message": f"Linha {line['id']}: barra destino {t} não existe.",
                "why_it_matters": "Uma linha não pode conectar-se a uma barra que não está definida no DBAR.",
                "how_to_fix": f"Adicione a barra {t} ou corrija o número da barra destino na linha {line['id']}.",
                "target": line["id"],
            })

    # 4 — Duplicate (from, to, circuit)
    seen_lines = set()
    for line in lines:
        key = (min(line["from_bus"], line["to_bus"]),
               max(line["from_bus"], line["to_bus"]),
               line.get("circuit", 1))
        if key in seen_lines:
            issues.append({
                "severity": "error",
                "message": f"Linha {line['id']}: circuito duplicado entre barras {key[0]} e {key[1]}, circuito {key[2]}.",
                "why_it_matters": "O ANAREDE identifica cada linha pelo par de barras e número de circuito. Duplicatas causam erros de leitura.",
                "how_to_fix": f"Altere o número de circuito da linha {line['id']} para um valor único entre essas barras.",
                "target": line["id"],
            })
        seen_lines.add(key)

    # 5 — Graph connectivity: isolated buses
    if len(buses) > 1 and lines:
        adj = {b["number"]: set() for b in buses}
        for line in lines:
            f, t = line["from_bus"], line["to_bus"]
            if f in adj and t in adj:
                adj[f].add(t)
                adj[t].add(f)

        # BFS/DFS from first bus
        start = buses[0]["number"]
        visited = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in visited:
                continue
            visited.add(node)
            stack.extend(adj.get(node, set()) - visited)

        isolated = [n for n in bus_nums if n not in visited]
        if isolated:
            issues.append({
                "severity": "error",
                "message": f"Barra(s) isolada(s) sem conexão: {isolated}.",
                "why_it_matters": "Barras sem conexão com o restante da rede tornam o sistema elétrico matematicamente insolúvel.",
                "how_to_fix": f"Adicione pelo menos uma linha conectando as barras {isolated} ao restante da rede.",
                "target": isolated,
            })

    # 6 — Line between buses with different kV (transformer needed)
    for line in lines:
        f, t = line["from_bus"], line["to_bus"]
        if f in bus_map and t in bus_map:
            kv_f = bus_map[f].get("kv", 0)
            kv_t = bus_map[t].get("kv", 0)
            if kv_f != kv_t and kv_f > 0 and kv_t > 0:
                issues.append({
                    "severity": "error",
                    "message": f"Linha {line['id']}: conecta barras em tensões diferentes ({kv_f} kV e {kv_t} kV). Necessário transformador.",
                    "why_it_matters": "No ANAREDE, a conexão entre barras de tensões distintas exige um registro de transformador (tipo T no DLIN), não uma linha simples. Transformadores não são suportados neste fluxo de versão.",
                    "how_to_fix": f"Certifique-se de que as barras {f} e {t} estão no mesmo nível de tensão, ou divida a rede em subsistemas separados por tensão.",
                    "target": line["id"],
                })

    # 7 — Generation capacity vs total load (warning)
    total_gen_cap = sum(
        b.get("p_gen_mw", 0) for b in buses if b.get("tipo") in (1, 2)
    )
    total_load = sum(b.get("p_load_mw", 0) for b in buses)
    if total_load > 0 and total_gen_cap < total_load * 0.5:
        issues.append({
            "severity": "warning",
            "message": f"Geração total ({total_gen_cap:.1f} MW) parece insuficiente para a carga total ({total_load:.1f} MW).",
            "why_it_matters": "Se a geração declarada for muito menor que a carga, o fluxo pode não convergir. A barra de referência absorverá o déficit, mas isso pode causar tensões anômalas.",
            "how_to_fix": "Verifique os valores de geração nas barras PV e de referência, ou reduza a carga nas barras PQ.",
            "target": None,
        })

    # 8 — V setpoint outside 0.90–1.10 pu
    for b in buses:
        v = b.get("v_pu", 1.0)
        if not (0.90 <= v <= 1.10):
            issues.append({
                "severity": "warning",
                "message": f"Barra {b['number']}: tensão setpoint {v:.3f} pu fora da faixa típica (0.90–1.10 pu).",
                "why_it_matters": "Tensões muito diferentes de 1.0 pu podem dificultar a convergência e indicam um caso fora da operação normal.",
                "how_to_fix": f"Ajuste a tensão da barra {b['number']} para um valor entre 0.90 e 1.10 pu.",
                "target": b["number"],
            })

    # 9 — X% implausibly small or large, X/R unusual
    for line in lines:
        x = line.get("x_pct", 0)
        r = line.get("r_pct", 0)
        if x < 0.01:
            issues.append({
                "severity": "warning",
                "message": f"Linha {line['id']}: X% = {x:.4f} % muito pequeno (< 0.01 %).",
                "why_it_matters": "Reatâncias muito pequenas podem causar mal-condicionamento numérico no ANAREDE.",
                "how_to_fix": f"Verifique os dados da linha {line['id']}. Se for uma linha de acoplamento (ex: BESS), use X = 0.00001 % como mínimo.",
                "target": line["id"],
            })
        if x > 100:
            issues.append({
                "severity": "warning",
                "message": f"Linha {line['id']}: X% = {x:.2f} % muito grande (> 100 %).",
                "why_it_matters": "Reatâncias muito altas indicam linhas eletricamente fracas, que dificultam a convergência.",
                "how_to_fix": f"Verifique os dados da linha {line['id']}. Valores acima de 100 % são incomuns para linhas reais.",
                "target": line["id"],
            })
        if r > 0 and x > 0:
            xr = x / r
            if xr < 1.0:
                issues.append({
                    "severity": "warning",
                    "message": f"Linha {line['id']}: razão X/R = {xr:.2f} incomum para linhas de alta tensão (esperado X/R > 5).",
                    "why_it_matters": "Linhas de transmissão de alta tensão têm tipicamente X/R alto. Razão baixa pode indicar dados invertidos.",
                    "how_to_fix": f"Verifique se os valores de R e X da linha {line['id']} não estão trocados.",
                    "target": line["id"],
                })

    return issues


# ── C) PWF assembly ───────────────────────────────────────────────────────────

# OPEN QUESTION: The exact syntax for ANAREDE title record (TITU) and power
# flow execution command (EXLF) has not been confirmed from the RAG corpus /
# indexed ANAREDE manual. These records are intentionally omitted from the
# generated file to avoid generating invalid syntax. Once confirmed, they
# should be added before the DBAR section.

def build_full_pwf(network):
    """
    Assemble a complete PWF file for a from-scratch network.
    Uses Script_Inclui_DBAR and Script_Inclui_DLIN from anarede_lib.
    Type mapping: PQ=0, PV=1, Referência=2.
    Lines: operação A, estado L, TAP field empty.

    OPEN QUESTION: Title record (TITU) and EXLF syntax not confirmed.
    Returns complete file text as a string.
    """
    buses = network.get("buses", [])
    lines = network.get("lines", [])

    if not buses:
        raise ValueError("Rede sem barras.")

    # Build DBAR block
    Script_bat = []
    Script_Inclui_DBAR(
        Script_bat,
        vet_numero=[b["number"] for b in buses],
        vet_operacao=["A"] * len(buses),
        vet_estado=["L"] * len(buses),
        vet_tipo=[str(b.get("tipo", 0)) for b in buses],
        vet_GBT=[],
        vet_nome=[b.get("name", "BARRA")[:12] for b in buses],
        vet_GLT=[],
        vet_Tensao=[f"{b.get('v_pu', 1.0):.3f}" for b in buses],
        vet_Angulo=[f"{b.get('angle_deg', 0.0):.3f}" for b in buses],
        vet_geracao_P=[int(round(b.get("p_gen_mw", 0.0))) for b in buses],
        vet_geracao_Q=[],
        vet_limite_Q_min=[int(round(b.get("q_min_mvar", 0.0))) for b in buses],
        vet_limite_Q_max=[int(round(b.get("q_max_mvar", 0.0))) for b in buses],
        vet_Barra_Controlada=[],
        vet_carga_P=[int(round(b.get("p_load_mw", 0.0))) for b in buses],
        vet_carga_Q=[int(round(b.get("q_load_mvar", 0.0))) for b in buses],
        vet_Banco_Cap_Reat=[],
        vet_Area=[],
        vet_Tensao_def_carga=[],
    )
    dbar_text = "\n".join(Script_bat[0])

    if not lines:
        return dbar_text + "\n\nFIM"

    # Build DLIN block
    Script_lin = []
    Script_Inclui_DLIN(
        Script_lin,
        vet_tipo=["L"] * len(lines),
        vet_Barra_De=[ln["from_bus"] for ln in lines],
        vet_Abertura_De=[""] * len(lines),
        vet_operacao=["A"] * len(lines),
        vet_Barra_Para=[ln["to_bus"] for ln in lines],
        vet_Abertura_Para=[""] * len(lines),
        vet_circuito=[str(ln.get("circuit", 1)) for ln in lines],
        vet_estado=["L"] * len(lines),
        vet_proprietario=[""] * len(lines),
        vet_modo_controle=[""] * len(lines),
        vet_resistencia=[ln.get("r_pct", 0.0) for ln in lines],
        vet_reatancia=[ln.get("x_pct", 0.0) for ln in lines],
        vet_suceptancia=[ln.get("q_mvar", 0.0) for ln in lines],
        vet_tap=[],          # empty = plain transmission line (not transformer)
        vet_tap_min=[],
        vet_tap_max=[],
        vet_defasagem=[],
        vet_Barra_Controlada=[],
        vet_Capacidade_Normal=[],
        vet_Capacidade_Emergencia=[],
        vet_Numero_Taps=[],
        vet_Capacidade_Equipamento=[],
        vet_Numero_unidades=[],
        vet_unidades_operacao=[],
    )
    dlin_text = "\n".join(Script_lin[0])

    return dbar_text + "\n\n" + dlin_text + "\n\nFIM"


# ── D) Non-convergence diagnostics ───────────────────────────────────────────

# PENDING REVIEW BY DOMAIN EXPERT (Thomas): All diagnostic tips below are based
# on general power flow fundamentals. They must be reviewed and validated by
# Thomas before being presented to users as authoritative guidance.

def diagnose_nonconvergence(network, color):
    """
    Return an ordered checklist of likely causes and fixes for non-convergence,
    specific to this network.

    color: "red" (diverged) | "yellow" (iteration limit) | None (unknown)

    PENDING REVIEW BY DOMAIN EXPERT — tips are heuristic, not verified.
    """
    buses = network.get("buses", [])
    lines = network.get("lines", [])
    bus_map = {b["number"]: b for b in buses}

    issues = validate_network(network)
    errors = [i for i in issues if i["severity"] == "error"]

    checklist = []

    # If there are validation errors, report those first
    if errors:
        checklist.append(
            "**1. Erros de validação detectados** — corrija-os antes de tentar rodar o fluxo:\n"
            + "\n".join(f"   - {e['message']}" for e in errors)
        )

    # PENDING REVIEW BY DOMAIN EXPERT
    total_gen = sum(b.get("p_gen_mw", 0) for b in buses if b.get("tipo") in (1, 2))
    total_load = sum(b.get("p_load_mw", 0) for b in buses)

    if total_load > 0:
        if total_gen < total_load * 0.8:
            checklist.append(
                f"**{len(checklist)+1}. Desequilíbrio P severo** — geração total ({total_gen:.1f} MW) "
                f"é muito menor que a carga ({total_load:.1f} MW). "
                "A barra de referência assumirá todo o déficit, podendo causar ângulos extremos.\n"
                "→ Aumente a geração nas barras PV ou reduza a carga."
            )

    # PENDING REVIEW BY DOMAIN EXPERT
    high_load_buses = [
        b for b in buses if b.get("p_load_mw", 0) > total_gen * 0.7 and total_gen > 0
    ]
    for b in high_load_buses:
        checklist.append(
            f"**{len(checklist)+1}. Barra {b['number']} ({b.get('name','')})** tem carga de "
            f"{b.get('p_load_mw',0):.1f} MW — maior que 70% da geração total ({total_gen:.1f} MW). "
            "Isso pode causar divergência se a linha de conexão for muito fraca.\n"
            "→ Verifique a reatância da linha que alimenta esta barra."
        )

    # PENDING REVIEW BY DOMAIN EXPERT
    weak_lines = [
        ln for ln in lines if ln.get("x_pct", 0) > 20
    ]
    for ln in weak_lines:
        checklist.append(
            f"**{len(checklist)+1}. Linha {ln['id']} (barras {ln['from_bus']}–{ln['to_bus']})** "
            f"tem X = {ln.get('x_pct',0):.2f} % (linha eletricamente fraca). "
            "Linhas com alta reatância limitam o fluxo de potência e dificultam a convergência.\n"
            "→ Verifique se os parâmetros estão corretos."
        )

    # PENDING REVIEW BY DOMAIN EXPERT
    if color == "yellow":
        checklist.append(
            f"**{len(checklist)+1}. Limite de iterações atingido (amarelo)** — o algoritmo não divergiu, "
            "mas não convergiu dentro do número padrão de iterações.\n"
            "→ No ANAREDE: Análise > Cálculo de Fluxo de Potência → aumente o número de iterações para 100 ou 200.\n"
            "→ Tente também ativar o 'Flat Start' (tensões inicializadas em 1.0 pu, ângulos em zero)."
        )
    elif color == "red":
        checklist.append(
            f"**{len(checklist)+1}. Divergência numérica (vermelho)** — o algoritmo Newton-Raphson divergiu.\n"
            "→ Reduza as cargas ou gerações para valores menores e tente convergir incrementalmente.\n"
            "→ Verifique se alguma barra PV tem Qmax muito restritivo (valores baixos de Qmax forçam "
            "a barra a operar fora da faixa de controle)."
        )

    # PENDING REVIEW BY DOMAIN EXPERT
    pv_no_q = [b for b in buses if b.get("tipo") == 1 and b.get("q_max_mvar", 0) == 0]
    for b in pv_no_q:
        checklist.append(
            f"**{len(checklist)+1}. Barra PV {b['number']} ({b.get('name','')})** "
            "tem Qmax = 0 Mvar — sem capacidade de geração reativa, "
            "o controle de tensão desta barra estará inativo.\n"
            "→ Defina Qmin e Qmax adequados (ex: Qmin = -50, Qmax = 50 para uma barra de 100 MVA)."
        )

    if not checklist:
        checklist.append(
            "**Nenhuma causa óbvia detectada automaticamente.** Sugestões gerais:\n"
            "1. Verifique se os dados de R%, X% e Q foram inseridos nas unidades corretas.\n"
            "2. Tente reduzir todas as cargas para 10% e aumentar gradualmente até encontrar o limite.\n"
            "3. Certifique-se de que a barra de referência tem Qmin/Qmax liberados."
        )

    return checklist


# ── Network summary helpers ───────────────────────────────────────────────────

_TIPO_LABELS = {0: "PQ (carga)", 1: "PV (geração)", 2: "Referência"}


def format_network_summary(network):
    """Return a compact markdown summary table of buses and lines."""
    buses = network.get("buses", [])
    lines = network.get("lines", [])
    title = network.get("title", "Meu Caso")
    base_mva = network.get("base_mva", 100.0)

    lines_out = [
        f"**Caso:** {title} | **Base:** {base_mva} MVA\n",
        "**Barras:**",
        "| # | Nome | kV | Tipo | V (pu) | Pg (MW) | PL (MW) |",
        "|---|------|----|------|--------|---------|---------|",
    ]
    for b in buses:
        tipo_lbl = _TIPO_LABELS.get(b.get("tipo", 0), "?")
        lines_out.append(
            f"| {b['number']} | {b.get('name','')[:10]} | {b.get('kv',0):.0f} "
            f"| {tipo_lbl} | {b.get('v_pu',1.0):.3f} "
            f"| {b.get('p_gen_mw',0):.0f} | {b.get('p_load_mw',0):.0f} |"
        )

    if lines:
        lines_out += [
            "\n**Linhas:**",
            "| # | De | Para | Circ | R% | X% | Q (Mvar) |",
            "|---|----|----- |------|----|----|----------|",
        ]
        for ln in lines:
            lines_out.append(
                f"| {ln['id']} | {ln['from_bus']} | {ln['to_bus']} "
                f"| {ln.get('circuit',1)} "
                f"| {ln.get('r_pct',0):.4f} | {ln.get('x_pct',0):.4f} "
                f"| {ln.get('q_mvar',0):.4f} |"
            )

    return "\n".join(lines_out)
