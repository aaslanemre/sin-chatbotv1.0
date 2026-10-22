"""
Suggestion chips for commonly used values (v6.5.1, professor's request).

A chip shows a value the user can click to fill a form field; the user can still
edit it before submitting. A chip appears ONLY when an entry exists here.

Populated ONLY with values that already appear as examples in the app (help
texts, placeholders, defaults). Technical defaults — typical R, X, B per km by
voltage level, typical BESS/STATCOM ratings, typical loads — must be supplied by
the domain experts: those entries are deliberately empty (see TODO).

Entry: {"value": number | {form value key: number}, "label": str, "source": str,
        "status": "exemplo" | "PENDING REVIEW BY DOMAIN EXPERT" | "confirmado"}
Every numeric value respects ANAREDE's 4-decimal limit.
"""

EXEMPLO = "exemplo"
PENDING = "PENDING REVIEW BY DOMAIN EXPERT"
CONFIRMADO = "confirmado"
STATUSES = (EXEMPLO, PENDING, CONFIRMADO)


def _e(value, label, source, status=EXEMPLO):
    return {"value": value, "label": label, "source": source, "status": status}


_KV_SOURCE = "Ajuda da tensão nominal: “Tensões padrão do SIN: 138, 230, 345, 440, 500, 765 kV”"

SUGGESTIONS = {
    # NET1 — base MVA (app default and help text "O padrão no Brasil é 100 MVA")
    "net_base_mva": [_e(100, "100 MVA", "Padrão do app (NET1) e ajuda: “O padrão no Brasil é 100 MVA”")],
    # NET2 — bus data
    "net_bus_voltage_kv": [_e(kv, f"{kv} kV", _KV_SOURCE) for kv in (138, 230, 345, 440, 500, 765)],
    "net_vset_pu": [_e(1.02, "1.02 pu", "Exemplo do app para a tensão setpoint (ex: 1.02)")],
    "net_vref_pu": [_e(1.05, "1.05 pu", "Exemplo do app para a tensão de referência (ex: 1.05)")],
    "net_q_limits": [_e({"qmin": -100, "qmax": 100}, "Qmin −100 / Qmax 100 Mvar",
                        "Exemplos do app para Qmin (ex: -100) e Qmax (ex: 100)")],
    "net_bus_pg_mw": [],      # TODO(domain experts): typical generation per bus — not an app example
    "net_bus_load": [],       # TODO(domain experts): typical P/Q load per bus — not an app example
    # NET3 — lines
    "net_line_circuit": [_e(1, "1", "Texto do app: circuito “normalmente 1”")],
    "line_params_per_km_by_kv": {
        230: [_e({"r": 0.0257, "x": 0.2995, "b": 5.4542, "l": 180},
                 "LT 230 kV, 180 km: R 0.0257 · X 0.2995 Ω/km · B 5.4542 μS/km",
                 "Exemplo de ajuda do app (linha de 230 kV / 180 km)")],
        # TODO(domain experts): typical R (Ω/km), X (Ω/km), B (μS/km) for 138, 345,
        # 440, 500 and 765 kV. Do not fill in without expert review.
    },
    "line_params_pu": [_e({"r": 0.001, "x": 0.05, "b": 0.02}, "R 0.001 · X 0.05 · B 0.02 pu",
                          "Exemplo de ajuda do app (modo pu)")],
    "line_params_pct": [_e({"r": 0.87, "x": 10.19, "q": 51.93}, "R 0.87 % · X 10.19 % · Q 51.93 Mvar",
                           "Exemplo de ajuda do app (modo %/Mvar)")],
    # STATCOM
    "statcom_q_limits": [_e({"qmin": -100, "qmax": 100}, "Qmin −100 / Qmax 100 Mvar",
                            "Exemplo do app: “Qmin -100 Mvar, Qmax 100 Mvar”")],
    # BESS
    "bess_mva": [],           # TODO(domain experts): typical BESS ratings — not an app example
    "bess_p_mw": [],          # TODO(domain experts)
}
