# ruff: noqa: E501
from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ledgercore.errors import IdFormatError
from ledgercore.yamlio import load_yaml_object

from planledger.errors import PlanledgerError
from planledger.identity import (
    format_plan_id,
    format_workshop_id,
    parse_plan_number,
    parse_workshop_number,
)
from planledger.project_context import Workspace

AllocationKind = Literal["plan", "workshop"]


@dataclass(frozen=True, slots=True)
class RecordAllocation:
    kind: AllocationKind
    local_id: str
    number: int
    source: Literal["record", "tombstone"]
    path: Path


@dataclass(frozen=True, slots=True)
class AllocationInventory:
    kind: AllocationKind
    allocations: tuple[RecordAllocation, ...]
    highest_number: int
    next_id: str

    @property
    def count(self) -> int:
        return len(self.allocations)


def _canonical_id(kind: AllocationKind, value: str) -> int:
    try:
        number = (
            parse_plan_number(value) if kind == "plan" else parse_workshop_number(value)
        )
    except IdFormatError as exc:
        raise PlanledgerError(
            "PLANLEDGER_ALLOCATION_INVALID",
            f"Non-canonical {kind} allocation name: {value}.",
        ) from exc
    expected = format_plan_id(number) if kind == "plan" else format_workshop_id(number)
    if value != expected:
        raise PlanledgerError(
            "PLANLEDGER_ALLOCATION_INVALID",
            f"Non-canonical {kind} allocation name: {value}.",
        )
    return number


def _record_metadata(path: Path, kind: AllocationKind) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise PlanledgerError(
            "PLANLEDGER_ALLOCATION_INVALID",
            f"Authoritative metadata must be a regular file: {path}.",
        )
    try:
        value = load_yaml_object(path, label=f"YAML file {path}")
    except Exception as exc:
        raise PlanledgerError(
            "PLANLEDGER_ALLOCATION_INVALID", f"Invalid allocation metadata: {path}."
        ) from exc
    if not isinstance(value, dict):
        raise PlanledgerError(
            "PLANLEDGER_ALLOCATION_INVALID",
            f"Allocation metadata must be a mapping: {path}.",
        )
    if (
        value.get("kind") != kind
        or value.get("type") != kind
        or value.get("id") != path.parent.name
    ):
        raise PlanledgerError(
            "PLANLEDGER_ALLOCATION_INVALID",
            f"Allocation metadata does not match {path.parent.name}: {path}.",
        )
    return value


def _tombstones_dir(workspace: Workspace, kind: AllocationKind) -> Path:
    return (
        workspace.planledger_dir
        / "allocations"
        / ("plans" if kind == "plan" else "workshops")
    )


def _records_dir(workspace: Workspace, kind: AllocationKind) -> Path:
    return workspace.planledger_dir / ("plans" if kind == "plan" else "workshops")


def _scan(kind: AllocationKind, workspace: Workspace) -> AllocationInventory:
    allocations: list[RecordAllocation] = []
    seen: set[int] = set()
    records = _records_dir(workspace, kind)
    if records.exists():
        if records.is_symlink() or not records.is_dir():
            raise PlanledgerError(
                "PLANLEDGER_ALLOCATION_INVALID",
                f"Allocation directory must be a directory: {records}.",
            )
        for candidate in sorted(records.iterdir()):
            if not candidate.name.startswith(f"{kind}-"):
                continue
            if candidate.is_symlink() or not candidate.is_dir():
                raise PlanledgerError(
                    "PLANLEDGER_ALLOCATION_INVALID",
                    f"Authoritative allocation must be a real directory: {candidate}.",
                )
            number = _canonical_id(kind, candidate.name)
            metadata_name = "plan.yaml" if kind == "plan" else "workshop.yaml"
            _record_metadata(candidate / metadata_name, kind)
            if number in seen:
                raise PlanledgerError(
                    "PLANLEDGER_ALLOCATION_DUPLICATE",
                    f"Duplicate {kind} allocation number: {number}.",
                )
            seen.add(number)
            allocations.append(
                RecordAllocation(kind, candidate.name, number, "record", candidate)
            )
    tombstones = _tombstones_dir(workspace, kind)
    if tombstones.exists():
        if tombstones.is_symlink() or not tombstones.is_dir():
            raise PlanledgerError(
                "PLANLEDGER_ALLOCATION_INVALID",
                f"Tombstone directory must be a directory: {tombstones}.",
            )
        suffix = ".toml"
        for candidate in sorted(tombstones.iterdir()):
            if not candidate.name.startswith(f"{kind}-"):
                continue
            if (
                candidate.is_symlink()
                or not candidate.is_file()
                or not candidate.name.endswith(suffix)
            ):
                raise PlanledgerError(
                    "PLANLEDGER_ALLOCATION_INVALID",
                    f"Invalid {kind} tombstone: {candidate}.",
                )
            local_id = candidate.stem
            number = _canonical_id(kind, local_id)
            try:
                with candidate.open("rb") as handle:
                    value = tomllib.load(handle)
            except (OSError, tomllib.TOMLDecodeError) as exc:
                raise PlanledgerError(
                    "PLANLEDGER_ALLOCATION_INVALID", f"Invalid tombstone: {candidate}."
                ) from exc
            if not isinstance(value, dict) or value.get("id") != local_id:
                raise PlanledgerError(
                    "PLANLEDGER_ALLOCATION_INVALID",
                    f"Tombstone metadata does not match {local_id}: {candidate}.",
                )
            if number in seen:
                raise PlanledgerError(
                    "PLANLEDGER_ALLOCATION_DUPLICATE",
                    f"Duplicate {kind} allocation number: {number}.",
                )
            seen.add(number)
            allocations.append(
                RecordAllocation(kind, local_id, number, "tombstone", candidate)
            )
    allocations.sort(key=lambda item: item.number)
    highest = allocations[-1].number if allocations else 0
    next_number = highest + 1
    next_id = (
        format_plan_id(next_number)
        if kind == "plan"
        else format_workshop_id(next_number)
    )
    return AllocationInventory(kind, tuple(allocations), highest, next_id)


def scan_plan_allocations(workspace: Workspace) -> AllocationInventory:
    return _scan("plan", workspace)


def scan_workshop_allocations(workspace: Workspace) -> AllocationInventory:
    return _scan("workshop", workspace)


def _reserve(
    workspace: Workspace, kind: AllocationKind, max_attempts: int
) -> tuple[str, Path]:
    directory = _records_dir(workspace, kind)
    directory.mkdir(parents=True, exist_ok=True)
    for _ in range(max_attempts):
        inventory = _scan(kind, workspace)
        number = inventory.highest_number + 1
        local_id = (
            format_plan_id(number) if kind == "plan" else format_workshop_id(number)
        )
        candidate = directory / local_id
        try:
            candidate.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            continue
        return local_id, candidate
    raise PlanledgerError(
        "PLANLEDGER_ALLOCATION_CONTENTION",
        f"Could not reserve a {kind} directory after {max_attempts} attempts.",
    )


def reserve_plan_directory(
    workspace: Workspace, *, max_attempts: int = 32
) -> tuple[str, Path]:
    return _reserve(workspace, "plan", max_attempts)


def reserve_workshop_directory(
    workspace: Workspace, *, max_attempts: int = 32
) -> tuple[str, Path]:
    return _reserve(workspace, "workshop", max_attempts)
