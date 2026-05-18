"""
Parses Anarede output (text) file and checks for convergence.
Anarede outputs a plain text report — convergence is indicated by
specific keywords in the output.
"""
from pathlib import Path
from config.settings import RESULTS_DIR

RESULTS_PATH = Path(RESULTS_DIR)
RESULTS_PATH.mkdir(parents=True, exist_ok=True)

CONVERGENCE_KEYWORDS = [
    "CONVERGENCIA ALCANCADA",
    "SOLUCAO CONVERGIDA",
    "CONVERGÊNCIA ALCANÇADA",
    "CONVERGIDO",
]

DIVERGENCE_KEYWORDS = [
    "NAO CONVERGIU",
    "NÃO CONVERGIU",
    "DIVERGENCIA",
    "DIVERGÊNCIA",
    "ITERACOES MAXIMAS",
    "ITERAÇÕES MÁXIMAS",
]

CONVERGENCE_TIPS = [
    "Tente salvar o caso atual como arquivo SAV antes de executar novamente.",
    "Desative flags de limite de reativos (QLIM) para facilitar a convergência inicial.",
    "Reduza a potência injetada pelo BESS e aumente gradualmente.",
    "Verifique se as tensões iniciais das barras estão dentro de limites razoáveis (0.9 a 1.1 pu).",
    "Utilize o método de Newton-Raphson com passo reduzido (NRPM).",
    "Verifique se há barras ilhadas ou sem referência de tensão (slack ausente).",
]


def save_results_file(uploaded_file, filename: str) -> Path:
    dest = RESULTS_PATH / filename
    dest.write_bytes(uploaded_file.read())
    return dest


def check_convergence(results_path: Path) -> dict:
    """
    Parse Anarede output file and return convergence status + details.
    """
    try:
        content = results_path.read_text(encoding="latin-1", errors="ignore")
    except Exception as e:
        return {
            "converged": False,
            "evidence": f"Could not read file: {e}",
            "tips": CONVERGENCE_TIPS,
            "voltage_violations": [],
            "overloaded_lines": [],
        }

    lines = content.splitlines()
    converged = False
    evidence = "No convergence indicator found in output file."

    for line in lines:
        upper = line.upper()
        if any(kw in upper for kw in CONVERGENCE_KEYWORDS):
            converged = True
            evidence = line.strip()
            break
        if any(kw in upper for kw in DIVERGENCE_KEYWORDS):
            converged = False
            evidence = line.strip()
            break

    voltage_violations = []
    overloaded_lines = []
    for line in lines:
        upper = line.upper()
        if "TENSAO FORA" in upper or "VIOLACAO DE TENSAO" in upper:
            voltage_violations.append(line.strip())
        if "SOBRECARGA" in upper or "FLUXO ACIMA" in upper:
            overloaded_lines.append(line.strip())

    return {
        "converged": converged,
        "evidence": evidence,
        "tips": [] if converged else CONVERGENCE_TIPS,
        "voltage_violations": voltage_violations[:10],
        "overloaded_lines": overloaded_lines[:10],
    }


def format_results_report(analysis: dict) -> str:
    """Format analysis dict into a readable chat message."""
    if analysis["converged"]:
        report = "Simulação convergiu com sucesso.\n\n"
        report += f"Indicador encontrado: `{analysis['evidence']}`\n\n"
        if analysis["voltage_violations"]:
            report += f"Violações de tensão detectadas ({len(analysis['voltage_violations'])}):\n"
            for v in analysis["voltage_violations"]:
                report += f"  • {v}\n"
        else:
            report += "Nenhuma violação de tensão detectada.\n"
        if analysis["overloaded_lines"]:
            report += f"\nLinhas sobrecarregadas ({len(analysis['overloaded_lines'])}):\n"
            for line in analysis["overloaded_lines"]:
                report += f"  • {line}\n"
        else:
            report += "Nenhuma sobrecarga de linha detectada.\n"
    else:
        report = "A simulação NÃO convergiu.\n\n"
        report += f"Indicador: `{analysis['evidence']}`\n\n"
        report += "Sugestões para resolver o problema de convergência:\n"
        for i, tip in enumerate(analysis["tips"], 1):
            report += f"{i}. {tip}\n"

    return report
