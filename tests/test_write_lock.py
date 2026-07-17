"""Planledger write-lock tests.

Covers plan section 24.8: mutating commands acquire/release the write
lock; read-only commands do not; the lock records PID, command,
timestamp, and project UUID; stale and malformed locks are reported; a
failed command releases its own lock; another live process's lock is
never removed automatically.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from planledger.errors import PlanledgerError
from planledger.write_lock import (
    acquire_planledger_write_lock,
    inspect_write_lock,
    require_planledger_quiescent,
    unlink_write_lock,
    write_lock_path,
)


def _project_root(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


def test_acquire_creates_lock_with_required_fields(tmp_path: Path) -> None:
    project = _project_root(tmp_path)
    with acquire_planledger_write_lock(
        project, command="init", project_uuid="00000000-0000-4000-8000-000000000001"
    ):
        snapshot = inspect_write_lock(project)
    assert snapshot.held is True
    assert snapshot.command == "init"
    assert snapshot.project_uuid == "00000000-0000-4000-8000-000000000001"
    assert snapshot.pid is not None
    assert snapshot.hostname is not None
    assert snapshot.claimed_at is not None


def test_acquire_releases_lock_on_exit(tmp_path: Path) -> None:
    project = _project_root(tmp_path)
    with acquire_planledger_write_lock(
        project, command="init", project_uuid="00000000-0000-4000-8000-000000000002"
    ):
        pass
    snapshot = inspect_write_lock(project)
    assert snapshot.held is False


def test_acquire_fails_when_other_writer_holds_lock(tmp_path: Path) -> None:
    project = _project_root(tmp_path)
    with acquire_planledger_write_lock(
        project, command="init", project_uuid="00000000-0000-4000-8000-000000000003"
    ):
        # Simulate a different live process holding the lock.
        path = write_lock_path(project)
        existing = json.loads(path.read_text(encoding="utf-8"))
        # Use a clearly different PID that is alive.
        existing["pid"] = 1  # init is alive on every POSIX system
        path.write_text(json.dumps(existing, indent=2, sort_keys=True))
        with pytest.raises(PlanledgerError) as exc:
            with acquire_planledger_write_lock(
                project,
                command="plan create",
                project_uuid="00000000-0000-4000-8000-000000000003",
            ):
                pass
        assert exc.value.code == "PLANLEDGER_STORAGE_MIGRATION_ACTIVE_WRITER"


def test_acquire_tolerates_own_lock_reacquisition(tmp_path: Path) -> None:
    project = _project_root(tmp_path)
    with acquire_planledger_write_lock(
        project, command="init", project_uuid="00000000-0000-4000-8000-000000000004"
    ):
        # Re-acquire is allowed because the same process already holds the
        # lock.
        with acquire_planledger_write_lock(
            project,
            command="init",
            project_uuid="00000000-0000-4000-8000-000000000004",
        ):
            snapshot = inspect_write_lock(project)
            assert snapshot.held is True
            assert snapshot.is_self is True


def test_unlink_only_removes_own_lock(tmp_path: Path) -> None:
    project = _project_root(tmp_path)
    path = write_lock_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pid": 1,  # init, alive
                "command": "other",
                "claimed_at": "2026-01-01T00:00:00Z",
                "project_uuid": "00000000-0000-4000-8000-000000000099",
                "hostname": "other",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    # Attempting to unlink with require_pids that do not match the holder
    # is a no-op.
    unlink_write_lock(project, require_pids=(99999,))
    assert path.is_file()


def test_inspect_reports_malformed_lock(tmp_path: Path) -> None:
    project = _project_root(tmp_path)
    path = write_lock_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(PlanledgerError) as exc:
        inspect_write_lock(project)
    assert exc.value.code == "PLANLEDGER_WRITE_LOCK_INVALID"


def test_require_quiescent_rejects_other_live_writer(tmp_path: Path) -> None:
    project = _project_root(tmp_path)
    path = write_lock_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pid": 1,
                "command": "other",
                "claimed_at": "2026-01-01T00:00:00Z",
                "project_uuid": "00000000-0000-4000-8000-000000000098",
                "hostname": "other",
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    with pytest.raises(PlanledgerError) as exc:
        require_planledger_quiescent(project)
    assert exc.value.code == "PLANLEDGER_STORAGE_MIGRATION_ACTIVE_WRITER"


def test_require_quiescent_accepts_unlocked_project(tmp_path: Path) -> None:
    project = _project_root(tmp_path)
    # No lock file; must not raise.
    require_planledger_quiescent(project)


def test_acquire_releases_on_exception(tmp_path: Path) -> None:
    project = _project_root(tmp_path)
    with pytest.raises(RuntimeError):
        with acquire_planledger_write_lock(
            project,
            command="init",
            project_uuid="00000000-0000-4000-8000-000000000005",
        ):
            raise RuntimeError("boom")
    snapshot = inspect_write_lock(project)
    assert snapshot.held is False


def test_snapshot_to_dict_round_trip(tmp_path: Path) -> None:
    project = _project_root(tmp_path)
    with acquire_planledger_write_lock(
        project, command="init", project_uuid="00000000-0000-4000-8000-000000000006"
    ):
        snapshot = inspect_write_lock(project)
    data = snapshot.to_dict()
    assert data["held"] is True
    assert data["command"] == "init"
    assert data["project_uuid"] == "00000000-0000-4000-8000-000000000006"


def test_lock_path_lives_in_planledger_config_dir(tmp_path: Path) -> None:
    project = _project_root(tmp_path)
    path = write_lock_path(project)
    assert path == project / ".ledger" / "planledger" / "write.lock"
