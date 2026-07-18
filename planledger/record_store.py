"""Shared filesystem mechanics for Planledger records."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

RecordKind = Literal["plan", "workshop"]


@dataclass(frozen=True, slots=True)
class RecordKindSpec:
    kind: RecordKind
    id_attribute: str
    directory_name: str
    metadata_filename: str
    active_state_key: str
    rendered_prefix: str


PLAN_RECORD_SPEC = RecordKindSpec(
    kind="plan",
    id_attribute="plan_id",
    directory_name="plans",
    metadata_filename="plan.yaml",
    active_state_key="active_plan_id",
    rendered_prefix="plan",
)
WORKSHOP_RECORD_SPEC = RecordKindSpec(
    kind="workshop",
    id_attribute="workshop_id",
    directory_name="workshops",
    metadata_filename="workshop.yaml",
    active_state_key="active_workshop_id",
    rendered_prefix="workshop",
)


def collection_directory(workspace: Any, spec: RecordKindSpec) -> Path:
    return cast(Path, workspace.planledger_dir) / spec.directory_name


def record_directory(workspace: Any, spec: RecordKindSpec, record_id: str) -> Path:
    return collection_directory(workspace, spec) / record_id


def metadata_path_from_directory(path: Path, spec: RecordKindSpec) -> Path:
    return path / spec.metadata_filename


def metadata_path(workspace: Any, spec: RecordKindSpec, record_id: str) -> Path:
    return metadata_path_from_directory(
        record_directory(workspace, spec, record_id), spec
    )


def rendered_directory(record: Any) -> Path:
    return cast(Path, record.path) / "rendered"


def latest_rendered_file(record: Any) -> Path:
    return rendered_directory(record) / "latest.md"


def versioned_rendered_file(
    record: Any, spec: RecordKindSpec, version: int | None = None
) -> Path:
    selected = version if version is not None else record.version
    record_id = getattr(record, spec.id_attribute)
    return rendered_directory(record) / f"{record_id}-v{selected:04d}.md"


def versions_directory(record: Any) -> Path:
    return cast(Path, record.path) / "versions"


def version_snapshot_directory(record: Any, version: int) -> Path:
    return versions_directory(record) / f"v{version:04d}"


def list_version_labels(record: Any) -> list[str]:
    directory = versions_directory(record)
    if not directory.is_dir():
        return []
    return sorted(
        entry.name
        for entry in directory.iterdir()
        if entry.is_dir() and entry.name.startswith("v")
    )


def read_component_content(record: Any, component: str) -> str:
    path = record.path / "components" / component
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def read_component_contents(
    record: Any, component_paths: dict[str, str]
) -> dict[str, str]:
    return {
        key: read_component_content(record, path)
        for key, path in component_paths.items()
    }
