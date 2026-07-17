"""Planledger schema-3 initialization.

This module owns the canonical schema-3 init flow. It composes Ledgercore
storage, registration, and binding primitives to produce a valid Planledger
workspace, and it tolerates an already-initialized project (idempotent).

The previous `planledger/storage.py` location is kept as a compatibility
re-export for one release and is removed in the next breaking release.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

from tomlkit import dumps as toml_dumps

from planledger.errors import PlanledgerError
from planledger.identity import DEFAULT_LEDGER_CODE, DEFAULT_LEDGER_NAME
from planledger.models import Workspace
from planledger.project_context import load_workspace as load_canonical_workspace

PLANLEDGER_CONFIG_FILENAMES: tuple[str, str] = ("planledger.toml", ".planledger.toml")
STORAGE_FILENAME = "storage.yaml"


def _write_toml(path: Path, document: dict[str, Any]) -> None:
    from planledger.storage import _atomic_write

    _atomic_write(path, toml_dumps(document))


def _canonical_stable_config() -> dict[str, Any]:
    return {
        "config_version": 1,
        "ledger": {"code": DEFAULT_LEDGER_CODE, "name": DEFAULT_LEDGER_NAME},
        "prompt_profiles": {
            "planning_workshop": {
                "enabled": True,
                "activation": "always",
                "question_policy": "ask_one_at_a_time",
                "codebase_first": True,
                "include_recommended_answer": True,
                "max_required_questions": 10,
                "required_question_topics": ["scope", "tests", "rollback", "risks"],
            },
        },
    }


def _initialize_planledger_external_store(
    store_root: Path,
    *,
    create: bool,
    legacy_compatible: bool = True,
) -> bool:
    """Create or refresh the Ledgercore external store marker."""
    from planledger.ledgercore_backend import (
        initialize_planledger_external_store,
        validate_planledger_external_store,
    )

    if store_root.exists() and (store_root.is_symlink() or not store_root.is_dir()):
        raise PlanledgerError(
            "PLANLEDGER_EXTERNAL_STORE_INVALID",
            f"Canonical external store is not a directory: {store_root}.",
        )
    if store_root.exists() and not any(store_root.iterdir()):
        initialize_planledger_external_store(
            store_root, legacy_compatible=legacy_compatible
        )
        return True
    if not store_root.exists():
        if not create:
            raise PlanledgerError(
                "PLANLEDGER_EXTERNAL_STORE_MISSING",
                "Canonical external store does not exist.",
                remediation=[
                    "Run: planledger init --create-external-store",
                ],
            )
        store_root.mkdir(parents=True)
        initialize_planledger_external_store(
            store_root, legacy_compatible=legacy_compatible
        )
        return True
    try:
        validate_planledger_external_store(store_root, allow_legacy=True)
        return False
    except PlanledgerError:
        if not create:
            raise
        initialize_planledger_external_store(
            store_root, legacy_compatible=legacy_compatible
        )
        return True


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    from planledger.storage import _write_yaml as _storage_write_yaml

    _storage_write_yaml(path, data)


def initialize_project(
    root: Path,
    project_name: str,
    *,
    create_external_store: bool | None = None,
    create_sibling_store: bool | None = None,
    project_uuid: str | None = None,
    data_storage: str = "external",
    external_root: str | None = "../ledger",
) -> Workspace:
    if create_external_store is None:
        create_external_store = bool(create_sibling_store)

    from planledger.ledgercore_backend import (
        DATA_MOUNT,
        derive_planledger_external_mount_path,
        ensure_planledger_registration,
        initialize_planledger_locations,
        load_planledger_ledger_layout,
        write_planledger_manifest,
    )

    resolved_root = root.resolve()
    ledger_dir = resolved_root / ".ledger"
    manifest_path = ledger_dir / "ledger.toml"
    local_path = ledger_dir / "ledger.local.toml"
    stable_path = ledger_dir / "planledger" / "config.toml"

    if manifest_path.exists() or stable_path.exists():
        try:
            existing = load_canonical_workspace(
                resolved_root, require_initialized=False
            )
            data_root = existing.data_root
            if not (existing.storage_path.is_file()):
                from planledger.storage import now_iso

                timestamp = now_iso()
                _write_yaml(
                    data_root / STORAGE_FILENAME,
                    {
                        "schema_version": 4,
                        "active_plan_id": None,
                        "active_workshop_id": None,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    },
                )
                for directory in (
                    "allocations/plans",
                    "allocations/workshops",
                    "migrations",
                    "plans",
                    "workshops",
                ):
                    (data_root / directory).mkdir(parents=True, exist_ok=True)
            return load_canonical_workspace(resolved_root)
        except PlanledgerError as exc:
            raise PlanledgerError(
                "PLANLEDGER_INITIALIZATION_CONFLICT",
                "Existing canonical Ledger configuration is incomplete or conflicting.",
                remediation=["Run: planledger doctor", "Run: planledger migrate"],
            ) from exc

    for legacy in PLANLEDGER_CONFIG_FILENAMES:
        if (resolved_root / legacy).exists():
            raise PlanledgerError(
                "PLANLEDGER_MIGRATION_REQUIRED",
                f"Legacy Planledger configuration found: {resolved_root / legacy}.",
                remediation=["Run: planledger migrate"],
            )

    project_uuid = project_uuid or str(uuid4())
    data_storage_normalized = data_storage
    if data_storage_normalized not in {"project", "external", "user-data"}:
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_TARGET_INVALID",
            f"Unsupported data storage {data_storage!r}.",
            details={"allowed": ["project", "external", "user-data"]},
        )
    data_storage_literal = cast(
        "Literal['project', 'external', 'user-data']", data_storage_normalized
    )
    external_root_value = (
        external_root if data_storage_normalized == "external" else None
    )

    if data_storage_normalized == "external" and external_root_value:
        candidate = (resolved_root / external_root_value).resolve()
        external_root_path = candidate
        _initialize_planledger_external_store(
            external_root_path,
            create=bool(create_external_store),
            legacy_compatible=True,
        )
        data_root = derive_planledger_external_mount_path(
            external_root_value,
            project_uuid,
            DATA_MOUNT,
            project_root=resolved_root,
        )
    elif data_storage_normalized == "project":
        data_root = (
            resolved_root / ".ledger" / "planledger" / DATA_MOUNT
        ).resolve()
    else:
        from platformdirs import user_data_path

        user_data = Path(user_data_path("ledgerwerk", appauthor=False))
        data_root = user_data / "planledger" / project_uuid / DATA_MOUNT

    if data_root.exists():
        if data_root.is_symlink() or not data_root.is_dir():
            raise PlanledgerError(
                "PLANLEDGER_DATA_ROOT_INVALID",
                f"Planledger data path is not a real directory: {data_root}.",
            )
        if any(data_root.iterdir()):
            raise PlanledgerError(
                "PLANLEDGER_DATA_ROOT_UNBOUND",
                f"Non-empty unbound Planledger data exists: {data_root}.",
                remediation=["Run: planledger migrate"],
            )
    data_root.mkdir(parents=True, exist_ok=True)

    ledger_dir.mkdir(parents=True, exist_ok=True)
    ledger_dir_planledger = ledger_dir / "planledger"
    ledger_dir_planledger.mkdir(parents=True, exist_ok=True)
    stable_path = ledger_dir_planledger / "config.toml"
    if not stable_path.exists():
        _write_toml(stable_path, _canonical_stable_config())

    manifest = ensure_planledger_registration(
        resolved_root,
        project_uuid=project_uuid,
        project_name=project_name,
        data_storage=data_storage_literal,
        external_root=external_root_value,
    )
    write_planledger_manifest(resolved_root, manifest, preserve_comments=True)

    layout = load_planledger_ledger_layout(resolved_root, validate_storage=False)
    initialize_planledger_locations(
        layout,
        initialize_config=True,
        initialize_data=True,
    )

    from planledger.storage import now_iso

    timestamp = now_iso()
    _write_yaml(
        data_root / STORAGE_FILENAME,
        {
            "schema_version": 4,
            "active_plan_id": None,
            "active_workshop_id": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )
    for directory in (
        "allocations/plans",
        "allocations/workshops",
        "migrations",
        "plans",
        "workshops",
    ):
        (data_root / directory).mkdir(parents=True, exist_ok=True)
    if local_path.exists() and not local_path.is_file():
        local_path.unlink()
    return load_canonical_workspace(resolved_root)
