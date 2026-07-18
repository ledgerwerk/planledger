"""Plan-specific storage paths backed by shared record mechanics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from planledger.record_store import (
    PLAN_RECORD_SPEC,
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


def plans_dir(workspace: Any) -> Path:
    return collection_directory(workspace, PLAN_RECORD_SPEC)


def plan_dir(workspace: Any, plan_id: str) -> Path:
    return record_directory(workspace, PLAN_RECORD_SPEC, plan_id)


def plan_metadata_path_from_dir(path: Path) -> Path:
    return metadata_path_from_directory(path, PLAN_RECORD_SPEC)


def plan_metadata_path(workspace: Any, plan_id: str) -> Path:
    return record_metadata_path(workspace, PLAN_RECORD_SPEC, plan_id)


def rendered_dir(plan: Any) -> Path:
    return rendered_directory(plan)


def latest_rendered_path(plan: Any) -> Path:
    return latest_rendered_file(plan)


def versioned_rendered_path(plan: Any, version: int | None = None) -> Path:
    return versioned_rendered_file(plan, PLAN_RECORD_SPEC, version)


def versions_dir(plan: Any) -> Path:
    return versions_directory(plan)


def version_snapshot_dir(plan: Any, version: int) -> Path:
    return version_snapshot_directory(plan, version)
