"""Read-only diagnostics facade for the staged storage split."""

from __future__ import annotations

from typing import Any

from planledger.models import Workspace


def doctor(workspace: Workspace) -> dict[str, Any]:
    from planledger.storage import doctor as _doctor

    return _doctor(workspace)
