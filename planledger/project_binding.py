from __future__ import annotations

"""Legacy Planledger-owned binding markers are no longer used.

Ledgercore 0.5.0 owns the ``.ledger-project.toml`` markers that mark config
and mount ownership. This module preserves read-only compatibility for any
external code that still imports the prior public names.
"""

from pathlib import Path

BINDING_FILENAME = ".ledger-project.toml"


def binding_path(data_root: Path) -> Path:
    return data_root / BINDING_FILENAME


__all__ = ["BINDING_FILENAME", "binding_path"]
