"""Wire the Planledger write lock into mutating CLI commands.

Read-only commands (``status``, ``info``, ``doctor``, ``storage where``,
``storage validate``, bare ``migrate``, ``plan list``, ``plan show``,
``plan versions``, ``plan diff``, ``workshop list``, ``workshop show``)
must not acquire the lock. All other mutating commands wrap their body in
``with_planledger_write_lock`` so concurrent writers block before the
mutation begins and the lock releases on exit.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from planledger.errors import PlanledgerError
from planledger.write_lock import acquire_planledger_write_lock


@contextmanager
def with_planledger_write_lock(
    project_root: Path,
    *,
    command: str,
    project_uuid: str,
) -> Iterator[None]:
    """Acquire the Planledger write lock for the duration of the body.

    See plan section 15. The context manager releases the lock on exit and
    does not delete another live process's lock.
    """
    with acquire_planledger_write_lock(
        project_root, command=command, project_uuid=project_uuid
    ):
        yield


def require_quiescent(project_root: Path) -> None:
    """Reject mutating flows when another live writer holds the lock.

    Used by ``migrate apply`` before copy and immediately before activation.
    """
    from planledger.write_lock import require_planledger_quiescent

    try:
        require_planledger_quiescent(project_root)
    except PlanledgerError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_MIGRATION_ACTIVE_WRITER",
            "Planledger quiescence check failed.",
            details={"reason": str(exc)},
        ) from exc


__all__ = ["with_planledger_write_lock", "require_quiescent"]
