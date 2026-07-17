from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanledgerError(Exception):
    code: str
    message: str
    remediation: list[str] = field(default_factory=list)
    exit_code: int = 1
    details: dict[str, object] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.code

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "code": self.code,
            "message": self.message,
            "remediation": list(self.remediation),
        }
        if self.details:
            data["details"] = {str(k): v for k, v in self.details.items()}
        return data
