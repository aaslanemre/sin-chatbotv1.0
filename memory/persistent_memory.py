"""
Saves last study state to JSON between sessions.
Loads automatically on app start. Cleared when user starts a new study.
"""
import json
from pathlib import Path
from memory.session_memory import StudyState
from config.settings import MEMORY_STORE_PATH

STORE = Path(MEMORY_STORE_PATH)


def save_study(state: StudyState):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(state.to_dict(), indent=2))


def load_study() -> StudyState:
    if not STORE.exists():
        return StudyState()
    try:
        data = json.loads(STORE.read_text())
        return StudyState.from_dict(data)
    except Exception:
        return StudyState()


def clear_study():
    if STORE.exists():
        STORE.unlink()
