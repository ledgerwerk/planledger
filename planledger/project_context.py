# ruff: noqa: E501
from __future__ import annotations

import os
import stat
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from ledgercore.config import LedgerProjectLocator, locate_ledger_project
from ledgercore.errors import LedgerConfigError, LedgerCoreError, LedgerLayoutError
from ledgercore.layout import (
    LedgerLocalConfig,
    LedgerProjectManifest,
    ResolvedLedgerLayout,
    parse_ledger_local_config,
    parse_ledger_project_manifest,
    resolve_ledger_layout,
)

from planledger.errors import PlanledgerError
from planledger.project_binding import (
    PlanledgerProjectBinding,
    validate_project_binding,
)

ProjectStateKind = Literal["uninitialized", "legacy", "canonical", "partial", "invalid"]


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
    store_root: Path
    store_marker_path: Path
    planledger_dir: Path
    storage_path: Path
    binding_path: Path
    project_uuid: str
    project_name: str | None
    active_mount_name: Literal["data"]
    mount_storage: Literal["workspace"]
    mount_scope: Literal["project"]
    mount_source: Literal["local-provider"]
    workspace_provider: Literal["sibling-ledger"]
    config: dict[str, Any]
    manifest: LedgerProjectManifest
    local_config: LedgerLocalConfig
    layout: ResolvedLedgerLayout
    binding: PlanledgerProjectBinding

    @property
    def ledger_code(self) -> str:
        from planledger.identity import ledger_code_from_config

        return ledger_code_from_config(self.config)


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
    return locate_ledger_project(
        start,
        legacy_tool_filenames=("planledger.toml", ".planledger.toml"),
    )


def _validate_planledger_registration(manifest: LedgerProjectManifest) -> None:
    registration = manifest.ledgers.get("planledger")
    if registration is None:
        raise PlanledgerError(
            "PLANLEDGER_REGISTRATION_MISSING",
            "The shared manifest has no planledger registration.",
        )
    if (
        registration.config is None
        or registration.config.location != "project"
        or registration.config.path != "plan/config.toml"
    ):
        raise PlanledgerError(
            "PLANLEDGER_REGISTRATION_CONFLICT",
            "Planledger config must be the project mount plan/config.toml.",
        )
    if registration.config.scope is not None:
        raise PlanledgerError(
            "PLANLEDGER_REGISTRATION_CONFLICT",
            "Planledger project config must not define a checkout scope.",
        )
    if set(registration.mounts) != {"data"}:
        raise PlanledgerError(
            "PLANLEDGER_REGISTRATION_CONFLICT",
            "Planledger must define exactly one data mount.",
        )
    mount = registration.mounts["data"]
    if (
        mount.storage != "workspace"
        or mount.scope != "project"
        or mount.path != "plan/planledger"
    ):
        raise PlanledgerError(
            "PLANLEDGER_REGISTRATION_CONFLICT",
            "Planledger data must be workspace/project at plan/planledger.",
        )


def _validate_store_root(store_root: Path) -> Path:
    if not store_root.exists():
        raise PlanledgerError(
            "PLANLEDGER_SIBLING_ROOT_MISSING",
            f"Canonical sibling Ledger store does not exist: {store_root}.",
        )
    if store_root.is_symlink() or not store_root.is_dir():
        raise PlanledgerError(
            "PLANLEDGER_SIBLING_ROOT_NOT_DIRECTORY",
            f"Canonical sibling Ledger store is not a directory: {store_root}.",
        )
    marker = store_root / ".ledger-store"
    try:
        mode = marker.lstat().st_mode
    except FileNotFoundError as exc:
        raise PlanledgerError(
            "PLANLEDGER_SIBLING_ROOT_UNMARKED",
            f"Sibling store marker is missing: {marker}.",
        ) from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise PlanledgerError(
            "PLANLEDGER_SIBLING_MARKER_INVALID",
            f"Sibling store marker must be a regular file: {marker}.",
        )
    return marker


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
    }
    found = forbidden.intersection(config)
    if found:
        raise PlanledgerError(
            "PLANLEDGER_CONFIG_CONFLICT",
            f"Stable Planledger config contains prohibited keys: {', '.join(sorted(found))}.",
        )
    storage = config.get("storage")
    if storage is not None:
        raise PlanledgerError(
            "PLANLEDGER_CONFIG_CONFLICT",
            "Stable Planledger config must not select storage.",
        )
    return config


def _workspace_config(
    stable: dict[str, Any], manifest: LedgerProjectManifest
) -> dict[str, Any]:
    config = dict(stable)
    ledger = (
        dict(config.get("ledger", {})) if isinstance(config.get("ledger"), dict) else {}
    )
    ledger.setdefault("code", "pl")
    ledger.setdefault("name", "planledger")
    config["ledger"] = ledger
    project: dict[str, Any] = {"uuid": manifest.project_uuid}
    if manifest.project_name is not None:
        project["name"] = manifest.project_name
    config["project"] = project
    return config


def _resolve(
    locator: LedgerProjectLocator,
    manifest: LedgerProjectManifest,
    local_config: LedgerLocalConfig,
) -> ResolvedLedgerLayout:
    try:
        return resolve_ledger_layout(
            locator,
            manifest,
            "planledger",
            local_config=local_config,
            environ={},
        )
    except (LedgerCoreError, LedgerConfigError, LedgerLayoutError) as exc:
        raise PlanledgerError("PLANLEDGER_LAYOUT_INVALID", str(exc)) from exc


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
            "Planledger storage is fixed to the configured sibling-ledger provider. Unset LEDGER_WORKSPACE_ROOT and retry.",
        )
    locator = locate_project(start)
    if locator is None:
        code = (
            "PLANLEDGER_PROJECT_NOT_FOUND"
            if require_initialized
            else "PLANLEDGER_PROJECT_NOT_FOUND"
        )
        raise PlanledgerError(
            code,
            "No canonical Ledger project was found.",
            remediation=["Run: planledger init"],
        )
    if locator.is_legacy:
        raise PlanledgerError(
            "PLANLEDGER_MIGRATION_REQUIRED",
            f"Legacy Planledger configuration found at {locator.manifest_path}.",
            remediation=["Run: planledger migrate", "Run: planledger migrate apply"],
        )
    manifest_document = _load_toml(locator.manifest_path)
    try:
        manifest = parse_ledger_project_manifest(manifest_document)
    except (LedgerCoreError, LedgerConfigError, LedgerLayoutError) as exc:
        raise PlanledgerError("PLANLEDGER_MANIFEST_INVALID", str(exc)) from exc
    _validate_planledger_registration(manifest)
    local_document = load_optional_toml(locator.local_config_path)
    if local_document is None:
        raise PlanledgerError(
            "PLANLEDGER_LOCAL_CONFIG_MISSING",
            f"Shared Ledger local config is missing: {locator.local_config_path}.",
        )
    try:
        local_config = parse_ledger_local_config(
            local_document, project_root=locator.project_root
        )
    except (LedgerCoreError, LedgerConfigError, LedgerLayoutError) as exc:
        raise PlanledgerError("PLANLEDGER_LOCAL_CONFIG_INVALID", str(exc)) from exc
    if local_config.workspace_root is not None:
        raise PlanledgerError(
            "PLANLEDGER_WORKSPACE_ROOT_CONFLICT",
            "Planledger requires sibling-ledger and rejects a workspace root override.",
        )
    if local_config.workspace_provider != "sibling-ledger":
        raise PlanledgerError(
            "PLANLEDGER_SIBLING_PROVIDER_REQUIRED",
            "Planledger requires workspace provider 'sibling-ledger'.",
        )
    layout = _resolve(locator, manifest, local_config)
    if set(layout.mounts) != {"data"}:
        raise PlanledgerError(
            "PLANLEDGER_MOUNT_INVALID",
            "Resolved Planledger layout must contain only the data mount.",
        )
    mount = layout.mounts["data"]
    store_root = (locator.project_root.parent / "ledger").resolve(strict=False)
    expected_data_root = store_root / "plan" / "planledger"
    if mount.path.resolve(strict=False) != expected_data_root:
        raise PlanledgerError(
            "PLANLEDGER_PATH_MISMATCH",
            f"Ledgercore resolved {mount.path}, expected {expected_data_root}.",
        )
    if (
        mount.storage != "workspace"
        or mount.scope != "project"
        or mount.source != "local-provider"
    ):
        raise PlanledgerError(
            "PLANLEDGER_MOUNT_INVALID",
            "Planledger data must resolve from the sibling local provider.",
        )
    marker = _validate_store_root(store_root)
    data_root = mount.path
    if require_initialized and not data_root.is_dir():
        raise PlanledgerError(
            "PLANLEDGER_DATA_ROOT_MISSING",
            f"Planledger data directory is missing: {data_root}.",
        )
    stable_config_path = layout.tool_config_path
    if stable_config_path is None:
        raise PlanledgerError(
            "PLANLEDGER_CONFIG_MISSING", "Planledger project config is not resolved."
        )
    stable_config = _validate_stable_config(stable_config_path)
    binding = validate_project_binding(data_root, project_uuid=manifest.project_uuid)
    return Workspace(
        root=locator.project_root,
        project_root=locator.project_root,
        config_root=locator.config_root,
        manifest_path=locator.manifest_path,
        local_config_path=locator.local_config_path,
        config_path=stable_config_path,
        store_root=store_root,
        store_marker_path=marker,
        planledger_dir=data_root,
        storage_path=data_root / "storage.yaml",
        binding_path=data_root / ".ledger-project.toml",
        project_uuid=manifest.project_uuid,
        project_name=manifest.project_name,
        active_mount_name="data",
        mount_storage="workspace",
        mount_scope="project",
        mount_source="local-provider",
        workspace_provider="sibling-ledger",
        config=_workspace_config(stable_config, manifest),
        manifest=manifest,
        local_config=local_config,
        layout=layout,
        binding=binding,
    )


def classify_project_state(start: Path) -> ProjectState:
    locator = locate_project(start)
    if locator is None:
        return ProjectState("uninitialized")
    if locator.is_legacy:
        return ProjectState("legacy", ("legacy_config_found",))
    try:
        load_workspace(start)
    except PlanledgerError as exc:
        code: ProjectStateKind = (
            "partial"
            if exc.code
            in {
                "PLANLEDGER_LOCAL_CONFIG_MISSING",
                "PLANLEDGER_DATA_ROOT_MISSING",
                "PLANLEDGER_BINDING_MISSING",
            }
            else "invalid"
        )
        return ProjectState(code, (exc.code,))
    return ProjectState("canonical")
