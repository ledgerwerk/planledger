from __future__ import annotations

import os
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ledgercore.config import LedgerProjectLocator

from planledger.errors import PlanledgerError
from planledger.ledgercore_backend import (
    DATA_MOUNT,
    TOOL_NAME,
    PlanledgerLedgerLayout,
    load_planledger_ledger_layout,
)

_PROJECT_STATE_KINDS = {
    "uninitialized",
    "legacy",
    "schema_migration_required",
    "registration_missing",
    "registration_invalid",
    "config_missing",
    "config_binding_missing",
    "config_binding_invalid",
    "data_missing",
    "data_binding_missing",
    "data_binding_invalid",
    "external_store_invalid",
    "storage_migration_incomplete",
    "state_missing",
    "state_invalid",
    "canonical",
    "partial",
    "invalid",
}

ProjectStateKind = Literal[
    "uninitialized",
    "legacy",
    "schema_migration_required",
    "registration_missing",
    "registration_invalid",
    "config_missing",
    "config_binding_missing",
    "config_binding_invalid",
    "data_missing",
    "data_binding_missing",
    "data_binding_invalid",
    "external_store_invalid",
    "storage_migration_incomplete",
    "state_missing",
    "state_invalid",
    "canonical",
    "partial",
    "invalid",
]


@dataclass(frozen=True, slots=True)
class ProjectState:
    kind: ProjectStateKind
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Workspace:
    root: Path
    project_root: Path
    config_root: Path
    manifest_path: Path
    local_config_path: Path
    config_path: Path

    data_root: Path
    planledger_dir: Path
    storage_path: Path

    project_uuid: str
    project_name: str | None

    data_storage: Literal["project", "external", "user-data"]
    storage_source: Literal["manifest", "local"]
    external_root: Path | None

    config: dict[str, Any]
    loaded_project: Any
    layout: PlanledgerLedgerLayout
    storage_validation: Any

    @property
    def ledger_code(self) -> str:
        from planledger.identity import ledger_code_from_config

        return ledger_code_from_config(self.config)

    @property
    def store_root(self) -> Path | None:
        if self.external_root is None:
            return None
        return self.external_root

    @property
    def store_marker_path(self) -> Path | None:
        if self.external_root is None:
            return None
        return self.external_root / ".ledger-store.toml"

    @property
    def binding_path(self) -> Path:
        return self.data_root / ".ledger-project.toml"


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise PlanledgerError(
            "PLANLEDGER_CONFIG_MISSING", f"Required configuration is missing: {path}."
        ) from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PlanledgerError(
            "PLANLEDGER_CONFIG_MALFORMED", f"Invalid TOML configuration: {path}."
        ) from exc
    if not isinstance(value, dict):
        raise PlanledgerError(
            "PLANLEDGER_CONFIG_MALFORMED",
            f"Configuration must be a TOML table: {path}.",
        )
    return value


def load_optional_toml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _load_toml(path)


def locate_project(start: Path) -> LedgerProjectLocator | None:
    from ledgercore.config import locate_ledger_project

    return locate_ledger_project(
        start,
        legacy_tool_filenames=("planledger.toml", ".planledger.toml"),
    )


def _validate_stable_config(config_path: Path) -> dict[str, Any]:
    config = _load_toml(config_path)
    forbidden = {
        "project_uuid",
        "project_name",
        "planledger_dir",
        "external_root",
        "workspace_root",
        "workspace_provider",
        "storage_mode",
        "data_root",
        "local_data",
        "external_data",
        "storage",
    }
    found = forbidden.intersection(config)
    if found:
        raise PlanledgerError(
            "PLANLEDGER_CONFIG_CONFLICT",
            f"Stable Planledger config contains prohibited keys: {', '.join(sorted(found))}.",
        )
    return config


def _workspace_config(
    stable: dict[str, Any], project_uuid: str, project_name: str | None
) -> dict[str, Any]:
    config = dict(stable)
    ledger = (
        dict(config.get("ledger", {})) if isinstance(config.get("ledger"), dict) else {}
    )
    ledger.setdefault("code", "pl")
    ledger.setdefault("name", TOOL_NAME)
    config["ledger"] = ledger
    project: dict[str, Any] = {"uuid": project_uuid}
    if project_name is not None:
        project["name"] = project_name
    config["project"] = project
    return config


def _resolve_storage_state(layout: PlanledgerLedgerLayout) -> None:
    if layout.data_storage == "cache":
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_TARGET_INVALID",
            "Planledger data mount must not use cache storage.",
        )
    if layout.data_storage not in {"project", "external", "user-data"}:
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_TARGET_INVALID",
            f"Planledger data storage {layout.data_storage!r} is not supported.",
        )


def _resolve_required_binding_status(layout: PlanledgerLedgerLayout) -> None:
    report = layout.storage_validation
    if report is None:
        return
    for result in report.results:
        if not result.valid:
            raise PlanledgerError(
                "PLANLEDGER_STORAGE_BINDING_INVALID",
                result.reason or "Planledger storage binding is invalid.",
                details={"path": str(result.path)},
            )


def _ensure_external_store_marker(layout: PlanledgerLedgerLayout) -> None:
    if layout.data_storage != "external":
        return
    external_root = layout.external_root
    if external_root is None:
        return
    from planledger.ledgercore_backend import validate_planledger_external_store

    try:
        validate_planledger_external_store(external_root, allow_legacy=True)
    except PlanledgerError:
        raise
    except Exception as exc:
        raise PlanledgerError(
            "PLANLEDGER_EXTERNAL_STORE_INVALID",
            f"Planledger external store is invalid: {external_root}.",
            details={"path": str(external_root)},
        ) from exc


def load_workspace(
    start: Path,
    *,
    require_initialized: bool = True,
    environ: Mapping[str, str] | None = None,
) -> Workspace:
    effective_environment = os.environ if environ is None else environ
    if effective_environment.get("LEDGER_WORKSPACE_ROOT"):
        raise PlanledgerError(
            "PLANLEDGER_WORKSPACE_ENV_UNSUPPORTED",
            "Planledger storage is fixed to Ledgercore 0.5 schema-3 mounts. "
            "Unset LEDGER_WORKSPACE_ROOT and retry.",
            remediation=[
                "Unset LEDGER_WORKSPACE_ROOT",
                "Use planledger storage set ... for storage changes",
            ],
        )
    layout = load_planledger_ledger_layout(start, validate_storage=True)
    _resolve_storage_state(layout)
    _resolve_required_binding_status(layout)
    _ensure_external_store_marker(layout)
    data_mount = layout.resolved_layout.mounts.get(DATA_MOUNT)
    if data_mount is None:
        raise PlanledgerError(
            "PLANLEDGER_MOUNT_INVALID",
            "Resolved Planledger layout must contain the data mount.",
        )
    data_root = data_mount.path
    if require_initialized and not data_root.is_dir():
        raise PlanledgerError(
            "PLANLEDGER_DATA_ROOT_MISSING",
            f"Planledger data directory is missing: {data_root}.",
            remediation=[
                "Run: planledger init",
                "Run: planledger migrate apply",
            ],
        )
    tool_config_path = layout.resolved_layout.tool_config_path
    if tool_config_path is None:
        raise PlanledgerError(
            "PLANLEDGER_CONFIG_MISSING", "Planledger project config is not resolved."
        )
    stable_config = _validate_stable_config(tool_config_path)
    manifest = layout.loaded_project.manifest
    config = _workspace_config(
        stable_config,
        manifest.project_uuid,
        manifest.project_name,
    )
    return Workspace(
        root=layout.locator.project_root,
        project_root=layout.locator.project_root,
        config_root=layout.locator.config_root,
        manifest_path=layout.locator.manifest_path,
        local_config_path=layout.locator.local_config_path,
        config_path=tool_config_path,
        data_root=data_root,
        planledger_dir=data_root,
        storage_path=data_root / "storage.yaml",
        project_uuid=manifest.project_uuid,
        project_name=manifest.project_name,
        data_storage=layout.data_storage,
        storage_source=layout.storage_source,
        external_root=layout.external_root,
        config=config,
        loaded_project=layout.loaded_project,
        layout=layout,
        storage_validation=layout.storage_validation,
    )


def classify_project_state(start: Path) -> ProjectState:
    try:
        locator = locate_project(start)
    except Exception as exc:
        return ProjectState("invalid", (str(exc),))
    if locator is None:
        return ProjectState("uninitialized")
    if locator.is_legacy:
        return ProjectState(
            "legacy", ("legacy_config_found", str(locator.manifest_path))
        )
    if not locator.manifest_path.is_file():
        return ProjectState("partial", ("manifest_missing",))
    try:
        loaded = load_planledger_ledger_layout(start, validate_storage=False)
    except Exception as exc:
        return ProjectState(
            "invalid",
            (str(exc) or exc.__class__.__name__,),
        )
    if loaded.loaded_project.manifest.schema_version != 3:
        return ProjectState(
            "schema_migration_required",
            (f"schema_version={loaded.loaded_project.manifest.schema_version}",),
        )
    if TOOL_NAME not in loaded.loaded_project.manifest.ledgers:
        return ProjectState("registration_missing")
    try:
        load_workspace(start)
    except PlanledgerError as exc:
        kind = _PROJECT_STATE_KIND_FROM_CODE.get(exc.code, "invalid")
        return ProjectState(kind, (exc.code,))
    return ProjectState("canonical")


_PROJECT_STATE_KIND_FROM_CODE: dict[str, ProjectStateKind] = {
    "PLANLEDGER_REGISTRATION_MISSING": "registration_missing",
    "PLANLEDGER_REGISTRATION_INVALID": "registration_invalid",
    "PLANLEDGER_CONFIG_MISSING": "config_missing",
    "PLANLEDGER_CONFIG_MALFORMED": "config_invalid",
    "PLANLEDGER_DATA_BINDING_INVALID": "data_binding_invalid",
    "PLANLEDGER_CONFIG_BINDING_INVALID": "config_binding_invalid",
    "PLANLEDGER_DATA_ROOT_MISSING": "data_missing",
    "PLANLEDGER_EXTERNAL_STORE_INVALID": "external_store_invalid",
    "PLANLEDGER_LEDGER_SCHEMA_MIGRATION_REQUIRED": "schema_migration_required",
    "PLANLEDGER_LEDGER_PROJECT_INVALID": "canonical",
    "PLANLEDGER_LEDGER_TOML_INVALID": "invalid",
    "PLANLEDGER_STORAGE_BINDING_INVALID": "data_binding_invalid",
}
