"""Planledger write guard with exclusive semantics for mutating commands.

The guard lives at ``.ledger/planledger/write.lock`` and tracks the holder's
PID, command name, claim timestamp, and project UUID. Read-only commands do not
acquire the guard. Migration acquires the guard exclusively for the entire
critical section; ``quiescence_check`` rejects the migration when another live
process holds the lock.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if sys.platform != "win32":
    import fcntl

from planledger.errors import PlanledgerError

WRITE_LOCK_FILENAME = "write.lock"
DEFAULT_LOCK_STALE_SECONDS = 6 * 60 * 60


@dataclass(frozen=True, slots=True)
class WriteLockSnapshot:
    path: Path
    held: bool
    pid: int | None
    command: str | None
    claimed_at: str | None
    project_uuid: str | None
    hostname: str | None
    age_seconds: float | None
    is_self: bool
    is_live: bool | None

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "held": self.held,
            "pid": self.pid,
            "command": self.command,
            "claimed_at": self.claimed_at,
            "project_uuid": self.project_uuid,
            "hostname": self.hostname,
            "age_seconds": self.age_seconds,
            "is_self": self.is_self,
            "is_live": self.is_live,
        }


def _now_iso() -> str:
    from ledgercore.time import utc_now_iso

    return utc_now_iso()


def write_lock_path(project_root: Path) -> Path:
    return project_root / ".ledger" / "planledger" / WRITE_LOCK_FILENAME


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def inspect_write_lock(
    project_root: Path,
    *,
    now_ts: float | None = None,
    stale_seconds: float = DEFAULT_LOCK_STALE_SECONDS,
) -> WriteLockSnapshot:
    path = write_lock_path(project_root)
    if not path.is_file():
        return WriteLockSnapshot(
            path=path,
            held=False,
            pid=None,
            command=None,
            claimed_at=None,
            project_uuid=None,
            hostname=None,
            age_seconds=None,
            is_self=False,
            is_live=None,
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanledgerError(
            "PLANLEDGER_WRITE_LOCK_INVALID",
            f"Planledger write lock is not readable: {path}.",
            details={"path": str(path), "reason": str(exc)},
        ) from exc
    pid_obj = document.get("pid")
    pid = pid_obj if isinstance(pid_obj, int) else None
    claimed_at = document.get("claimed_at")
    claimed_iso = claimed_at if isinstance(claimed_at, str) else None
    age_seconds: float | None = None
    if claimed_iso is not None:
        try:
            from datetime import datetime, timezone

            cleaned = claimed_iso.replace("Z", "+00:00")
            claimed_dt = datetime.fromisoformat(cleaned)
            claimed_ts = claimed_dt.astimezone(timezone.utc).timestamp()
            age_seconds = max(0.0, (now_ts or time.time()) - claimed_ts)
        except (TypeError, ValueError):
            age_seconds = None
    host = socket.gethostname()
    is_self = pid == os.getpid() and document.get("hostname") == host
    is_live: bool | None = None
    if pid is not None:
        is_live = _pid_alive(pid)
    stale = age_seconds is not None and age_seconds > stale_seconds
    if stale and not is_live:
        is_live = False
    return WriteLockSnapshot(
        path=path,
        held=True,
        pid=pid,
        command=document.get("command")
        if isinstance(document.get("command"), str)
        else None,
        claimed_at=claimed_iso,
        project_uuid=document.get("project_uuid")
        if isinstance(document.get("project_uuid"), str)
        else None,
        hostname=document.get("hostname")
        if isinstance(document.get("hostname"), str)
        else None,
        age_seconds=age_seconds,
        is_self=is_self,
        is_live=is_live,
    )


@contextmanager
def acquire_planledger_write_lock(
    project_root: Path,
    *,
    command: str,
    project_uuid: str,
) -> Iterator[WriteLockSnapshot]:
    """Acquire the Planledger write lock for the duration of the context.

    Raises PLANLEDGER_STORAGE_MIGRATION_ACTIVE_WRITER when another live writer
    holds the lock. Releases the lock on exit. Does not delete another live
    process's lock.
    """
    current = inspect_write_lock(project_root)
    if current.held:
        if current.is_self:
            yield current
            return
        if current.is_live:
            raise PlanledgerError(
                "PLANLEDGER_STORAGE_MIGRATION_ACTIVE_WRITER",
                "Planledger writes are blocked by an active writer.",
                remediation=[
                    "Stop the active Planledger writer",
                    f"Inspect: {current.path}",
                ],
                details={"lock": current.to_dict()},
            )
        if current.pid is not None:
            unlink_write_lock(project_root, require_pids=(current.pid,))
    path = write_lock_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "command": command,
        "claimed_at": _now_iso(),
        "project_uuid": project_uuid,
    }
    document = json.dumps(payload, indent=2, sort_keys=True)
    acquired = WriteLockSnapshot(
        path=path,
        held=True,
        pid=payload["pid"],
        command=command,
        claimed_at=payload["claimed_at"],
        project_uuid=project_uuid,
        hostname=payload["hostname"],
        age_seconds=0.0,
        is_self=True,
        is_live=True,
    )
    try:
        with open(path, "x", encoding="utf-8") as handle:
            try:
                if sys.platform != "win32":
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except (OSError, AttributeError):
                pass
            handle.write(document)
            handle.flush()
    except FileExistsError as exc:
        existing = inspect_write_lock(project_root)
        if existing.is_live and not existing.is_self:
            raise PlanledgerError(
                "PLANLEDGER_STORAGE_MIGRATION_ACTIVE_WRITER",
                "Planledger write lock was claimed by another writer.",
                details={"lock": existing.to_dict()},
            ) from exc
        unlink_write_lock(project_root, require_pids=(os.getpid(),))
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(document)
            handle.flush()
    try:
        yield acquired
    finally:
        unlink_write_lock(project_root, require_pids=(os.getpid(),))


def unlink_write_lock(project_root: Path, *, require_pids: tuple[int, ...]) -> None:
    path = write_lock_path(project_root)
    if not path.is_file():
        return
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    pid = document.get("pid")
    if not isinstance(pid, int) or pid not in require_pids:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


def require_planledger_quiescent(project_root: Path) -> None:
    snapshot = inspect_write_lock(project_root)
    if snapshot.held and snapshot.is_live and not snapshot.is_self:
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_MIGRATION_ACTIVE_WRITER",
            "Planledger storage migration is blocked by an active writer.",
            remediation=[
                "Wait for the active Planledger writer to finish",
                "Run: planledger doctor",
            ],
            details={"lock": snapshot.to_dict()},
        )


__all__ = [
    "WRITE_LOCK_FILENAME",
    "WriteLockSnapshot",
    "acquire_planledger_write_lock",
    "inspect_write_lock",
    "require_planledger_quiescent",
    "unlink_write_lock",
    "write_lock_path",
]
