"""Planledger-specific domain transformations applied to staged data.

These helpers consume legacy storage files from the source directory and emit
schema-4 ``storage.yaml`` plus counter-gap tombstones into a staged directory.
They never touch the Ledgercore manifest or the binding markers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from planledger.errors import PlanledgerError
from planledger.identity import parse_plan_number, parse_workshop_number
from planledger.legacy_layout import (
    read_legacy_active,
    read_legacy_counter,
    read_legacy_state,
)


def _parse_prefixed(record_id: str, kind: str) -> int:
    if kind == "plan":
        return parse_plan_number(record_id)
    if kind == "workshop":
        return parse_workshop_number(record_id)
    raise ValueError(f"unknown kind {kind!r}")

DOMAIN_TOMBSTONE_SCHEMA = 1
MIGRATION_KIND_PLANLEDGER = "planledger"


@dataclass(frozen=True, slots=True)
class MigrationReceipt:
    source_state_schema: int | None
    target_state_schema: int
    plan_tombstones: tuple[str, ...]
    workshop_tombstones: tuple[str, ...]
    preserve_active_plan_id: bool
    preserve_active_workshop_id: bool
    receipt_path: Path | None


def _now_iso() -> str:
    from ledgercore.time import utc_now_iso

    return utc_now_iso()


def _format_record_toml(
    *,
    schema_version: int,
    record_id: str,
    reason: str,
    migration_tag: str,
) -> str:
    return (
        f"schema_version = {schema_version}\n"
        f"id = {record_id!r}\n"
        f"reason = {reason!r}\n"
        f"migration = {migration_tag!r}\n"
    )


def _parse_kind_directory(directory: Path, kind: str) -> list[str]:
    if not directory.is_dir():
        return []
    records: list[str] = []
    for entry in directory.iterdir():
        if not entry.is_dir() or entry.is_symlink():
            continue
        if not entry.name.startswith(f"{kind}-"):
            continue
        records.append(entry.name)
    return records


def _parse_tombstone_directory(directory: Path, kind: str) -> list[str]:
    if not directory.is_dir():
        return []
    tombstones: list[str] = []
    for entry in directory.iterdir():
        if entry.is_dir() or entry.is_symlink() or not entry.is_file():
            continue
        if not entry.name.startswith(f"{kind}-") or not entry.name.endswith(".toml"):
            continue
        tombstones.append(entry.name[: -len(".toml")])
    return tombstones


def _sorted_ids(records: tuple[str, ...] | list[str], kind: str) -> list[tuple[str, int]]:
    decorated: list[tuple[str, int]] = []
    for record in records:
        try:
            number = _parse_prefixed(record, kind)
        except ValueError:
            continue
        decorated.append((record, number))
    decorated.sort(key=lambda item: item[1])
    return decorated


def _compute_counter_gaps(
    existing_ids: tuple[str, ...],
    legacy_counter: int,
    kind: str,
) -> list[str]:
    if legacy_counter <= 0:
        return []
    occupied: dict[int, str] = {}
    for record_id in existing_ids:
        try:
            number = _parse_prefixed(record_id, kind)
        except ValueError:
            continue
        occupied.setdefault(number, record_id)
    gaps: list[str] = []
    for number in range(1, legacy_counter):
        if number in occupied:
            continue
        gaps.append(f"{kind}-{number:04d}")
    return gaps


def plan_domain_migration(
    source_root: Path,
    *,
    target_state_schema: int = 4,
) -> MigrationReceipt:
    state_path = source_root / "storage.yaml"
    source_state_schema: int | None = None
    plan_tombstones: tuple[str, ...] = ()
    workshop_tombstones: tuple[str, ...] = ()
    preserve_active_plan: bool = False
    preserve_active_workshop: bool = False
    if state_path.is_file():
        state = read_legacy_state(state_path)
        schema_obj = state.get("schema_version")
        if isinstance(schema_obj, int):
            source_state_schema = schema_obj
        # Legacy state may carry `project_uuid`; it is dropped silently during
        # migration per plan section 14.1. The new layout derives identity from
        # the Ledgercore manifest, not from Planledger state.
        try:
            plan_counter = read_legacy_counter(state, "next_plan_id")
            workshop_counter = read_legacy_counter(state, "next_workshop_id")
        except PlanledgerError:
            raise
        existing_plans = tuple(_parse_kind_directory(source_root / "plans", "plan"))
        existing_workshops = tuple(
            _parse_kind_directory(source_root / "workshops", "workshop")
        )
        existing_plan_allocations = tuple(
            _parse_kind_directory(source_root / "allocations" / "plans", "plan")
        )
        existing_workshop_allocations = tuple(
            _parse_kind_directory(
                source_root / "allocations" / "workshops", "workshop"
            )
        )
        existing_plan_tombstones = tuple(
            _parse_tombstone_directory(
                source_root / "allocations" / "plans", "plan"
            )
        )
        existing_workshop_tombstones = tuple(
            _parse_tombstone_directory(
                source_root / "allocations" / "workshops", "workshop"
            )
        )
        existing_plan_records = set(existing_plans) | set(existing_plan_allocations)
        existing_workshop_records = (
            set(existing_workshops) | set(existing_workshop_allocations)
        )
        plan_counter_value = plan_counter if plan_counter is not None else 0
        workshop_counter_value = (
            workshop_counter if workshop_counter is not None else 0
        )
        plan_tombstones_list = _compute_counter_gaps(
            tuple(existing_plan_records) + existing_plan_tombstones,
            plan_counter_value,
            "plan",
        )
        workshop_tombstones_list = _compute_counter_gaps(
            tuple(existing_workshop_records) + existing_workshop_tombstones,
            workshop_counter_value,
            "workshop",
        )
        plan_tombstones = tuple(sorted(plan_tombstones_list))
        workshop_tombstones = tuple(sorted(workshop_tombstones_list))
        active_plan = read_legacy_active(state, "active_plan_id")
        active_workshop = read_legacy_active(state, "active_workshop_id")
        if active_plan and active_plan in (existing_plan_records | set(plan_tombstones)):
            preserve_active_plan = True
        if active_workshop and active_workshop in (
            existing_workshop_records | set(workshop_tombstones)
        ):
            preserve_active_workshop = True
    return MigrationReceipt(
        source_state_schema=source_state_schema,
        target_state_schema=target_state_schema,
        plan_tombstones=plan_tombstones,
        workshop_tombstones=workshop_tombstones,
        preserve_active_plan_id=preserve_active_plan,
        preserve_active_workshop_id=preserve_active_workshop,
        receipt_path=None,
    )


def apply_domain_migration(
    source_root: Path,
    staged_root: Path,
    receipt: MigrationReceipt,
    *,
    migration_tag: str = "ledgercore-0.5.0",
    created_at: str | None = None,
) -> MigrationReceipt:
    import yaml

    state_path = source_root / "storage.yaml"
    source_state: dict[str, object] = {}
    if state_path.is_file():
        source_state = read_legacy_state(state_path)
    timestamp = created_at or _now_iso()
    target_state: dict[str, object] = {
        "schema_version": receipt.target_state_schema,
        "active_plan_id": read_legacy_active(source_state, "active_plan_id"),
        "active_workshop_id": read_legacy_active(source_state, "active_workshop_id"),
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    staged_state_path = staged_root / "storage.yaml"
    staged_state_path.parent.mkdir(parents=True, exist_ok=True)
    with staged_state_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(target_state, handle, sort_keys=False)

    for tombstone_id in receipt.plan_tombstones:
        directory = staged_root / "allocations" / "plans"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{tombstone_id}.toml"
        path.write_text(
            _format_record_toml(
                schema_version=DOMAIN_TOMBSTONE_SCHEMA,
                record_id=tombstone_id,
                reason="legacy_counter_gap",
                migration_tag=migration_tag,
            ),
            encoding="utf-8",
        )
    for tombstone_id in receipt.workshop_tombstones:
        directory = staged_root / "allocations" / "workshops"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{tombstone_id}.toml"
        path.write_text(
            _format_record_toml(
                schema_version=DOMAIN_TOMBSTONE_SCHEMA,
                record_id=tombstone_id,
                reason="legacy_counter_gap",
                migration_tag=migration_tag,
            ),
            encoding="utf-8",
        )

    for sub in ("plans", "workshops", "allocations", "migrations"):
        source_sub = source_root / sub
        if source_sub.is_dir():
            target_sub = staged_root / sub
            target_sub.mkdir(parents=True, exist_ok=True)
    return MigrationReceipt(
        source_state_schema=receipt.source_state_schema,
        target_state_schema=receipt.target_state_schema,
        plan_tombstones=receipt.plan_tombstones,
        workshop_tombstones=receipt.workshop_tombstones,
        preserve_active_plan_id=receipt.preserve_active_plan_id,
        preserve_active_workshop_id=receipt.preserve_active_workshop_id,
        receipt_path=receipt.receipt_path,
    )


def write_migration_receipt(
    staged_root: Path,
    receipt: MigrationReceipt,
    *,
    ledgercore_journal_path: Path | None,
    mode: str = "move",
    completed_at: str | None = None,
) -> Path:
    import json

    migrations_dir = staged_root / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    completed = completed_at or _now_iso()
    safe_tag = completed.replace(":", "").replace("-", "")
    receipt_path = migrations_dir / (
        f"{safe_tag}-planledger-ledgercore-0.5.json"
    )
    payload = {
        "schema_version": 1,
        "storage_schema_before": receipt.source_state_schema,
        "storage_schema_after": receipt.target_state_schema,
        "plan_tombstones_created": len(receipt.plan_tombstones),
        "workshop_tombstones_created": len(receipt.workshop_tombstones),
        "active_plan_preserved": receipt.preserve_active_plan_id,
        "active_workshop_preserved": receipt.preserve_active_workshop_id,
        "ledgercore_journal_path": str(ledgercore_journal_path)
        if ledgercore_journal_path
        else None,
        "mode": mode,
    }
    receipt_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return receipt_path


__all__ = [
    "DOMAIN_TOMBSTONE_SCHEMA",
    "MigrationReceipt",
    "apply_domain_migration",
    "plan_domain_migration",
    "write_migration_receipt",
]
