from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

from planledger.project_context import Workspace as Workspace

PlanStatus = Literal["new", "in_progress", "rework", "cancelled", "done"]
WorkshopStatus = Literal["new", "exploring", "shaped", "planned", "cancelled"]


@dataclass
class AppContext:
    root: Path | None
    cwd: Path | None
    json_output: bool


__all__ = ["AppContext", "Workspace", "ComponentSpec", "Plan", "Workshop"]


@dataclass
class ComponentSpec:
    key: str
    path: str
    title: str
    order: int
    required: bool
    sha256: str | None = None


@dataclass
class Plan:
    plan_id: str
    path: Path
    metadata: dict[str, Any]
    components: dict[str, ComponentSpec] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return str(self.metadata.get("title") or "")

    @property
    def status(self) -> PlanStatus:
        value = self.metadata.get("status", "new")
        if not isinstance(value, str):
            return "new"
        return cast(PlanStatus, value)

    @property
    def version(self) -> int:
        return int(self.metadata.get("version", 0))


@dataclass
class Workshop:
    workshop_id: str
    path: Path
    metadata: dict[str, Any]
    components: dict[str, ComponentSpec] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return str(self.metadata.get("title") or "")

    @property
    def status(self) -> WorkshopStatus:
        value = self.metadata.get("status", "new")
        if not isinstance(value, str):
            return "new"
        return cast(WorkshopStatus, value)

    @property
    def version(self) -> int:
        return int(self.metadata.get("version", 0))
