"""Workshop-specific storage paths backed by shared record mechanics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from planledger.record_store import (
    WORKSHOP_RECORD_SPEC,
    collection_directory,
    latest_rendered_file,
    metadata_path_from_directory,
    record_directory,
    rendered_directory,
    version_snapshot_directory,
    versioned_rendered_file,
    versions_directory,
)
from planledger.record_store import (
    metadata_path as record_metadata_path,
)


def workshops_dir(workspace: Any) -> Path:
    return collection_directory(workspace, WORKSHOP_RECORD_SPEC)


def workshop_dir(workspace: Any, workshop_id: str) -> Path:
    return record_directory(workspace, WORKSHOP_RECORD_SPEC, workshop_id)


def workshop_metadata_path_from_dir(path: Path) -> Path:
    return metadata_path_from_directory(path, WORKSHOP_RECORD_SPEC)


def workshop_metadata_path(workspace: Any, workshop_id: str) -> Path:
    return record_metadata_path(workspace, WORKSHOP_RECORD_SPEC, workshop_id)


def workshop_rendered_dir(workshop: Any) -> Path:
    return rendered_directory(workshop)


def latest_rendered_workshop_path(workshop: Any) -> Path:
    return latest_rendered_file(workshop)


def versioned_rendered_workshop_path(workshop: Any, version: int | None = None) -> Path:
    return versioned_rendered_file(workshop, WORKSHOP_RECORD_SPEC, version)


def workshop_versions_dir(workshop: Any) -> Path:
    return versions_directory(workshop)


def workshop_version_snapshot_dir(workshop: Any, version: int) -> Path:
    return version_snapshot_directory(workshop, version)
