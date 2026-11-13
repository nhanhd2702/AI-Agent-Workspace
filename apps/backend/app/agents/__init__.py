"""Worker agent runtime package."""

from typing import Any
from app.agents.base import BaseWorkerAgent, SkillPathError, WorkerResult

__all__ = [
    "BaseWorkerAgent",
    "SkillPathError",
    "WorkerResult",
    "AgentResult",
    "ArtifactOutput",
    "FunnelsAgent",
    "GrowthAdvisorAgent",
    "UIDesignerAgent",
]


def __getattr__(name: str) -> Any:
    if name in {
        "FunnelsAgent",
        "GrowthAdvisorAgent",
        "UIDesignerAgent",
        "AgentResult",
        "ArtifactOutput",
    }:
        import app.agents.funnels as funnels_module

        val = getattr(funnels_module, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
