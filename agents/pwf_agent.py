"""
Handles PWF file parsing, modification, and download.

PWF is a plain ASCII text file used by Anarede.
The DBAR section contains bus data. To add a BESS as a generator,
we insert a new line in the DBAR section with the appropriate fields.
"""
from pathlib import Path
from datetime import datetime
from config.settings import MODIFIED_PWF_DIR
from utils.anarede_lib import (
    Script_Inclui_DBAR,
    Script_Inclui_DLIN,
    Script_Inclui_DCER,
    calculate_q_limits,
    format_ansi_field,
    COUPLING_LINE_X_PCT,
)

MODIFIED_DIR = Path(MODIFIED_PWF_DIR)
MODIFIED_DIR.mkdir(parents=True, exist_ok=True)


def read_pwf(pwf_path: Path) -> str:
    """Read PWF file content (latin-1 encoding is standard for Anarede)."""
    return pwf_path.read_text(encoding="latin-1")


def preview_pwf(pwf_path: Path, max_lines: int = 50) -> str:
    """Return first N lines for display in UI."""
    lines = read_pwf(pwf_path).splitlines()
    preview = "\n".join(lines[:max_lines])
    if len(lines) > max_lines:
        preview += f"\n... ({len(lines) - max_lines} more lines)"
    return preview


def generate_dbar_block(bus_number, bess_bus_number, bus_type, S_mva, P_mw):
    """
    bus_number: int — existing network bus (bus_from for DLIN)
    bess_bus_number: int — new BESS bus number
    bus_type: str — '1' for PV, '0' for PQ
    S_mva: float — apparent power in MVA
    P_mw: float — active power in MW
    Returns combined DBAR + DLIN + FIM as a single string.
    """
    return generate_bess_block([{"bus_number": bus_number, "bess_bus_number": bess_bus_number,
                                 "bus_type": bus_type, "S_mva": S_mva, "P_mw": P_mw}])


def generate_bess_block(devices):
    """
    One file for N BESS (v6.5.1): DBAR block with one new bus per device, DLIN
    block with one coupling line per device (same single-device rules: tipo
    PQ=0 / PV=1 in the DBAR, line operação A / estado L, empty TAP, reactance
    COUPLING_LINE_X_PCT, R = B = 0), one 99999 per block, FIM at the end.
    devices: list of dicts with the generate_dbar_block arguments.
    """
    limits = [calculate_q_limits(d["S_mva"], d["P_mw"]) for d in devices]
    n = len(devices)

    # Generate DBAR
    Script_bat = []
    Script_Inclui_DBAR(
        Script_bat,
        vet_numero=[d["bess_bus_number"] for d in devices],
        vet_operacao=['A'] * n,
        vet_estado=['L'] * n,
        vet_tipo=[d["bus_type"] for d in devices],
        vet_GBT=[],
        vet_nome=['BESS'] * n,
        vet_GLT=[],
        vet_Tensao=[],
        vet_Angulo=[],
        vet_geracao_P=[int(round(float(d["P_mw"]))) for d in devices],
        vet_geracao_Q=[],
        vet_limite_Q_min=[int(round(float(q_min))) for q_min, _ in limits],
        vet_limite_Q_max=[int(round(float(q_max))) for _, q_max in limits],
        vet_Barra_Controlada=[],
        vet_carga_P=[],
        vet_carga_Q=[],
        vet_Banco_Cap_Reat=[],
        vet_Area=[],
        vet_Tensao_def_carga=[]
    )
    dbar_block = "\n".join(Script_bat[0])

    # Generate DLIN using proper library function
    Script_lin = []
    Script_Inclui_DLIN(
        Script_lin,
        vet_tipo=['L'] * n,
        vet_Barra_De=[d["bus_number"] for d in devices],
        vet_Abertura_De=[''] * n,
        vet_operacao=['A'] * n,
        vet_Barra_Para=[d["bess_bus_number"] for d in devices],
        vet_Abertura_Para=[''] * n,
        vet_circuito=['1'] * n,
        vet_estado=['L'] * n,
        vet_proprietario=[''] * n,
        vet_modo_controle=[''] * n,
        vet_resistencia=[0.0] * n,
        vet_reatancia=[COUPLING_LINE_X_PCT] * n,
        vet_suceptancia=[0.0] * n,
        vet_tap=[],
        vet_tap_min=[],
        vet_tap_max=[],
        vet_defasagem=[],
        vet_Barra_Controlada=[],
        vet_Capacidade_Normal=[],
        vet_Capacidade_Emergencia=[],
        vet_Numero_Taps=[],
        vet_Capacidade_Equipamento=[],
        vet_Numero_unidades=[],
        vet_unidades_operacao=[]
    )
    dlin_block = "\n".join(Script_lin[0])

    return dbar_block + "\n\n" + dlin_block + "\n\nFIM"


def generate_statcom_block(bus_number, q_min, q_max,
                           controlled_bus=None,
                           droop=0.0, units=1):
    """
    Generate DBAR + DCER blocks for STATCOM insertion.
    bus_number: int — bus where STATCOM connects
    q_min: float — minimum reactive generation (Mvar)
    q_max: float — maximum reactive generation (Mvar)
    controlled_bus: int — remote bus to control (None=local)
    droop: float — slope in %
    units: int — number of units
    Returns combined DBAR + DCER + FIM as string.
    """
    Script_bat = []
    Script_Inclui_DBAR(
        Script_bat,
        vet_numero=[bus_number],
        vet_operacao=['A'],
        vet_estado=['L'],
        vet_tipo=['1'],
        vet_GBT=[],
        vet_nome=['STATCOM'],
        vet_GLT=[],
        vet_Tensao=[],
        vet_Angulo=[],
        vet_geracao_P=[0],
        vet_geracao_Q=[],
        vet_limite_Q_min=[int(round(float(q_min)))],
        vet_limite_Q_max=[int(round(float(q_max)))],
        vet_Barra_Controlada=[controlled_bus or bus_number],
        vet_carga_P=[],
        vet_carga_Q=[],
        vet_Banco_Cap_Reat=[],
        vet_Area=[],
        vet_Tensao_def_carga=[]
    )
    dbar_block = "\n".join(Script_bat[0])

    Script_cer = []
    Script_Inclui_DCER(
        Script_cer,
        vet_barra=[bus_number],
        vet_operacao=['A'],
        vet_grupo=[1],
        vet_unidades=[units],
        vet_barra_controlada=[controlled_bus or bus_number],
        vet_inclinacao=[droop],
        vet_geracao_Q=[0],
        vet_limite_Q_min=[int(round(float(q_min)))],
        vet_limite_Q_max=[int(round(float(q_max)))],
        vet_modo_controle=['I'],
        vet_estado=['L'],
        vet_modo_correcao=['L']
    )
    dcer_block = "\n".join(Script_cer[0])

    return dbar_block + "\n\n" + dcer_block + "\n\nFIM"


def generate_contingency_block(contingencies):
    """
    contingencies: list of dicts with keys:
      - id: int (contingency number)
      - name: str
      - type: 'line' or 'generator'
      - bus_from: int (for line)
      - bus_to: int (for line)
      - circuit: int (default 1)
      - bus: int (for generator)
    Returns DCTG block as string.
    """
    lines = ['DCTG']
    for c in contingencies:
        id_str = format_ansi_field(int(c['id']), 4)
        name = c.get('name', f"CTG{c['id']}")[:46]
        lines.append(f"{id_str}   {name}")
        if c['type'] == 'line':
            bf = format_ansi_field(int(c['bus_from']), 5)
            bt = format_ansi_field(int(c['bus_to']), 5)
            ci = format_ansi_field(int(c.get('circuit', 1)), 2)
            lines.append(f"CIRD {bf} {bt} {ci}")
        elif c['type'] == 'generator':
            b = format_ansi_field(int(c['bus']), 5)
            lines.append(f"GERA  {b}")
        lines.append('FCAS')
    lines.append('99999')
    return '\n'.join(lines)


def write_modified_pwf(content: str, original_name: str) -> Path:
    """Write modified PWF to disk and return the path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = Path(original_name).stem
    output_path = MODIFIED_DIR / f"{stem}_BESS_{timestamp}.pwf"
    output_path.write_text(content, encoding="latin-1")
    return output_path
