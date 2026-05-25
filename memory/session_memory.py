"""
In-memory study state. Lives for the duration of one chat session.
Cleared when user clicks 'Clear conversation'.
"""
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class StudyState:
    objective: Optional[str] = None
    sin_area: Optional[str] = None
    technology: Optional[str] = None
    scenarios: List[str] = field(default_factory=list)
    modification_needed: Optional[bool] = None
    contingencies: List[str] = field(default_factory=list)
    last_convergence: Optional[bool] = None
    study_type: Optional[str] = None  # "static" | "dynamic" | "energetic"

    def summary(self) -> str:
        """Returns a string injected into the LLM context."""
        parts = []
        if self.objective:
            parts.append(f"Study objective: {self.objective}")
        if self.technology:
            parts.append(f"Technology: {self.technology}")
        if self.sin_area:
            parts.append(f"SIN area: {self.sin_area}")
        if self.scenarios:
            parts.append(f"Scenarios: {', '.join(self.scenarios)}")
        if self.contingencies:
            parts.append(f"Contingencies: {', '.join(self.contingencies)}")
        if self.last_convergence is not None:
            parts.append(
                f"Last simulation: {'converged' if self.last_convergence else 'did not converge'}"
            )
        return "\n".join(parts) if parts else "No study context defined yet."

    def to_dict(self) -> dict:
        return {
            "objective": self.objective,
            "sin_area": self.sin_area,
            "technology": self.technology,
            "scenarios": self.scenarios,
            "modification_needed": self.modification_needed,
            "contingencies": self.contingencies,
            "last_convergence": self.last_convergence,
            "study_type": self.study_type,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StudyState":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)
