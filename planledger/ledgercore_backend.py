"""Single Planledger integration point for Ledgercore 0.5.x public APIs.

Planledger domain modules must not import detailed Ledgercore storage,
TOML, binding, layout, or migration APIs directly. They call this adapter
instead. The adapter owns the Planledger-specific tool name, mount name,
storage-kind validation, error mapping, and compatibility shims.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from ledgercore.atomic import atomic_write_text
from ledgercore.config import LedgerProjectLocator
from ledgercore.errors import (
    LedgerConfigError,
    LedgerCoreError,
    StorageBindingError,
    StorageMigrationError,
    TomlConfigError,
)
from ledgercore.layout import (
    ResolvedLedgerLayout,
    resolve_ledger_layout,
)
from ledgercore.manifest import (
    EffectiveLedgerRegistration,
    LedgerLocalOverrides,
    LedgerProjectManifest,
    LoadedLedgerProject,
    MountDefinition,
    StorageKind,
)
from ledgercore.migration import (
    StorageMigrationPlan,
    StorageMigrationResult,
    execute_storage_migration,
    inspect_storage_migration,
    plan_schema_v2_to_v3,
    plan_storage_migration,
    recover_storage_migration,
)
from ledgercore.storage_binding import (
    StorageBinding,
    StorageValidationReport,
    initialize_config_binding,
    initialize_external_store,
    initialize_storage_binding,
    read_storage_binding,
    validate_external_store,
    validate_ledger_layout_storage,
    write_storage_binding,
)
from ledgercore.storage_paths import (
    derive_external_mount_path,
    derive_project_mount_path,
    derive_tool_config_path,
    derive_user_data_mount_path,
    resolve_external_root,
)
from ledgercore.tomlio import (
    clear_local_mount_override,
    load_ledger_project,
    read_ledger_manifest,
    set_local_mount_override,
    write_ledger_local_config,
    write_ledger_manifest,
)

from planledger.errors import PlanledgerError

TOOL_NAME = "planledger"
DATA_MOUNT = "data"

PLANLEDGER_ALLOWED_KINDS: tuple[StorageKind, ...] = (
    "project",
    "external",
    "user-data",
)
PLANLEDGER_REQUIRED_MOUNTS: frozenset[str] = frozenset({"data"})

_DataStorage = Literal["project", "external", "user-data"]
_StorageSource = Literal["manifest", "local"]


@dataclass(frozen=True, slots=True)
class PlanledgerLedgerLayout:
    locator: LedgerProjectLocator
    loaded_project: LoadedLedgerProject
    resolved_layout: ResolvedLedgerLayout
    validation_report: StorageValidationReport | None
    data_storage: _DataStorage
    storage_source: _StorageSource
    external_root: Path | None

    @property
    def storage_validation(self) -> StorageValidationReport | None:
        return self.validation_report


def _map_error(exc: LedgerCoreError) -> PlanledgerError:
    if isinstance(exc, TomlConfigError):
        code = "PLANLEDGER_LEDGER_TOML_INVALID"
    elif isinstance(exc, StorageBindingError):
        code = "PLANLEDGER_DATA_BINDING_INVALID"
    elif isinstance(exc, StorageMigrationError):
        code = "PLANLEDGER_STORAGE_MIGRATION_BLOCKED"
    elif isinstance(exc, LedgerConfigError):
        code = "PLANLEDGER_LEDGER_PROJECT_INVALID"
    else:
        code = f"PLANLEDGER_LEDGER_{type(exc).__name__.upper()}"
    return PlanledgerError(
        code,
        str(exc),
        remediation=[],
        details={
            "ledgercore_code": exc.code,
            "ledgercore_error_type": type(exc).__name__,
        },
    )


def _wrap_load_ledger_project(
    func: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    try:
        return func(*args, **kwargs)
    except TomlConfigError as exc:
        raise PlanledgerError(
            "PLANLEDGER_LEDGER_TOML_INVALID",
            str(exc),
            details={"ledgercore_code": exc.code},
        ) from exc
    except LedgerConfigError as exc:
        raise PlanledgerError(
            "PLANLEDGER_LEDGER_PROJECT_INVALID",
            str(exc),
            details={"ledgercore_code": exc.code},
        ) from exc


def _require_planledger_registration(
    project: LoadedLedgerProject,
) -> EffectiveLedgerRegistration:
    registration = project.effective_ledgers.get(TOOL_NAME)
    if registration is None:
        raise PlanledgerError(
            "PLANLEDGER_REGISTRATION_MISSING",
            f"The shared manifest has no {TOOL_NAME!r} registration.",
            remediation=[
                "Run: planledger init",
                "Run: planledger migrate apply",
            ],
        )
    if set(registration.mounts) != PLANLEDGER_REQUIRED_MOUNTS:
        raise PlanledgerError(
            "PLANLEDGER_REGISTRATION_INVALID",
            "Planledger must define exactly "
            f"{sorted(PLANLEDGER_REQUIRED_MOUNTS)} mounts, "
            f"got {sorted(registration.mounts)}.",
        )
    return registration


def _resolve_layout_from_project(
    project: LoadedLedgerProject,
) -> ResolvedLedgerLayout:
    try:
        return resolve_ledger_layout(
            project.locator,
            project.manifest,
            TOOL_NAME,
            local_overrides=project.local_overrides,
        )
    except LedgerConfigError as exc:
        raise PlanledgerError(
            "PLANLEDGER_LEDGER_PROJECT_INVALID",
            str(exc),
            details={
                "ledgercore_code": exc.code,
                "ledgercore_error_type": type(exc).__name__,
            },
        ) from exc


def _validate_layout_storage(
    layout: ResolvedLedgerLayout,
) -> StorageValidationReport:
    try:
        return validate_ledger_layout_storage(layout)
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def _ensure_cache_storage_rejected(layout: ResolvedLedgerLayout) -> None:
    for mount_name in PLANLEDGER_REQUIRED_MOUNTS:
        if mount_name not in layout.mounts:
            continue
        mount = layout.mounts[mount_name]
        if mount.storage == "cache":
            raise PlanledgerError(
                "PLANLEDGER_STORAGE_TARGET_INVALID",
                f"Planledger {mount_name} mount must not use cache storage.",
            )


def load_planledger_ledger_layout(
    start: Path,
    *,
    validate_storage: bool = True,
) -> PlanledgerLedgerLayout:
    project = _wrap_load_ledger_project(
        load_ledger_project,
        start,
        legacy_tool_filenames=("planledger.toml", ".planledger.toml"),
    )
    if project.manifest.schema_version != 3:
        raise PlanledgerError(
            "PLANLEDGER_LEDGER_SCHEMA_MIGRATION_REQUIRED",
            "Ledger manifest is not schema 3; run planledger migrate.",
            remediation=["Run: planledger migrate"],
        )
    _require_planledger_registration(project)
    layout = _resolve_layout_from_project(project)
    _ensure_cache_storage_rejected(layout)
    data_mount = layout.mounts.get(DATA_MOUNT)
    if data_mount is None:
        raise PlanledgerError(
            "PLANLEDGER_MOUNT_INVALID",
            "Resolved Planledger layout must contain the data mount.",
        )
    data_storage = cast(_DataStorage, data_mount.storage)
    storage_source = cast(_StorageSource, data_mount.source)
    external_root = data_mount.root if data_storage == "external" else None
    if external_root is not None and not external_root.is_absolute():
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_TARGET_INVALID",
            "Ledgercore returned a non-absolute external root.",
            details={"path": str(external_root)},
        )
    report = _validate_layout_storage(layout) if validate_storage else None
    return PlanledgerLedgerLayout(
        locator=project.locator,
        loaded_project=project,
        resolved_layout=layout,
        validation_report=report,
        data_storage=data_storage,
        storage_source=storage_source,
        external_root=external_root,
    )


def ensure_planledger_registration(
    project_root: Path,
    *,
    project_uuid: str,
    project_name: str,
    data_storage: _DataStorage = "external",
    external_root: str | None = "../ledger",
) -> LedgerProjectManifest:
    if data_storage == "external" and not external_root:
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_TARGET_INVALID",
            "External storage requires an external_root value.",
        )
    manifest_path = project_root.resolve(strict=False) / ".ledger" / "ledger.toml"
    if manifest_path.is_file():
        manifest = read_ledger_manifest(manifest_path)
    else:
        manifest = LedgerProjectManifest(
            schema_version=3,
            project_uuid=project_uuid,
            project_name=project_name,
            ledgers={},
        )
    new_mount = MountDefinition(
        name=DATA_MOUNT,
        storage=data_storage,
        external_root=external_root if data_storage == "external" else None,
    )
    from ledgercore.manifest import LedgerRegistration

    ledgers = dict(manifest.ledgers)
    existing = ledgers.get(TOOL_NAME)
    if existing is None:
        ledgers[TOOL_NAME] = LedgerRegistration(
            name=TOOL_NAME,
            mounts={DATA_MOUNT: new_mount},
        )
    else:
        mounts = dict(existing.mounts)
        mounts[DATA_MOUNT] = new_mount
        ledgers[TOOL_NAME] = LedgerRegistration(
            name=TOOL_NAME,
            mounts=mounts,
        )
    new_manifest = LedgerProjectManifest(
        schema_version=3,
        project_uuid=manifest.project_uuid,
        project_name=manifest.project_name,
        ledgers=cast(Mapping[str, Any], ledgers),
    )
    return new_manifest


def write_planledger_manifest(
    project_root: Path,
    manifest: LedgerProjectManifest,
    *,
    preserve_comments: bool = True,
) -> None:
    manifest_path = project_root.resolve(strict=False) / ".ledger" / "ledger.toml"
    try:
        write_ledger_manifest(
            manifest_path, manifest, preserve_comments=preserve_comments
        )
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def initialize_planledger_locations(
    layout: PlanledgerLedgerLayout,
    *,
    initialize_config: bool,
    initialize_data: bool,
) -> tuple[StorageBinding | None, StorageBinding | None]:
    config_binding: StorageBinding | None = None
    data_binding: StorageBinding | None = None
    if initialize_config:
        try:
            config_binding = initialize_config_binding(layout.resolved_layout)
        except LedgerCoreError as exc:
            raise _map_error(exc) from exc
    if initialize_data and DATA_MOUNT in layout.resolved_layout.mounts:
        resolved = layout.resolved_layout.mounts[DATA_MOUNT]
        try:
            data_binding = initialize_storage_binding(resolved, require_empty=True)
        except LedgerCoreError as exc:
            raise _map_error(exc) from exc
    return config_binding, data_binding


def set_planledger_data_target(
    project_root: Path,
    *,
    storage: _DataStorage,
    external_root: str | None,
    target: str,
) -> LedgerLocalOverrides | LedgerProjectManifest:
    if target not in {"manifest", "local"}:
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_TARGET_INVALID",
            f"target must be 'manifest' or 'local', got {target!r}.",
        )
    project = _wrap_load_ledger_project(
        load_ledger_project,
        project_root,
        legacy_tool_filenames=("planledger.toml", ".planledger.toml"),
    )
    if target == "manifest":
        new_mount = MountDefinition(
            name=DATA_MOUNT,
            storage=storage,
            external_root=external_root if storage == "external" else None,
        )
        from ledgercore.manifest import LedgerRegistration

        ledgers = dict(project.manifest.ledgers)
        existing = ledgers.get(TOOL_NAME)
        if existing is None:
            ledgers[TOOL_NAME] = LedgerRegistration(
                name=TOOL_NAME,
                mounts={DATA_MOUNT: new_mount},
            )
        else:
            mounts = dict(existing.mounts)
            mounts[DATA_MOUNT] = new_mount
            ledgers[TOOL_NAME] = LedgerRegistration(
                name=TOOL_NAME,
                mounts=mounts,
            )
        new_manifest = LedgerProjectManifest(
            schema_version=3,
            project_uuid=project.manifest.project_uuid,
            project_name=project.manifest.project_name,
            ledgers=cast(Mapping[str, Any], ledgers),
        )
        write_planledger_manifest(project_root, new_manifest)
        return new_manifest
    new_overrides = set_local_mount_override(
        project,
        TOOL_NAME,
        DATA_MOUNT,
        storage=storage,
        root=external_root,
    )
    local_path = project_root.resolve(strict=False) / ".ledger" / "ledger.local.toml"
    try:
        write_ledger_local_config(
            local_path,
            new_overrides,
            preserve_comments=True,
            delete_if_empty=False,
        )
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc
    return new_overrides


def clear_planledger_data_override(project_root: Path) -> LedgerLocalOverrides | None:
    project = _wrap_load_ledger_project(
        load_ledger_project,
        project_root,
        legacy_tool_filenames=("planledger.toml", ".planledger.toml"),
    )
    new_overrides = clear_local_mount_override(project, TOOL_NAME, DATA_MOUNT)
    local_path = project_root.resolve(strict=False) / ".ledger" / "ledger.local.toml"
    try:
        write_ledger_local_config(
            local_path,
            new_overrides,
            preserve_comments=True,
            delete_if_empty=True,
        )
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc
    return new_overrides if new_overrides.ledgers else None


def initialize_planledger_external_store(
    root: Path,
    *,
    legacy_compatible: bool = False,
) -> Path:
    try:
        return initialize_external_store(root)
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def validate_planledger_external_store(
    root: Path, *, allow_legacy: bool = True
) -> Path:
    try:
        return validate_external_store(root, allow_legacy=allow_legacy)
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def read_planledger_storage_binding(path: Path) -> StorageBinding:
    try:
        return read_storage_binding(path)
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def write_planledger_storage_binding(path: Path, binding: StorageBinding) -> None:
    try:
        write_storage_binding(path, binding)
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def plan_planledger_layout_migration(
    current: LoadedLedgerProject,
    target_manifest: LedgerProjectManifest,
    target_overrides: LedgerLocalOverrides,
    *,
    mounts: tuple[str, ...] | None = None,
    include_config: bool = False,
    cache_strategy: str = "rebuild",
) -> StorageMigrationPlan:
    try:
        return plan_storage_migration(
            current,
            target_manifest,
            target_overrides,
            TOOL_NAME,
            mounts=mounts,
            include_config=include_config,
            cache_strategy=cast(Any, cache_strategy),
        )
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def execute_planledger_layout_migration(
    plan: StorageMigrationPlan,
    *,
    mode: str = "move",
    verify: str = "sha256",
    quiescence_check: Callable[[], None] | None = None,
    project_root: Path | None = None,
) -> StorageMigrationResult:
    try:
        return execute_storage_migration(
            plan,
            mode=cast(Any, mode),
            verify=cast(Any, verify),
            quiescence_check=quiescence_check,
            project_root=project_root,
        )
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def inspect_planledger_storage_migration(
    journal_path: Path,
) -> Any:
    try:
        return inspect_storage_migration(journal_path)
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def recover_planledger_storage_migration(
    journal_path: Path,
) -> StorageMigrationResult:
    try:
        return recover_storage_migration(journal_path)
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def plan_schema_v2_to_v3_manifest(
    loaded: Any,
) -> LedgerProjectManifest:
    try:
        return cast(LedgerProjectManifest, plan_schema_v2_to_v3(loaded))
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def atomic_write_text_file(path: Path, content: str) -> None:
    try:
        atomic_write_text(path, content)
    except LedgerCoreError as exc:
        raise _map_error(exc) from exc


def derive_planledger_tool_config_path(project_root: Path) -> Path:
    return derive_tool_config_path(project_root, TOOL_NAME)


def derive_planledger_project_mount_path(project_root: Path, mount_name: str) -> Path:
    return derive_project_mount_path(project_root, TOOL_NAME, mount_name)


def derive_planledger_external_mount_path(
    external_root: str | Path,
    project_uuid: str,
    mount_name: str,
    *,
    project_root: Path,
) -> Path:
    return derive_external_mount_path(
        external_root,
        TOOL_NAME,
        project_uuid,
        mount_name,
        project_root=project_root,
    )


def derive_planledger_user_data_mount_path(
    user_data_root: Path,
    project_uuid: str,
    mount_name: str,
) -> Path:
    return derive_user_data_mount_path(
        user_data_root, TOOL_NAME, project_uuid, mount_name
    )


def resolve_planledger_external_root(root: Path | str, *, project_root: Path) -> Path:
    return resolve_external_root(root, project_root=project_root)


__all__ = [
    "TOOL_NAME",
    "DATA_MOUNT",
    "PLANLEDGER_REQUIRED_MOUNTS",
    "PLANLEDGER_ALLOWED_KINDS",
    "PlanledgerLedgerLayout",
    "atomic_write_text_file",
    "clear_planledger_data_override",
    "derive_planledger_external_mount_path",
    "derive_planledger_project_mount_path",
    "derive_planledger_tool_config_path",
    "derive_planledger_user_data_mount_path",
    "ensure_planledger_registration",
    "execute_planledger_layout_migration",
    "initialize_planledger_external_store",
    "initialize_planledger_locations",
    "inspect_planledger_storage_migration",
    "load_planledger_ledger_layout",
    "plan_planledger_layout_migration",
    "plan_schema_v2_to_v3_manifest",
    "read_planledger_storage_binding",
    "recover_planledger_storage_migration",
    "resolve_planledger_external_root",
    "set_planledger_data_target",
    "validate_planledger_external_store",
    "write_planledger_manifest",
    "write_planledger_storage_binding",
]
