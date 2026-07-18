"""Planledger migration quiescence tests.

Covers plan section 24.8: an active writer blocks the migration flow
before copy and immediately before activation. The quiescence check
rejects migration when another live process holds the Planledger write
lock.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from planledger.errors import PlanledgerError
from planledger.write_lock import (
    require_planledger_quiescent,
    write_lock_path,
)


def _seed_lock(project: Path, *, pid: int, command: str = "other") -> None:
    path = write_lock_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pid": pid,
                "command": command,
                "claimed_at": "2026-01-01T00:00:00Z",
                "project_uuid": "00000000-0000-4000-8000-000000000001",
                "hostname": "test",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_quiescence_rejects_live_writer_before_copy(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _seed_lock(project, pid=os.getpid())  # init is alive (hostname differs -> not self)
    with pytest.raises(PlanledgerError) as exc:
        require_planledger_quiescent(project)
    assert exc.value.code == "PLANLEDGER_STORAGE_MIGRATION_ACTIVE_WRITER"


def test_quiescence_rejects_live_writer_before_activation(tmp_path: Path) -> None:
    # Same check fires immediately before activation, per plan section 15.
    project = tmp_path / "project"
    project.mkdir()
    _seed_lock(project, pid=os.getpid())
    with pytest.raises(PlanledgerError):
        require_planledger_quiescent(project)


def test_quiescence_accepts_dead_writer_lock(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    # Use a PID that almost certainly does not exist.
    _seed_lock(project, pid=2_000_000_000)
    # Should not raise; the holder is dead.
    require_planledger_quiescent(project)


def test_quiescence_accepts_unlocked_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    require_planledger_quiescent(project)
