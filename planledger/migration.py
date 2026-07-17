# ruff: noqa: E501
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import yaml
from tomlkit import dumps as toml_dumps
from tomlkit import parse as toml_parse

from planledger.errors import PlanledgerError
from planledger.project_binding import BINDING_FILENAME
from planledger.project_context import locate_project

MigrationSourceKind = Literal[
    "uninitialized",
    "legacy_local",
    "legacy_external",
    "repository_local_proposal",
    "namespaced_workspace",
    "direct_sibling_unbound",
    "old_canonical",
    "canonical",
    "partial",
    "invalid",
]


@dataclass(frozen=True, slots=True)
class MigrationIssue:
    severity: Literal["blocker", "warning", "info"]
    code: str
    message: str
    remediation: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MigrationCopyItem:
    source: Path | None
    destination: Path
    category: str
    action: str
    verification: str


@dataclass(frozen=True, slots=True)
class PlanledgerMigrationInspection:
    project_root: Path
    source_kind: MigrationSourceKind
    source_config_path: Path | None
    source_data_root: Path | None
    source_project_uuid: str | None
    canonical_project_uuid: str | None
    sibling_store_root: Path
    sibling_marker_path: Path
    target_data_root: Path
    target_binding_path: Path
    manifest_path: Path
    ledger_local_config_path: Path
    stable_config_path: Path
    plan_count: int
    workshop_count: int
    source_state_schema: int | None
    legacy_next_plan_id: int | None
    legacy_next_workshop_id: int | None
    copy_items: tuple[MigrationCopyItem, ...]
    issues: tuple[MigrationIssue, ...]
    ready: bool
    migration_required: bool


@dataclass(frozen=True, slots=True)
class PlanledgerMigrationResult:
    inspection: PlanledgerMigrationInspection
    backup_dir: Path
    receipt_path: Path
    copied: tuple[str, ...]
    skipped: tuple[str, ...]
    source_preserved: bool
    verification: dict[str, Any]


def _toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PlanledgerError(
            "PLANLEDGER_MIGRATION_CONFIG_INVALID", f"Invalid TOML source: {path}."
        ) from exc
    return value if isinstance(value, dict) else {}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    return stat.S_ISREG(mode) and not stat.S_ISLNK(mode)


def _manifest_uuid(manifest_path: Path) -> str | None:
    if not manifest_path.is_file():
        return None
    try:
        value = _toml(manifest_path).get("project", {}).get("uuid")
    except PlanledgerError:
        return None
    return value if isinstance(value, str) else None



def _source_uuid(config_path: Path | None, data_root: Path | None) -> str | None:
    if config_path is not None and config_path.is_file():
        try:
            value = _toml(config_path).get("project", {}).get("uuid")
        except PlanledgerError:
            value = None
        if isinstance(value, str):
            return value
    if data_root is not None:
        try:
            state = _state(data_root)[0]
        except Exception:
            state = {}
        value = state.get("project_uuid")
        if isinstance(value, str):
            return value
    return None


def _state(data_root: Path) -> tuple[dict[str, Any], list[MigrationIssue]]:
    path = data_root / "storage.yaml"
    if not path.is_file():
        return {}, [
            MigrationIssue(
                "blocker", "SOURCE_DATA_MISSING", f"Source state is missing: {path}."
            )
        ]
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}, [
            MigrationIssue(
                "blocker", "STATE_INVALID", f"Source state is invalid: {path}."
            )
        ]
    if not isinstance(value, dict):
        return {}, [
            MigrationIssue(
                "blocker", "STATE_INVALID", f"Source state must be a mapping: {path}."
            )
        ]
    return value, []


def _count_records(root: Path, kind: str) -> tuple[int, list[MigrationIssue]]:
    directory = root / ("plans" if kind == "plan" else "workshops")
    if not directory.exists():
        return 0, []
    if directory.is_symlink() or not directory.is_dir():
        return 0, [
            MigrationIssue(
                "blocker",
                "SOURCE_SYMLINK",
                f"Source {kind} directory is not a real directory: {directory}.",
            )
        ]
    count = 0
    issues: list[MigrationIssue] = []
    metadata_name = "plan.yaml" if kind == "plan" else "workshop.yaml"
    for entry in directory.iterdir():
        if not entry.name.startswith(f"{kind}-"):
            continue
        if (
            entry.is_symlink()
            or not entry.is_dir()
            or not (entry / metadata_name).is_file()
        ):
            issues.append(
                MigrationIssue(
                    "blocker",
                    f"MALFORMED_{kind.upper()}_RECORD",
                    f"Malformed {kind} record: {entry}.",
                )
            )
            continue
        try:
            metadata = yaml.safe_load(
                (entry / metadata_name).read_text(encoding="utf-8")
            )
        except (OSError, yaml.YAMLError):
            issues.append(
                MigrationIssue(
                    "blocker",
                    f"MALFORMED_{kind.upper()}_RECORD",
                    f"Malformed {kind} metadata: {entry / metadata_name}.",
                )
            )
            continue
        if (
            not isinstance(metadata, dict)
            or metadata.get("id") != entry.name
            or metadata.get("type") != kind
            or (
                metadata.get("kind") is not None
                and metadata.get("kind") != kind
            )
        ):
            issues.append(
                MigrationIssue(
                    "blocker",
                    f"MALFORMED_{kind.upper()}_RECORD",
                    f"Metadata does not match {entry.name}.",
                )
            )
            continue
        count += 1
    return count, issues


def _sibling_root(project_root: Path, sibling_ledger_root: Path | None) -> Path:
    if sibling_ledger_root is not None:
        return sibling_ledger_root.expanduser().resolve(strict=False)
    return (project_root.parent / "ledger").resolve(strict=False)



def _planledger_container(sibling_root: Path) -> Path:
    return sibling_root / "planledger"




def _candidate_sources(
    project_root: Path,
    config_path: Path | None,
    sibling_root: Path,
    canonical_uuid: str | None,
) -> list[tuple[MigrationSourceKind, Path, Path | None]]:
    candidates: list[tuple[MigrationSourceKind, Path, Path | None]] = []
    seen: set[Path] = set()

    def add(kind: MigrationSourceKind, path: Path) -> None:
        resolved = path.resolve(strict=False)
        if resolved in seen or not resolved.exists():
            return
        seen.add(resolved)
        candidates.append((kind, resolved, config_path))

    repository = project_root / ".ledger" / "plan" / "data"
    if repository.exists():
        add("repository_local_proposal", repository)
    if config_path is not None and config_path.is_file():
        try:
            configured = _toml(config_path).get("storage", {}).get("planledger_dir")
        except PlanledgerError:
            configured = None
        if isinstance(configured, str) and configured:
            path = Path(configured).expanduser()
            if not path.is_absolute():
                path = project_root / path
            add(
                "legacy_local" if path.resolve().is_relative_to(project_root) else "legacy_external",
                path,
            )
    namespace_root = sibling_root / "projects"
    if namespace_root.is_dir():
        for candidate in namespace_root.glob("*/project/plan/planledger"):
            if candidate.is_dir():
                add("namespaced_workspace", candidate)
    legacy_container = sibling_root / "plan" / "planledger"
    if legacy_container.is_dir():
        add("old_canonical", legacy_container)
    container = _planledger_container(sibling_root)
    binding = container / BINDING_FILENAME
    if container.exists() and (
        (container / "storage.yaml").exists()
        or (container / "plans").exists()
        or (container / "workshops").exists()
    ):
        if not binding.is_file() or canonical_uuid is None:
            add("direct_sibling_unbound", container)
        else:
            try:
                bound_uuid = _toml(binding).get("project_uuid")
            except PlanledgerError:
                bound_uuid = None
            if bound_uuid == canonical_uuid:
                add("direct_sibling_unbound", container)
    old = project_root / ".ledger" / "plan" / "ledgers" / "main"
    if old.exists():
        add("old_canonical", old)
    return candidates


def _copy_items(source: Path | None, target: Path) -> tuple[MigrationCopyItem, ...]:
    if source is None or not source.exists():
        return ()
    items: list[MigrationCopyItem] = []
    recognized = {"storage.yaml", "plans", "workshops", "allocations", "migrations"}
    for top in source.iterdir():
        if top.name == BINDING_FILENAME:
            continue
        if top.name not in recognized:
            items.append(
                MigrationCopyItem(
                    top, target / top.name, "unknown", "block-conflict", "sha256"
                )
            )
            continue
        if top.is_symlink():
            items.append(
                MigrationCopyItem(
                    top, target / top.name, "unknown", "block-conflict", "sha256"
                )
            )
            continue
        if top.is_file():
            items.append(
                MigrationCopyItem(top, target / top.name, "state", "copy", "sha256")
            )
        else:
            for child in top.rglob("*"):
                if child.is_symlink():
                    items.append(
                        MigrationCopyItem(
                            child,
                            target / child.relative_to(source),
                            "data",
                            "block-conflict",
                            "sha256",
                        )
                    )
                elif child.is_file():
                    items.append(
                        MigrationCopyItem(
                            child,
                            target / child.relative_to(source),
                            "data",
                            "copy",
                            "sha256",
                        )
                    )
    return tuple(items)


def inspect_migration(  # noqa: C901
    start: Path,
    *,
    source: Path | None = None,
    environ: Mapping[str, str] | None = None,
    sibling_ledger_root: Path | None = None,
) -> PlanledgerMigrationInspection:
    effective_environment = os.environ if environ is None else environ
    if effective_environment.get("LEDGER_WORKSPACE_ROOT"):
        raise PlanledgerError(
            "PLANLEDGER_WORKSPACE_ENV_UNSUPPORTED",
            "Unset LEDGER_WORKSPACE_ROOT before migration.",
        )
    start = start.resolve()
    locator = locate_project(start)
    project_root = locator.project_root if locator is not None else start
    manifest_path = project_root / ".ledger" / "ledger.toml"
    local_path = project_root / ".ledger" / "ledger.local.toml"
    stable_path = project_root / ".ledger" / "plan" / "config.toml"
    sibling = _sibling_root(project_root, sibling_ledger_root)
    container = _planledger_container(sibling)
    marker = sibling / ".ledger-store"
    config_candidates = [
        project_root / "planledger.toml",
        project_root / ".planledger.toml",
    ]
    source_config = next((path for path in config_candidates if path.is_file()), None)
    canonical_uuid = _manifest_uuid(manifest_path)
    source_candidates = _candidate_sources(
        project_root, source_config, sibling, canonical_uuid
    )
    if source is not None:
        selected = source.expanduser().resolve(strict=False)
        source_candidates = [
            item for item in source_candidates if item[1].resolve() == selected
        ]
        if not source_candidates and selected.exists():
            source_candidates = [("legacy_external", selected, source_config)]
    issues: list[MigrationIssue] = []
    if local_path.is_file():
        try:
            workspace_local = _toml(local_path).get("storage", {}).get("workspace", {})
            if isinstance(workspace_local, dict) and "root" in workspace_local:
                configured_root = Path(str(workspace_local["root"])).expanduser()
                if not configured_root.is_absolute():
                    configured_root = project_root / configured_root
                if configured_root.resolve(strict=False) != sibling:
                    issues.append(
                        MigrationIssue(
                            "blocker",
                            "WORKSPACE_ROOT_CONFLICT",
                            "Shared local config contains a workspace root override for another root.",
                        )
                    )
            elif isinstance(workspace_local, dict) and workspace_local.get(
                "provider"
            ) not in (None, "sibling-ledger"):
                issues.append(
                    MigrationIssue(
                        "blocker",
                        "WORKSPACE_PROVIDER_CONFLICT",
                        "Shared local config selects another workspace provider.",
                    )
                )
        except (PlanledgerError, TypeError, ValueError) as exc:
            issues.append(
                MigrationIssue("blocker", "WORKSPACE_LOCAL_CONFIG_INVALID", str(exc))
            )
    if len(source_candidates) > 1 and source is None:
        issues.append(
            MigrationIssue(
                "blocker",
                "MULTIPLE_SOURCE_ROOTS",
                "Multiple Planledger source roots were found; pass --source explicitly.",
            )
        )
    selected_kind: MigrationSourceKind = "uninitialized"
    source_data: Path | None = None
    if source_candidates:
        selected_kind, source_data, source_config = source_candidates[0]
    elif manifest_path.is_file():
        selected_kind = "canonical"
    source_uuid = _source_uuid(source_config, source_data)
    project_uuid = canonical_uuid or source_uuid
    target = container / (project_uuid or "unresolved")
    target_binding = target / BINDING_FILENAME
    current_state = None
    if (target / "storage.yaml").is_file():
        current_state = _state(target)[0].get("schema_version")
    current_provider = None
    if local_path.is_file():
        try:
            current_provider = (
                _toml(local_path).get("storage", {}).get("workspace", {}).get("provider")
            )
        except PlanledgerError:
            current_provider = None
    if (
        source is None
        and manifest_path.is_file()
        and local_path.is_file()
        and stable_path.is_file()
        and target_binding.is_file()
        and current_state == 4
        and current_provider == "sibling-ledger"
    ):
        source_candidates = []
        source_config = None
        selected_kind = "canonical"
        source_data = None
    if not sibling.exists():
        issues.append(
            MigrationIssue(
                "blocker",
                "SIBLING_ROOT_MISSING",
                f"Canonical sibling store is missing: {sibling}.",
                ("planledger migrate apply --create-sibling-store",),
            )
        )
    elif sibling.is_symlink() or not sibling.is_dir():
        issues.append(
            MigrationIssue(
                "blocker",
                "SIBLING_ROOT_NOT_DIRECTORY",
                f"Canonical sibling store is not a directory: {sibling}.",
            )
        )
    elif not _regular(marker):
        issues.append(
            MigrationIssue(
                "blocker",
                "SIBLING_ROOT_UNMARKED",
                f"Sibling store marker is missing or invalid: {marker}.",
            )
        )
    if source_data is not None:
        state, state_issues = _state(source_data)
        issues.extend(state_issues)
        plan_count, plan_issues = _count_records(source_data, "plan")
        workshop_count, workshop_issues = _count_records(source_data, "workshop")
        issues.extend(plan_issues + workshop_issues)
        source_binding = source_data / BINDING_FILENAME
        if source_binding.is_file() and project_uuid is not None:
            try:
                bound_uuid = _toml(source_binding).get("project_uuid")
            except PlanledgerError:
                bound_uuid = None
            if bound_uuid != project_uuid:
                issues.append(
                    MigrationIssue(
                        "blocker",
                        "SOURCE_BINDING_UUID_MISMATCH",
                        "Source binding belongs to another project.",
                    )
                )
        state_schema = state.get("schema_version") if isinstance(state.get("schema_version"), int) else None
        next_plan = state.get("next_plan_id") if isinstance(state.get("next_plan_id"), int) else None
        next_workshop = state.get("next_workshop_id") if isinstance(state.get("next_workshop_id"), int) else None
        if state.get("next_plan_id") is not None and next_plan is None:
            issues.append(MigrationIssue("blocker", "STATE_COUNTER_INVALID", "Legacy next_plan_id is malformed."))
        if state.get("next_workshop_id") is not None and next_workshop is None:
            issues.append(MigrationIssue("blocker", "STATE_COUNTER_INVALID", "Legacy next_workshop_id is malformed."))
    else:
        plan_count = workshop_count = 0
        state_schema = None
        next_plan = next_workshop = None
    if target.exists() and target.is_symlink():
        issues.append(
            MigrationIssue(
                "blocker",
                "TARGET_SYMLINK",
                f"Migration target is a symlink: {target}.",
            )
        )
    if target.exists() and target.is_dir():
        if target_binding.is_file():
            try:
                target_uuid = _toml(target_binding).get("project_uuid")
            except PlanledgerError:
                target_uuid = None
            if target_uuid != project_uuid:
                issues.append(
                    MigrationIssue(
                        "blocker",
                        "BINDING_UUID_MISMATCH",
                        f"Target binding belongs to {target_uuid}, expected {project_uuid}.",
                    )
                )
        target_has_unbound_data = any(target.iterdir()) and (
            source_data is None or source_data.resolve() != target.resolve()
        )
        if not target_binding.exists() and target_has_unbound_data:
            issues.append(
                MigrationIssue(
                    "blocker",
                    "BINDING_MISSING",
                    f"Non-empty target is unbound: {target}.",
                )
            )
    copy_items = _copy_items(source_data, target)
    if any(item.action == "block-conflict" for item in copy_items):
        issues.append(MigrationIssue("blocker", "UNKNOWN_SOURCE_ENTRY", "Source contains unknown or symlinked entries."))
    ready = not any(issue.severity == "blocker" for issue in issues)
    migration_required = selected_kind not in {"uninitialized", "canonical"} or not target_binding.exists()
    return PlanledgerMigrationInspection(
        project_root=project_root,
        source_kind=selected_kind,
        source_config_path=source_config,
        source_data_root=source_data,
        source_project_uuid=source_uuid,
        canonical_project_uuid=canonical_uuid,
        sibling_store_root=sibling,
        sibling_marker_path=marker,
        target_data_root=target,
        target_binding_path=target_binding,
        manifest_path=manifest_path,
        ledger_local_config_path=local_path,
        stable_config_path=stable_path,
        plan_count=plan_count,
        workshop_count=workshop_count,
        source_state_schema=state_schema,
        legacy_next_plan_id=next_plan,
        legacy_next_workshop_id=next_workshop,
        copy_items=copy_items,
        issues=tuple(issues),
        ready=ready,
        migration_required=migration_required,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def inspection_to_dict(inspection: PlanledgerMigrationInspection) -> dict[str, Any]:
    payload = _jsonable(inspection)
    payload["kind"] = "planledger_migration_inspection"
    payload["schema_version"] = 1
    payload["status"] = "ready" if inspection.ready else "blocked"
    payload["source"] = {
        "kind": inspection.source_kind,
        "path": str(inspection.source_data_root)
        if inspection.source_data_root
        else None,
    }
    payload["target"] = {
        "provider": "sibling-ledger",
        "store_root": str(inspection.sibling_store_root),
        "data_root": str(inspection.target_data_root),
    }
    payload["commands"] = {"apply": "planledger migrate apply"}
    return cast(dict[str, Any], payload)


def _backup_path(
    path: Path, backup_root: Path, project_root: Path, records: list[dict[str, Any]]
) -> None:
    if not path.exists() or path.is_symlink():
        return
    relative = Path("files") / (
        path.resolve().relative_to(project_root.resolve())
        if path.resolve().is_relative_to(project_root.resolve())
        else Path(path.name)
    )
    destination = backup_root / relative
    if path.is_dir():
        shutil.copytree(path, destination, symlinks=True)
        for child in path.rglob("*"):
            if child.is_file() and not child.is_symlink():
                records.append(
                    {
                        "original": str(child),
                        "backup": str(
                            backup_root
                            / Path("files")
                            / (
                                child.resolve().relative_to(project_root.resolve())
                                if child.resolve().is_relative_to(
                                    project_root.resolve()
                                )
                                else Path(child.name)
                            )
                        ),
                        "sha256": _sha256(child),
                        "size": child.stat().st_size,
                    }
                )
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
        records.append(
            {
                "original": str(path),
                "backup": str(destination),
                "sha256": _sha256(path),
                "size": path.stat().st_size,
            }
        )


def _copy_tree_no_overwrite(
    source: Path, destination: Path, copied: list[str], skipped: list[str]
) -> None:
    if source.is_symlink():
        raise PlanledgerError(
            "PLANLEDGER_MIGRATION_SYMLINK", f"Refusing to copy symlink: {source}."
        )
    if source.is_dir():
        destination.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            _copy_tree_no_overwrite(child, destination / child.name, copied, skipped)
        return
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink() or not destination.is_file():
            raise PlanledgerError(
                "PLANLEDGER_DESTINATION_CONFLICT",
                f"Destination conflict: {destination}.",
            )
        if _sha256(source) == _sha256(destination):
            skipped.append(str(destination))
            return
        raise PlanledgerError(
            "PLANLEDGER_DESTINATION_CONFLICT",
            f"Differing destination file: {destination}.",
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    copied.append(str(destination))


def _canonical_state(source: Path | None, staged: Path) -> None:
    value: dict[str, Any] = {}
    if source is not None and (source / "storage.yaml").is_file():
        loaded = yaml.safe_load((source / "storage.yaml").read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            value = loaded
    state = {
        "schema_version": 4,
        "active_plan_id": value.get("active_plan_id") or None,
        "active_workshop_id": value.get("active_workshop_id") or None,
        "created_at": value.get("created_at")
        or datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "updated_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
    (staged / "storage.yaml").write_text(
        yaml.safe_dump(state, sort_keys=False), encoding="utf-8"
    )


def _write_binding(path: Path, project_uuid: str) -> None:
    path.write_text(
        f'schema_version = 1\nproject_uuid = "{project_uuid}"\nledger = "planledger"\nmount = "data"\n',
        encoding="utf-8",
    )


def _activate_config(
    inspection: PlanledgerMigrationInspection, project_uuid: str, project_name: str
) -> None:
    inspection.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if inspection.manifest_path.is_file():
        document = toml_parse(inspection.manifest_path.read_text(encoding="utf-8"))
    else:
        document = toml_parse(
            toml_dumps(
                {
                    "schema_version": 2,
                    "project": {"uuid": project_uuid, "name": project_name},
                    "storage": {
                        "workspace": {
                            "default_provider": "user-data",
                            "namespace": "ledgerwerk",
                        },
                        "cache": {
                            "default_provider": "user-cache",
                            "namespace": "ledgerwerk",
                        },
                    },
                    "ledgers": {},
                }
            )
        )
    document["schema_version"] = 2
    project = document.setdefault("project", {})
    project["uuid"] = project_uuid
    if project_name:
        project["name"] = project_name
    ledgers = document.setdefault("ledgers", {})
    ledgers["planledger"] = {
        "config": {"location": "project", "path": "plan/config.toml"},
        "mounts": {
            "data": {
                "storage": "workspace",
                "scope": "project",
                "path": f"planledger/{project_uuid}",
            }
        },
    }
    inspection.manifest_path.write_text(toml_dumps(document), encoding="utf-8")
    local = (
        toml_parse(inspection.ledger_local_config_path.read_text(encoding="utf-8"))
        if inspection.ledger_local_config_path.is_file()
        else toml_parse("schema_version = 1\n")
    )
    local["schema_version"] = 1
    storage = local.setdefault("storage", {})
    workspace = storage.get("workspace")
    if workspace is not None and "root" in workspace:
        configured_root = Path(str(workspace["root"])).expanduser()
        if not configured_root.is_absolute():
            configured_root = inspection.project_root / configured_root
        if configured_root.resolve(strict=False) != inspection.sibling_store_root:
            raise PlanledgerError(
                "PLANLEDGER_WORKSPACE_ROOT_CONFLICT",
                "Migration cannot replace a workspace root override for another root.",
            )
        workspace.pop("root", None)
    if workspace is not None and workspace.get("provider") not in (
        None,
        "sibling-ledger",
    ):
        raise PlanledgerError(
            "PLANLEDGER_WORKSPACE_PROVIDER_CONFLICT",
            "Migration cannot replace another workspace provider.",
        )
    storage["workspace"] = {"provider": "sibling-ledger"}
    inspection.ledger_local_config_path.parent.mkdir(parents=True, exist_ok=True)
    inspection.ledger_local_config_path.write_text(toml_dumps(local), encoding="utf-8")
    stable = (
        toml_parse(inspection.stable_config_path.read_text(encoding="utf-8"))
        if inspection.stable_config_path.is_file()
        else toml_parse(
            toml_dumps(
                {"config_version": 1, "ledger": {"code": "pl", "name": "planledger"}}
            )
        )
    )
    stable["config_version"] = 1
    stable.pop("project_uuid", None)
    stable.pop("project_name", None)
    stable.pop("storage", None)
    inspection.stable_config_path.parent.mkdir(parents=True, exist_ok=True)
    inspection.stable_config_path.write_text(toml_dumps(stable), encoding="utf-8")


def apply_migration(
    inspection: PlanledgerMigrationInspection,
    *,
    backup_dir: Path | None = None,
    create_sibling_store: bool = False,
    retire_source: bool = False,
    backup: bool = True,
) -> PlanledgerMigrationResult:
    fresh = inspect_migration(
        inspection.project_root,
        source=inspection.source_data_root,
        sibling_ledger_root=inspection.sibling_store_root,
    )
    issues = [
        issue
        for issue in fresh.issues
        if not (
            create_sibling_store
            and issue.code in {"SIBLING_ROOT_MISSING", "SIBLING_ROOT_UNMARKED"}
        )
    ]
    if any(issue.severity == "blocker" for issue in issues):
        raise PlanledgerError(
            "PLANLEDGER_MIGRATION_BLOCKED",
            "Migration is blocked; inspect the reported issues before applying.",
            remediation=[
                issue.message for issue in issues if issue.severity == "blocker"
            ],
        )
    if not fresh.sibling_store_root.exists():
        fresh.sibling_store_root.mkdir(parents=True)
    marker = fresh.sibling_marker_path
    if not marker.exists():
        if any(fresh.sibling_store_root.iterdir()):
            raise PlanledgerError(
                "PLANLEDGER_SIBLING_ROOT_NOT_EMPTY",
                f"Cannot create marker in non-empty store: {fresh.sibling_store_root}.",
            )
        marker.touch()
    project_uuid = (
        fresh.canonical_project_uuid or fresh.source_project_uuid or str(uuid4())
    )
    if fresh.target_data_root.name == "unresolved":
        target = _planledger_container(fresh.sibling_store_root) / project_uuid
        fresh = replace(
            fresh,
            target_data_root=target,
            target_binding_path=target / BINDING_FILENAME,
            canonical_project_uuid=fresh.canonical_project_uuid or project_uuid,
        )
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = (
        backup_dir
        or (fresh.project_root / ".ledger" / "backups" / f"planledger-{timestamp}")
    ).resolve()
    backup.mkdir(parents=True, exist_ok=False)
    backup_records: list[dict[str, Any]] = []
    for path in (
        fresh.source_config_path,
        fresh.manifest_path,
        fresh.ledger_local_config_path,
        fresh.stable_config_path,
        fresh.source_data_root,
        fresh.target_data_root,
    ):
        if path is not None:
            _backup_path(path, backup, fresh.project_root, backup_records)
    (backup / "inspection.json").write_text(
        json.dumps(inspection_to_dict(fresh), indent=2, default=str), encoding="utf-8"
    )
    staging = (
        fresh.sibling_store_root
        / "plan"
        / f".planledger-migration-{project_uuid}-{timestamp}-{uuid4().hex[:8]}"
    )
    staging.mkdir(parents=True, exist_ok=False)
    copied: list[str] = []
    skipped: list[str] = []
    try:
        if fresh.target_data_root.exists() and any(fresh.target_data_root.iterdir()):
            _copy_tree_no_overwrite(fresh.target_data_root, staging, copied, skipped)
        if fresh.source_data_root is not None:
            _copy_tree_no_overwrite(fresh.source_data_root, staging, copied, skipped)
        _canonical_state(fresh.source_data_root, staging)
        (staging / "allocations" / "plans").mkdir(parents=True, exist_ok=True)
        (staging / "allocations" / "workshops").mkdir(parents=True, exist_ok=True)
        (staging / "migrations").mkdir(parents=True, exist_ok=True)
        _write_binding(staging / BINDING_FILENAME, project_uuid)
        fresh.target_data_root.parent.mkdir(parents=True, exist_ok=True)
        if fresh.target_data_root.exists():
            _copy_tree_no_overwrite(staging, fresh.target_data_root, copied, skipped)
            shutil.rmtree(staging)
        else:
            staging.replace(fresh.target_data_root)
        project_name = fresh.project_root.name
        if fresh.manifest_path.is_file():
            try:
                project_name = str(
                    _toml(fresh.manifest_path).get("project", {}).get("name")
                    or project_name
                )
            except PlanledgerError:
                pass
        _activate_config(fresh, project_uuid, project_name)
        receipt = (
            fresh.target_data_root
            / "migrations"
            / f"{timestamp}-ledgercore-0.4-sibling-storage.json"
        )
        verification = {
            "binding": True,
            "state_schema": 4,
            "target": str(fresh.target_data_root),
            "taskledger_preserved": True,
        }
        receipt.write_text(
            json.dumps(
                {
                    "source_kind": fresh.source_kind,
                    "source": str(fresh.source_data_root)
                    if fresh.source_data_root
                    else None,
                    "target": str(fresh.target_data_root),
                    "backup": str(backup),
                    "copied": copied,
                    "skipped": skipped,
                    "verification": verification,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if (
            retire_source
            and fresh.source_data_root is not None
            and fresh.source_data_root.resolve() != fresh.target_data_root.resolve()
        ):
            retired = fresh.source_data_root.with_name(
                f"{fresh.source_data_root.name}.retired-{timestamp}"
            )
            fresh.source_data_root.replace(retired)
        (backup / "backup-manifest.json").write_text(
            json.dumps(backup_records, indent=2), encoding="utf-8"
        )
        return PlanledgerMigrationResult(
            fresh,
            backup,
            receipt,
            tuple(copied),
            tuple(skipped),
            not retire_source,
            verification,
        )
    except Exception:
        if staging.exists():
            # Keep failed staging available for explicit inspection/resume.
            pass
        raise


def result_to_dict(result: PlanledgerMigrationResult) -> dict[str, Any]:
    payload: dict[str, Any] = cast(dict[str, Any], _jsonable(result))
    payload["inspection"] = inspection_to_dict(result.inspection)
    return payload
