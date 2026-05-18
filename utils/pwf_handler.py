"""
Handles .pwf files uploaded by the user.
Saves them to a local folder and provides a text preview.
"""
from pathlib import Path

PWF_UPLOAD_DIR = Path("uploaded_pwf")
PWF_UPLOAD_DIR.mkdir(exist_ok=True)


def save_pwf(uploaded_file) -> Path:
    """Save a Streamlit UploadedFile to disk. Returns the saved path."""
    dest = PWF_UPLOAD_DIR / uploaded_file.name
    dest.write_bytes(uploaded_file.read())
    return dest


def preview_pwf(pwf_path: Path, max_lines: int = 50) -> str:
    """Return the first max_lines lines of a .pwf file as a string."""
    try:
        lines = pwf_path.read_text(encoding="latin-1").splitlines()
        preview = "\n".join(lines[:max_lines])
        if len(lines) > max_lines:
            preview += f"\n... ({len(lines) - max_lines} linhas adicionais)"
        return preview
    except Exception as e:
        return f"Erro ao ler arquivo PWF: {e}"
