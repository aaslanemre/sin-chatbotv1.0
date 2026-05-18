"""
Handles PWF file parsing, modification, and download.

PWF is a plain ASCII text file used by Anarede.
The DBAR section contains bus data. To add a BESS as a generator,
we insert a new line in the DBAR section with the appropriate fields.
"""
from pathlib import Path
from datetime import datetime
from config.settings import MODIFIED_PWF_DIR

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


def add_bess_to_dbar(
    pwf_content: str,
    bus_number: int,
    bus_name: str,
    active_power_mw: float,
) -> str:
    """
    Inserts a BESS generator line into the DBAR section of a PWF file.
    BESS is modeled as a PV generator (type 1) with voltage control disabled.

    DBAR line format (fixed-width ASCII):
    Cols 1-5:   bus number
    Cols 6:     operation (0=keep)
    Cols 7:     type (1=PV generator, 0=PQ load, 2=slack)
    Cols 9-20:  bus name (12 chars)
    Cols 21-24: base voltage (kV)
    Cols 55-58: active power generation (MW)
    Cols 59-62: reactive power generation (Mvar)
    """
    lines = pwf_content.splitlines()
    dbar_end_idx = None

    for i, line in enumerate(lines):
        if line.strip().startswith("DBAR"):
            for j in range(i + 1, len(lines)):
                if lines[j].strip().startswith("99999"):
                    dbar_end_idx = j
                    break
            break

    if dbar_end_idx is None:
        raise ValueError("DBAR section not found in PWF file.")

    bess_line = (
        f"{bus_number:5d}"
        f"0"
        f"1"
        f" "
        f"{bus_name:<12s}"
        f"{'':>30s}"
        f"{active_power_mw:4.0f}"
        f"{'':>20s}"
    )

    lines.insert(dbar_end_idx, bess_line)
    return "\n".join(lines)


def write_modified_pwf(content: str, original_name: str) -> Path:
    """Write modified PWF to disk and return the path."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = Path(original_name).stem
    output_path = MODIFIED_DIR / f"{stem}_BESS_{timestamp}.pwf"
    output_path.write_text(content, encoding="latin-1")
    return output_path


def generate_bess_pwf(
    pwf_path: Path,
    bus_number: int,
    bus_name: str,
    active_power_mw: float,
) -> tuple:
    """
    Full pipeline: read → modify → write → return (file_path, preview).
    Returns the path to the new PWF file and a preview of the DBAR section.
    """
    content = read_pwf(pwf_path)
    modified = add_bess_to_dbar(content, bus_number, bus_name, active_power_mw)
    out_path = write_modified_pwf(modified, pwf_path.name)

    lines = modified.splitlines()
    preview_lines = []
    in_dbar = False
    count = 0
    for line in lines:
        if line.strip().startswith("DBAR"):
            in_dbar = True
        if in_dbar:
            preview_lines.append(line)
            count += 1
            if count > 30:
                break

    return out_path, "\n".join(preview_lines)
