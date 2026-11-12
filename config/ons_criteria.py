"""
ONS criteria used by the ANATEM guide (v6.6.3).

Values copied ONLY from ONS — Procedimentos de Rede, Submódulo 2.3 (Critérios),
rev. 2026.04: Tabela 2 (item 2.4.1.11) and the criteria of item 2.4.3.7.
Never interpolated or extrapolated: a voltage that is not in the table has no time.

PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel)
"""

import re

ONS_SOURCE = "ONS — Procedimentos de Rede, Submódulo 2.3 (Critérios), rev. 2026.04"

# Tabela 2 (item 2.4.1.11): operating voltage (kV) → fault clearing time (ms) =
# relay operation + breaker opening.
# (kV, sem falha do disjuntor, com falha do disjuntor, teleproteção: None | True | False)
FAULT_CLEARING_TABLE = (
    (765, 80, 200, None),
    (525, 100, 250, None),
    (500, 100, 250, None),
    (440, 100, 250, None),
    (345, 100, 400, None),
    (230, 150, 500, None),
    (138, 150, 500, True),    # com teleproteção
    (138, 450, 750, False),   # sem teleproteção
    (88, 450, 750, False),    # sem teleproteção
    (69, 800, 1000, False),   # sem teleproteção
)
TABLE_KV = tuple(dict.fromkeys(row[0] for row in FAULT_CLEARING_TABLE))   # 765 … 69, no repeats
# Voltages with two rows (with / without teleprotection): the user must choose.
TELEPROTECTION_KV = tuple(kv for kv in TABLE_KV
                          if sum(1 for row in FAULT_CLEARING_TABLE if row[0] == kv) > 1)

# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel) — items 2.4.1.11 / 2.4.1.10
FAULT_TIME_CAVEAT = (
    "Valores **indicativos**: use-os apenas quando não houver informação no banco de dados do ONS. "
    "Os tempos reais dependem do arranjo da subestação e do tempo de atuação da proteção."
)
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel) — item 2.4.1.7
SIMULATION_TIME_NOTE = ("Tempo de simulação: o Submódulo 2.3 cita como usual uma simulação da ordem "
                        "de **15 segundos**.")
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel) — item 2.4.1.2
LINE_LOSS_TIP = ("Os Procedimentos de Rede pedem simular a abertura sem curto-circuito prévio e/ou com "
                 "aplicação de curto-circuito monofásico.")
# PENDING REVIEW BY DOMAIN EXPERT (Thomas/Gabriel) — item 2.4.1.11 / Tabela 2
NOT_IN_TABLE_TEXT = ("Essa tensão não está na Tabela 2 do Submódulo 2.3. Use o tempo informado pelo agente "
                     "ou pelo banco de dados do ONS.")

# Item 2.4.3.7: post-disturbance criteria checked at the ANATEM step AT12.
# (number, short label) — the full texts are in agents/anatem_flow.py (AT12).
POST_DISTURBANCE_CRITERIA = (
    (1, "Tensão mínima na 1ª oscilação"),
    (2, "Tensão mínima nas demais oscilações"),
    (3, "Variação tensão inicial/final"),
    (4, "Oscilação pico a pico após 10 s"),
)


def fault_clearing_times(kv, teleprotection=None):
    """(sem falha, com falha) in ms for a voltage of Tabela 2, or None when the voltage
    is not in the table. A voltage with two rows (138 kV) needs `teleprotection`
    (True/False); without it the answer is None."""
    rows = [row for row in FAULT_CLEARING_TABLE if row[0] == kv]
    if len(rows) > 1:
        rows = [row for row in rows if row[3] is teleprotection]
    if len(rows) != 1:
        return None
    return rows[0][1], rows[0][2]


_KV_RE = re.compile(r"(?<![\d.,])(\d{2,4})(?:[.,]0+)?(?![.,]?\d)\s*(?:kv\b)?", re.I)


def parse_kv(text):
    """'500', '500kV', '500 kV' → 500; None when no voltage is given (exactly one number)."""
    nums = _KV_RE.findall(str(text or ""))
    return int(nums[0]) if len(nums) == 1 else None
