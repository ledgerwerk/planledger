from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class AppContext:
    root: Path | None
    cwd: Path | None
    json_output: bool


@dataclass
class Workspace:
    root: Path
    config_path: Path
    planledger_dir: Path
    storage_path: Path
    ledger_ref: str
    ledger_dir: Path
    config: dict[str, Any]


@dataclass
class Record:
    kind: str
    record_id: str
    path: Path
    front_matter: dict[str, Any]
    body: str
