"""Read-only inventory facade for the staged storage split."""

from __future__ import annotations

from typing import Any

from planledger.models import Workspace


def collect_inventory(workspace: Workspace) -> dict[str, Any]:
    from planledger.storage import collect_inventory as _collect_inventory

    return _collect_inventory(workspace)
