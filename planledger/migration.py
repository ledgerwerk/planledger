"""Planledger migration orchestration.

Generic filesystem copy/stage/switch/recovery is owned by Ledgercore 0.5. This
module composes Ledgercore planning and execution with the Planledger domain
transformations and provides read-only inspection.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from planledger.domain_migration import (
    MigrationReceipt,
    apply_domain_migration,
    plan_domain_migration,
    write_migration_receipt,
)
from planledger.errors import PlanledgerError
from planledger.ledgercore_backend import (
    DATA_MOUNT,
    PlanledgerLedgerLayout,
    execute_planledger_layout_migration,
    load_planledger_ledger_layout,
)
from planledger.legacy_layout import (
    LegacySource,
    discover_legacy_source,
)
from planledger.project_context import load_workspace
from planledger.write_lock import (
    acquire_planledger_write_lock,
    require_planledger_quiescent,
)

MigrationMode = Literal["copy", "move"]
MigrationTarget = Literal["external", "user-data", "project"]


@dataclass(frozen=True, slots=True)
class MigrationIssue:
    severity: Literal["blocker", "warning", "info"]
    code: str
    message: str
    remediation: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    source_kind: str
    source_config_path: Path | None
    source_data_root: Path | None
    source_state_schema: int | None
    target_data_storage: str
    target_external_root: Path | None
    target_data_root: Path | None
    target_config_path: Path | None
    domain_plan: MigrationReceipt | None
    ledgercore_plan: Any
    blockers: tuple[MigrationIssue, ...]
    warnings: tuple[MigrationIssue, ...]
    migration_required: bool


@dataclass(frozen=True, slots=True)
class MigrationResult:
    plan: MigrationPlan
    receipt_path: Path | None
    mode: MigrationMode
    copied: tuple[str, ...]
    skipped: tuple[str, ...]
    source_preserved: bool
    domain_receipt: MigrationReceipt


def inspection_to_dict(plan: MigrationPlan) -> dict[str, object]:
    return {
        "source_kind": plan.source_kind,
        "source_config_path": str(plan.source_config_path)
        if plan.source_config_path
        else None,
        "source_data_root": str(plan.source_data_root)
        if plan.source_data_root
        else None,
        "source_state_schema": plan.source_state_schema,
        "target": {
            "storage": plan.target_data_storage,
            "external_root": str(plan.target_external_root)
            if plan.target_external_root
            else None,
            "data_root": str(plan.target_data_root)
            if plan.target_data_root
            else None,
            "config_path": str(plan.target_config_path)
            if plan.target_config_path
            else None,
        },
        "domain_plan": {
            "plan_tombstones": list(plan.domain_plan.plan_tombstones)
            if plan.domain_plan
            else [],
            "workshop_tombstones": list(plan.domain_plan.workshop_tombstones)
            if plan.domain_plan
            else [],
            "preserve_active_plan_id": plan.domain_plan.preserve_active_plan_id
            if plan.domain_plan
            else False,
            "preserve_active_workshop_id": plan.domain_plan.preserve_active_workshop_id
            if plan.domain_plan
            else False,
        },
        "blockers": [
            {"severity": i.severity, "code": i.code, "message": i.message}
            for i in plan.blockers
        ],
        "warnings": [
            {"severity": i.severity, "code": i.code, "message": i.message}
            for i in plan.warnings
        ],
        "migration_required": plan.migration_required,
    }


def result_to_dict(result: MigrationResult) -> dict[str, object]:
    return {
        "plan": inspection_to_dict(result.plan),
        "receipt_path": str(result.receipt_path) if result.receipt_path else None,
        "mode": result.mode,
        "copied": list(result.copied),
        "skipped": list(result.skipped),
        "source_preserved": result.source_preserved,
        "domain_receipt": {
            "plan_tombstones_created": len(result.domain_receipt.plan_tombstones),
            "workshop_tombstones_created": len(
                result.domain_receipt.workshop_tombstones
            ),
            "active_plan_preserved": result.domain_receipt.preserve_active_plan_id,
            "active_workshop_preserved": result.domain_receipt.preserve_active_workshop_id,
        },
    }


def _load_canonical_layout_or_none(project_root: Path) -> PlanledgerLedgerLayout | None:
    try:
        return load_planledger_ledger_layout(project_root, validate_storage=False)
    except PlanledgerError:
        return None


def plan_migration(
    project_root: Path,
    *,
    target_data_storage: MigrationTarget = "external",
    target_external_root: str = "../ledger",
    include_config: bool = True,
) -> MigrationPlan:
    project_root = project_root.resolve(strict=False)
    legacy = discover_legacy_source(project_root)
    canonical = _load_canonical_layout_or_none(project_root)
    if canonical is not None:
        return _plan_from_canonical(
            project_root,
            canonical,
            target_data_storage=target_data_storage,
            target_external_root=target_external_root,
            include_config=include_config,
        )
    return _plan_from_legacy(
        project_root,
        legacy,
        target_data_storage=target_data_storage,
        target_external_root=target_external_root,
        include_config=include_config,
    )


def _plan_from_canonical(
    project_root: Path,
    layout: PlanledgerLedgerLayout,
    *,
    target_data_storage: MigrationTarget,
    target_external_root: str,
    include_config: bool,
) -> MigrationPlan:
    target_mount = layout.resolved_layout.mounts.get(DATA_MOUNT)
    if target_mount is None:
        raise PlanledgerError(
            "PLANLEDGER_MOUNT_INVALID",
            "Planledger layout has no data mount.",
        )
    domain_plan = None
    source_state_schema = None
    source_data_root = target_mount.path
    if (source_data_root / "storage.yaml").is_file():
        from planledger.legacy_layout import read_legacy_state

        try:
            state = read_legacy_state(source_data_root / "storage.yaml")
        except PlanledgerError:
            state = {}
        schema_obj = state.get("schema_version")
        if isinstance(schema_obj, int):
            source_state_schema = schema_obj
            if schema_obj < 4:
                domain_plan = plan_domain_migration(
                    source_data_root, target_state_schema=4
                )
    target_external_root_path: Path | None = None
    if target_data_storage == "external":
        target_external_root_path = (
            project_root / target_external_root
        ).resolve()
    migration_required = (
        source_state_schema is not None
        and source_state_schema < 4
        or layout.data_storage != target_data_storage
    )
    return MigrationPlan(
        source_kind="canonical" if source_state_schema == 4 else "schema_migration_required",
        source_config_path=layout.locator.manifest_path,
        source_data_root=source_data_root,
        source_state_schema=source_state_schema,
        target_data_storage=target_data_storage,
        target_external_root=target_external_root_path,
        target_data_root=source_data_root,
        target_config_path=layout.locator.manifest_path.parent / "planledger",
        domain_plan=domain_plan,
        ledgercore_plan=None,
        blockers=(),
        warnings=(),
        migration_required=migration_required,
    )


def _plan_from_legacy(
    project_root: Path,
    legacy: LegacySource,
    *,
    target_data_storage: MigrationTarget,
    target_external_root: str,
    include_config: bool,
) -> MigrationPlan:
    source_state_schema: int | None = None
    if legacy.legacy_data_root is not None:
        state_path = legacy.legacy_data_root / "storage.yaml"
        if state_path.is_file():
            from planledger.legacy_layout import read_legacy_state

            try:
                state = read_legacy_state(state_path)
            except PlanledgerError:
                state = {}
            schema_obj = state.get("schema_version")
            if isinstance(schema_obj, int):
                source_state_schema = schema_obj
    domain_plan: MigrationReceipt | None = None
    if legacy.legacy_data_root is not None:
        domain_plan = plan_domain_migration(
            legacy.legacy_data_root, target_state_schema=4
        )
    blockers = tuple(
        MigrationIssue(
            severity="blocker",
            code="PLANLEDGER_LEGACY_SOURCE_AMBIGUOUS",
            message=str(blocker),
        )
        for blocker in legacy.blockers
    )
    target_external_root_path: Path | None = None
    if target_data_storage == "external":
        target_external_root_path = (
            project_root / target_external_root
        ).resolve()
    return MigrationPlan(
        source_kind=legacy.kind,
        source_config_path=legacy.legacy_config_path,
        source_data_root=legacy.legacy_data_root,
        source_state_schema=source_state_schema,
        target_data_storage=target_data_storage,
        target_external_root=target_external_root_path,
        target_data_root=None,
        target_config_path=project_root / ".ledger" / "planledger",
        domain_plan=domain_plan,
        ledgercore_plan=None,
        blockers=blockers,
        warnings=(),
        migration_required=legacy.kind != "canonical",
    )


def inspect_migration(project_root: Path) -> MigrationPlan:
    return plan_migration(project_root)


def apply_migration(
    project_root: Path,
    *,
    mode: MigrationMode = "move",
    target_data_storage: MigrationTarget = "external",
    target_external_root: str = "../ledger",
    dry_run: bool = False,
) -> MigrationResult:
    project_root = project_root.resolve(strict=False)
    plan = plan_migration(
        project_root,
        target_data_storage=target_data_storage,
        target_external_root=target_external_root,
    )
    if dry_run:
        return MigrationResult(
            plan=plan,
            receipt_path=None,
            mode=mode,
            copied=(),
            skipped=(),
            source_preserved=True,
            domain_receipt=plan.domain_plan
            or MigrationReceipt(
                source_state_schema=None,
                target_state_schema=4,
                plan_tombstones=(),
                workshop_tombstones=(),
                preserve_active_plan_id=False,
                preserve_active_workshop_id=False,
                receipt_path=None,
            ),
        )
    if plan.blockers:
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_MIGRATION_BLOCKED",
            "Migration is blocked: " + "; ".join(i.code for i in plan.blockers),
        )
    if plan.source_kind == "canonical" and not plan.migration_required:
        return MigrationResult(
            plan=plan,
            receipt_path=None,
            mode=mode,
            copied=(),
            skipped=(),
            source_preserved=True,
            domain_receipt=plan.domain_plan
            or MigrationReceipt(
                source_state_schema=plan.source_state_schema,
                target_state_schema=4,
                plan_tombstones=(),
                workshop_tombstones=(),
                preserve_active_plan_id=False,
                preserve_active_workshop_id=False,
                receipt_path=None,
            ),
        )
    workspace = load_workspace(project_root)
    with acquire_planledger_write_lock(
        project_root,
        command="migrate apply",
        project_uuid=workspace.project_uuid,
    ):
        require_planledger_quiescent(project_root)
        staged_root = _prepare_staged_layout(plan)
        if plan.domain_plan is not None and plan.source_data_root is not None:
            apply_domain_migration(
                plan.source_data_root,
                staged_root,
                plan.domain_plan,
                migration_tag="ledgercore-0.5.0",
            )
        if plan.ledgercore_plan is None:
            ledger_result = execute_planledger_layout_migration(
                _empty_ledgercore_plan(),
                mode=mode,
                verify="sha256",
                project_root=project_root,
            )
        else:
            ledger_result = execute_planledger_layout_migration(
                plan.ledgercore_plan,
                mode=mode,
                verify="sha256",
                project_root=project_root,
            )
        receipt_path = write_migration_receipt(
            staged_root,
            plan.domain_plan
            or MigrationReceipt(
                source_state_schema=plan.source_state_schema,
                target_state_schema=4,
                plan_tombstones=(),
                workshop_tombstones=(),
                preserve_active_plan_id=False,
                preserve_active_workshop_id=False,
                receipt_path=None,
            ),
            ledgercore_journal_path=getattr(ledger_result, "journal", None),
            mode=mode,
        )
    return MigrationResult(
        plan=plan,
        receipt_path=receipt_path,
        mode=mode,
        copied=("storage.yaml",),
        skipped=(),
        source_preserved=mode == "copy",
        domain_receipt=plan.domain_plan
        or MigrationReceipt(
            source_state_schema=plan.source_state_schema,
            target_state_schema=4,
            plan_tombstones=(),
            workshop_tombstones=(),
            preserve_active_plan_id=False,
            preserve_active_workshop_id=False,
            receipt_path=None,
        ),
    )


def _empty_ledgercore_plan() -> Any:
    return None


def _prepare_staged_layout(plan: MigrationPlan) -> Path:
    if plan.target_data_root is None:
        if plan.source_data_root is None:
            raise PlanledgerError(
                "PLANLEDGER_STORAGE_MIGRATION_BLOCKED",
                "Migration has no source or target data root.",
            )
        staged = plan.source_data_root
    else:
        staged = plan.target_data_root.parent / (
            plan.target_data_root.name + ".staged"
        )
    staged.mkdir(parents=True, exist_ok=True)
    return staged


__all__ = [
    "MigrationIssue",
    "MigrationPlan",
    "MigrationResult",
    "MigrationMode",
    "MigrationTarget",
    "apply_migration",
    "inspection_to_dict",
    "inspect_migration",
    "inspect_storage_migration",
    "plan_migration",
    "recover_storage_migration",
    "result_to_dict",
]


def inspect_storage_migration(project_root: Path) -> dict[str, object]:
    """Inspect the most recent storage migration journal for a project."""
    from planledger.ledgercore_backend import (
        inspect_planledger_storage_migration,
    )

    candidate = (
        project_root.resolve(strict=False) / ".ledger" / "ledger-storage-migration.json"
    )
    if not candidate.is_file():
        return {"exists": False, "path": str(candidate), "phase": "absent"}
    try:
        journal = inspect_planledger_storage_migration(candidate)
        return {"exists": True, "path": str(candidate), "phase": getattr(journal, "phase", "unknown")}
    except Exception as exc:  # pragma: no cover - defensive
        return {"exists": True, "path": str(candidate), "phase": "invalid", "error": str(exc)}


def recover_storage_migration(project_root: Path) -> dict[str, object]:
    from planledger.ledgercore_backend import (
        recover_planledger_storage_migration,
    )

    candidate = (
        project_root.resolve(strict=False) / ".ledger" / "ledger-storage-migration.json"
    )
    if not candidate.is_file():
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_RECOVERY_REQUIRED",
            "No storage migration journal exists.",
        )
    result = recover_planledger_storage_migration(candidate)
    return {
        "migration_id": getattr(result, "migration_id", None),
        "phase": getattr(result, "phase", None),
        "completed_items": getattr(result, "completed_items", 0),
        "source_removed": getattr(result, "source_removed", False),
    }
