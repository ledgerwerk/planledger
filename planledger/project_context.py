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
from planledger.legacy_layout import LegacySource, discover_legacy_source

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
class ProjectInspection:
    state: ProjectState
    locator: LedgerProjectLocator | None = None
    layout: PlanledgerLedgerLayout | None = None
    workspace: Workspace | None = None
    legacy: LegacySource | None = None


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
            "Stable Planledger config contains prohibited keys: "
            f"{', '.join(sorted(found))}.",
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
        if result.valid:
            continue
        mount_name = (
            "config" if result.path == layout.resolved_layout.tool_config_path else None
        )
        mount = next(
            (
                candidate_name
                for candidate_name, candidate in layout.resolved_layout.mounts.items()
                if candidate.path == result.path
            ),
            None,
        )
        if mount is not None:
            mount_name = mount
        reason = result.reason or "Planledger storage binding is invalid."
        validation_kind = "config_binding" if mount_name == "config" else "data_binding"
        if "external store marker" in reason.lower():
            validation_kind = "external_store_marker"
        raise PlanledgerError(
            "PLANLEDGER_DATA_BINDING_INVALID",
            reason,
            details={
                "mount": mount_name or "unknown",
                "path": str(result.path),
                "reason": reason,
                "validation_kind": validation_kind,
                "operation": "load_workspace",
            },
        )


def load_workspace(
    start: Path,
    *,
    require_initialized: bool = True,
    validate_storage: bool = True,
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
    layout = load_planledger_ledger_layout(start, validate_storage=validate_storage)
    _resolve_storage_state(layout)
    if validate_storage:
        _resolve_required_binding_status(layout)
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


_PROJECT_STATE_KIND_FROM_CODE: dict[str, ProjectStateKind] = {
    "PLANLEDGER_REGISTRATION_MISSING": "registration_missing",
    "PLANLEDGER_REGISTRATION_INVALID": "registration_invalid",
    "PLANLEDGER_CONFIG_MISSING": "config_missing",
    "PLANLEDGER_CONFIG_MALFORMED": "invalid",
    "PLANLEDGER_DATA_BINDING_INVALID": "data_binding_invalid",
    "PLANLEDGER_CONFIG_BINDING_INVALID": "config_binding_invalid",
    "PLANLEDGER_DATA_ROOT_MISSING": "data_missing",
    "PLANLEDGER_EXTERNAL_STORE_INVALID": "external_store_invalid",
    "PLANLEDGER_LEDGER_SCHEMA_MIGRATION_REQUIRED": "schema_migration_required",
    "PLANLEDGER_LEDGER_PROJECT_INVALID": "invalid",
    "PLANLEDGER_LEDGER_TOML_INVALID": "invalid",
    "PLANLEDGER_STORAGE_BINDING_INVALID": "data_binding_invalid",
}


def _state_for_error(exc: PlanledgerError) -> ProjectState:
    if "schema 2" in str(exc).lower() or "schema_version = 2" in str(exc).lower():
        kind: ProjectStateKind = "schema_migration_required"
    else:
        kind = _PROJECT_STATE_KIND_FROM_CODE.get(exc.code, "invalid")
    return ProjectState(kind, (exc.code, str(exc)))


def inspect_project_context(start: Path) -> ProjectInspection:
    root = start.resolve(strict=False)
    try:
        locator = locate_project(root)
        legacy = discover_legacy_source(root)
    except PlanledgerError as exc:
        return ProjectInspection(state=_state_for_error(exc))
    except Exception as exc:
        return ProjectInspection(
            state=ProjectState("invalid", (str(exc) or type(exc).__name__,))
        )

    if locator is None:
        if legacy.kind == "schema_migration_required":
            state = ProjectState("schema_migration_required", legacy.blockers)
        elif legacy.kind != "uninitialized":
            state = ProjectState("legacy", (legacy.kind,))
        else:
            state = ProjectState("uninitialized")
        return ProjectInspection(state=state, locator=locator, legacy=legacy)
    if locator.is_legacy:
        return ProjectInspection(
            state=ProjectState(
                "legacy", ("legacy_config_found", str(locator.manifest_path))
            ),
            locator=locator,
            legacy=legacy,
        )
    if not locator.manifest_path.is_file():
        return ProjectInspection(
            state=ProjectState("partial", ("manifest_missing",)),
            locator=locator,
            legacy=legacy,
        )

    try:
        layout = load_planledger_ledger_layout(root, validate_storage=False)
    except PlanledgerError as exc:
        return ProjectInspection(
            state=_state_for_error(exc), locator=locator, legacy=legacy
        )
    except Exception as exc:
        return ProjectInspection(
            state=ProjectState("invalid", (str(exc) or type(exc).__name__,)),
            locator=locator,
            legacy=legacy,
        )
    if layout.loaded_project.manifest.schema_version != 3:
        return ProjectInspection(
            state=ProjectState(
                "schema_migration_required",
                (f"schema_version={layout.loaded_project.manifest.schema_version}",),
            ),
            locator=locator,
            layout=layout,
            legacy=legacy,
        )

    try:
        workspace = load_workspace(
            root,
            require_initialized=False,
            validate_storage=False,
        )
    except PlanledgerError as exc:
        return ProjectInspection(
            state=_state_for_error(exc),
            locator=locator,
            layout=layout,
            legacy=legacy,
        )
    try:
        validated_workspace = load_workspace(root, require_initialized=False)
    except PlanledgerError as exc:
        state = _state_for_error(exc)
    else:
        workspace = validated_workspace
        state = ProjectState("canonical")
    if legacy.retired_artifacts:
        state = ProjectState(
            state.kind,
            state.reasons
            + tuple(f"retired_artifact:{path}" for path in legacy.retired_artifacts),
        )
    return ProjectInspection(
        state=state,
        locator=locator,
        layout=layout,
        workspace=workspace,
        legacy=legacy,
    )


def classify_project_state(start: Path) -> ProjectState:
    return inspect_project_context(start).state
