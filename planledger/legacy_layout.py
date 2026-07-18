"""Planledger-only legacy source discovery for migration.

These helpers recognize the historical Planledger layouts (``planledger.toml``,
``.planledger.toml``, ``.ledger/plan/data``, ``.ledger/plan/ledgers/main``,
direct ``../ledger/plan/planledger``, the namespace ``workspace`` path, and
unbound stray data). They never modify the filesystem and never produce a
canonical Planledger workspace.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from planledger.errors import PlanledgerError

LEGACY_CONFIG_FILENAMES: tuple[str, str] = ("planledger.toml", ".planledger.toml")

LegacySourceKind = Literal[
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
    "schema_migration_required",
]


@dataclass(frozen=True, slots=True)
class LegacySource:
    kind: LegacySourceKind
    project_root: Path
    legacy_config_path: Path | None = None
    legacy_data_root: Path | None = None
    legacy_external_root: Path | None = None
    project_uuid: str | None = None
    blockers: tuple[str, ...] = ()
    retired_artifacts: tuple[Path, ...] = ()


def _read_toml(path: Path) -> dict[str, object]:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PlanledgerError(
            "PLANLEDGER_MIGRATION_CONFIG_INVALID",
            f"Invalid TOML source: {path}.",
        ) from exc
    if not isinstance(value, dict):
        raise PlanledgerError(
            "PLANLEDGER_MIGRATION_CONFIG_INVALID",
            f"Legacy configuration must be a TOML table: {path}.",
        )
    return value


def _discover_retired_artifacts(project_root: Path) -> tuple[Path, ...]:
    candidates = (
        project_root / ".planledger" / "ledgers" / "main",
        project_root / ".ledger" / "plan" / "data",
        project_root / ".ledger" / "plan" / "ledgers" / "main",
    )
    return tuple(path for path in candidates if path.exists())


def discover_legacy_source(project_root: Path) -> LegacySource:  # noqa: C901
    project_root = project_root.resolve(strict=False)
    ledger_dir = project_root / ".ledger"
    retired_artifacts = _discover_retired_artifacts(project_root)
    manifest_path = ledger_dir / "ledger.toml"
    if manifest_path.is_file():
        try:
            document = _read_toml(manifest_path)
        except PlanledgerError:
            return LegacySource(
                kind="invalid",
                project_root=project_root,
                legacy_config_path=manifest_path,
                blockers=(f"invalid manifest: {manifest_path}",),
            )
        schema = document.get("schema_version")
        if schema == 3:
            return LegacySource(
                kind="canonical",
                project_root=project_root,
                retired_artifacts=retired_artifacts,
            )
        if schema == 2:
            return LegacySource(
                kind="schema_migration_required",
                project_root=project_root,
                legacy_config_path=manifest_path,
            )

    candidates: list[LegacySource] = []
    for name in ("planledger.toml", ".planledger.toml"):
        candidate = project_root / name
        if not candidate.is_file():
            continue
        try:
            document = _read_toml(candidate)
        except PlanledgerError:
            continue
        project_uuid_obj = document.get("project", {})
        project_uuid: str | None = None
        if isinstance(project_uuid_obj, dict):
            uuid_obj = project_uuid_obj.get("uuid")
            if isinstance(uuid_obj, str):
                project_uuid = uuid_obj
        storage_obj = document.get("storage")
        legacy_data_root: Path | None = None
        legacy_external_root: Path | None = None
        kind: LegacySourceKind = "legacy_local"
        if isinstance(storage_obj, dict):
            planledger_dir_obj = storage_obj.get("planledger_dir")
            if isinstance(planledger_dir_obj, str):
                candidate_path = Path(planledger_dir_obj).expanduser()
                if not candidate_path.is_absolute():
                    candidate_path = (project_root / candidate_path).resolve()
                else:
                    candidate_path = candidate_path.resolve()
                if (
                    candidate_path.parent.parent
                    and candidate_path.parent.parent.name == "ledger"
                    and candidate_path.parent.parent.parent == project_root.parent
                ):
                    legacy_external_root = candidate_path.parent.parent
                    kind = "legacy_external"
                else:
                    kind = "legacy_local"
                legacy_data_root = candidate_path
        candidates.append(
            LegacySource(
                kind=kind,
                project_root=project_root,
                legacy_config_path=candidate,
                legacy_data_root=legacy_data_root,
                legacy_external_root=legacy_external_root,
                project_uuid=project_uuid,
            )
        )

    legacy_data_dir = ledger_dir / "plan" / "data"
    if legacy_data_dir.is_dir():
        storage_yaml = legacy_data_dir / "storage.yaml"
        candidates.append(
            LegacySource(
                kind="legacy_local",
                project_root=project_root,
                legacy_data_root=legacy_data_dir,
                legacy_config_path=storage_yaml if storage_yaml.is_file() else None,
            )
        )

    legacy_ledgers_main = ledger_dir / "plan" / "ledgers" / "main"
    if legacy_ledgers_main.is_dir():
        candidates.append(
            LegacySource(
                kind="legacy_local",
                project_root=project_root,
                legacy_data_root=legacy_ledgers_main,
            )
        )

    candidate_external_data = project_root.parent / "ledger" / "plan" / "planledger"
    if candidate_external_data.is_dir():
        candidates.append(
            LegacySource(
                kind="direct_sibling_unbound",
                project_root=project_root,
                legacy_data_root=candidate_external_data,
                legacy_external_root=project_root.parent / "ledger",
            )
        )

    proposed_data = ledger_dir / "planledger"
    if proposed_data.is_dir() and not manifest_path.is_file():
        candidates.append(
            LegacySource(
                kind="repository_local_proposal",
                project_root=project_root,
                legacy_data_root=proposed_data,
            )
        )

    siblings_data = project_root.parent / "ledger" / "planledger"
    if siblings_data.is_dir() and not manifest_path.is_file():
        candidates.append(
            LegacySource(
                kind="namespaced_workspace",
                project_root=project_root,
                legacy_data_root=siblings_data,
                legacy_external_root=project_root.parent / "ledger",
            )
        )

    if not candidates:
        return LegacySource(kind="uninitialized", project_root=project_root)
    if len(candidates) > 1:
        blockers = tuple(
            f"{c.kind}: {c.legacy_data_root or c.legacy_config_path}"
            for c in candidates
        )
        return LegacySource(
            kind="invalid",
            project_root=project_root,
            blockers=blockers,
        )
    return candidates[0]


def read_legacy_state(state_path: Path) -> dict[str, object]:
    """Read a legacy ``storage.yaml`` state into a plain mapping."""
    import yaml

    try:
        value = yaml.safe_load(state_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PlanledgerError(
            "PLANLEDGER_STATE_INVALID", f"Legacy state is unreadable: {state_path}."
        ) from exc
    if not isinstance(value, dict):
        raise PlanledgerError(
            "PLANLEDGER_STATE_INVALID",
            f"Legacy state must be a mapping: {state_path}.",
        )
    return value


def read_legacy_active(state: dict[str, object], key: str) -> str | None:
    value = state.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def read_legacy_counter(state: dict[str, object], key: str) -> int | None:
    value = state.get(key)
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise PlanledgerError(
        "PLANLEDGER_LEGACY_COUNTER_INVALID",
        f"Legacy counter {key!r} must be an integer; got {type(value).__name__}.",
    )


def read_legacy_project_uuid(state: dict[str, object]) -> str | None:
    value = state.get("project_uuid")
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return None


__all__ = [
    "LEGACY_CONFIG_FILENAMES",
    "LegacySource",
    "LegacySourceKind",
    "discover_legacy_source",
    "read_legacy_active",
    "read_legacy_counter",
    "read_legacy_project_uuid",
    "read_legacy_state",
]
