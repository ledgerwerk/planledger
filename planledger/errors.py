from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanledgerError(Exception):
    kind: str
    message: str
    remediation: list[str] = field(default_factory=list)
    exit_code: int = 1

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "kind": self.kind,
            "message": self.message,
        }
        if self.remediation:
            data["remediation"] = self.remediation
        return data
