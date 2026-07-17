# ruff: noqa: E501
from __future__ import annotations

import os
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

from planledger.errors import PlanledgerError

BINDING_FILENAME = ".ledger-project.toml"


@dataclass(frozen=True, slots=True)
class PlanledgerProjectBinding:
    schema_version: int
    project_uuid: str
    project_name: str | None
    ledger: str
    mount: str


def binding_path(data_root: Path) -> Path:
    return data_root / BINDING_FILENAME


def _load(path: Path) -> dict[str, Any]:

    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (FileNotFoundError, OSError) as exc:
        raise PlanledgerError(
            "PLANLEDGER_BINDING_MISSING", f"Binding is not readable: {path}."
        ) from exc
    if not isinstance(value, dict):
        raise PlanledgerError(
            "PLANLEDGER_BINDING_MALFORMED", f"Binding must be a TOML table: {path}."
        )
    return value


def _parse(document: dict[str, Any], path: Path) -> PlanledgerProjectBinding:
    schema = document.get("schema_version")
    project_uuid = document.get("project_uuid")
    project_name = document.get("project_name")
    ledger = document.get("ledger")
    mount = document.get("mount")
    if schema != 1 or not all(
        isinstance(item, str) and item for item in (project_uuid, ledger, mount)
    ) or (project_name is not None and not isinstance(project_name, str)):
        raise PlanledgerError(
            "PLANLEDGER_BINDING_MALFORMED", f"Invalid project binding: {path}."
        )
    return PlanledgerProjectBinding(
        1,
        cast(str, project_uuid),
        cast(str, project_name) if project_name is not None else None,
        cast(str, ledger),
        cast(str, mount),
    )


def read_project_binding(data_root: Path) -> PlanledgerProjectBinding | None:
    path = binding_path(data_root)
    if not path.exists():
        return None
    try:
        info = path.lstat()
    except OSError as exc:
        raise PlanledgerError(
            "PLANLEDGER_BINDING_MALFORMED", f"Cannot inspect binding: {path}."
        ) from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise PlanledgerError(
            "PLANLEDGER_BINDING_MALFORMED", f"Binding must be a regular file: {path}."
        )
    return _parse(_load(path), path)


def validate_project_binding(
    data_root: Path, *, project_uuid: str, project_name: str | None = None
 ) -> PlanledgerProjectBinding:
    binding = read_project_binding(data_root)
    if binding is None:
        raise PlanledgerError(
            "PLANLEDGER_BINDING_MISSING",
            f"Planledger data is not bound to project {project_uuid}: {binding_path(data_root)}.",
            remediation=["Run: planledger migrate apply"],
        )
    if binding.project_uuid != project_uuid:
        raise PlanledgerError(
            "PLANLEDGER_BINDING_UUID_MISMATCH",
            f"Binding belongs to project {binding.project_uuid}, not {project_uuid}.",
        )
    if (
        project_name is not None
        and binding.project_name is not None
        and binding.project_name != project_name
    ):
        raise PlanledgerError(
            "PLANLEDGER_BINDING_PROJECT_NAME_MISMATCH",
            f"Binding project name is {binding.project_name}, not {project_name}.",
        )
    if binding.ledger != "planledger":
        raise PlanledgerError(
            "PLANLEDGER_BINDING_LEDGER_MISMATCH", "Binding ledger must be planledger."
        )
    if binding.mount != "data":
        raise PlanledgerError(
            "PLANLEDGER_BINDING_MOUNT_MISMATCH", "Binding mount must be data."
        )
    return binding


def directory_is_effectively_empty(data_root: Path) -> bool:
    if not data_root.exists():
        return True
    if data_root.is_symlink() or not data_root.is_dir():
        return False
    return all(entry.name == BINDING_FILENAME for entry in data_root.iterdir())


def create_project_binding(
    data_root: Path, *, project_uuid: str, project_name: str | None = None
 ) -> PlanledgerProjectBinding:
    data_root.mkdir(parents=True, exist_ok=True)
    path = binding_path(data_root)
    name_line = f"project_name = {project_name!r}\n" if project_name is not None else ""
    document = (
        "schema_version = 1\n"
        f"project_uuid = {project_uuid!r}\n"
        + name_line
        + 'ledger = "planledger"\nmount = "data"\n'
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        return validate_project_binding(
            data_root, project_uuid=project_uuid, project_name=project_name
        )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(document)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return validate_project_binding(
        data_root, project_uuid=project_uuid, project_name=project_name
    )
