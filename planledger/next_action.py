"""Public next-action facade for the staged storage split."""

from __future__ import annotations

from typing import Any

from planledger.models import Workspace


def compute_next_action(
    workspace: Workspace | None, plan_id: str | None = None
) -> dict[str, Any]:
    from planledger.storage import compute_next_action as _compute_next_action

    return _compute_next_action(workspace, plan_id)
