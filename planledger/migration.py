"""Planledger migration orchestration.

Generic filesystem copy/stage/switch/recovery is owned by Ledgercore 0.6.
This module composes Ledgercore planning and execution with the Planledger
domain transformations and provides read-only inspection.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

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
    RecoveryAssessment,
    StorageMigrationPlan,
    build_planledger_data_target,
    build_planledger_migration_manifest,
    execute_planledger_layout_migration,
    load_planledger_ledger_layout,
    plan_planledger_layout_migration,
    plan_planledger_prepared_migration,
    resolve_planledger_external_root,
    resolve_planledger_migration_data_path,
    resolve_planledger_target_layout,
    validate_planledger_layout_migration,
    write_planledger_migration_stage_binding,
)
from planledger.legacy_layout import (
    LegacySource,
    discover_legacy_source,
)
from planledger.write_lock import (
    acquire_planledger_write_lock,
    require_planledger_quiescent,
)

MigrationMode = Literal["copy"]
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
    project_uuid: str | None
    target_data_storage: MigrationTarget
    target_external_root: Path | None
    target_data_root: Path | None
    target_config_path: Path | None
    domain_plan: MigrationReceipt | None
    ledgercore_plan: StorageMigrationPlan | None
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
            "data_root": str(plan.target_data_root) if plan.target_data_root else None,
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
            "active_workshop_preserved": (
                result.domain_receipt.preserve_active_workshop_id
            ),
            "ledgercore_migration_id": result.domain_receipt.ledgercore_migration_id,
            "ledgercore_journal_path": (
                str(result.domain_receipt.ledgercore_journal_path)
                if result.domain_receipt.ledgercore_journal_path
                else None
            ),
            "ledgercore_phase": result.domain_receipt.ledgercore_phase,
            "ledgercore_items_completed": (
                result.domain_receipt.ledgercore_items_completed
            ),
            "ledgercore_source_removed": (
                result.domain_receipt.ledgercore_source_removed
            ),
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
    source_mount = layout.resolved_layout.mounts.get(DATA_MOUNT)
    if source_mount is None:
        raise PlanledgerError(
            "PLANLEDGER_MOUNT_INVALID",
            "Planledger layout has no data mount.",
        )
    source_data_root = source_mount.path
    source_state_schema: int | None = None
    domain_plan: MigrationReceipt | None = None
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
        target_external_root_path = resolve_planledger_external_root(
            target_external_root, project_root=project_root
        )
    target_manifest, target_overrides = build_planledger_data_target(
        layout.loaded_project,
        storage=target_data_storage,
        external_root=(
            str(target_external_root_path)
            if target_external_root_path is not None
            else None
        ),
        target="local",
    )
    target_layout = resolve_planledger_target_layout(
        layout.loaded_project, target_manifest, target_overrides
    )
    target_mount = target_layout.mounts.get(DATA_MOUNT)
    if target_mount is None:
        raise PlanledgerError(
            "PLANLEDGER_MOUNT_INVALID",
            "Resolved target layout has no data mount.",
        )
    storage_changed = (
        source_data_root.resolve(strict=False)
        != target_mount.path.resolve(strict=False)
    )
    ledgercore_plan = None
    blockers: list[MigrationIssue] = []
    if storage_changed:
        ledgercore_plan = plan_planledger_layout_migration(
            layout.loaded_project,
            target_manifest,
            target_overrides,
            mounts=(DATA_MOUNT,),
            include_config=False,
        )
        validation = validate_planledger_layout_migration(
            ledgercore_plan, project_root=project_root
        )
        if not validation.valid:
            blockers.extend(
                MigrationIssue(
                    severity="blocker",
                    code="PLANLEDGER_STORAGE_MIGRATION_PLAN_INVALID",
                    message=error,
                )
                for error in validation.errors
            )
    migration_required = storage_changed or (
        domain_plan is not None and source_state_schema != 4
    )
    return MigrationPlan(
        source_kind=(
            "canonical" if source_state_schema == 4 else "schema_migration_required"
        ),
        source_config_path=layout.locator.manifest_path,
        source_data_root=source_data_root,
        source_state_schema=source_state_schema,
        project_uuid=layout.loaded_project.manifest.project_uuid,
        target_data_storage=target_data_storage,
        target_external_root=target_external_root_path,
        target_data_root=target_mount.path,
        target_config_path=target_layout.tool_config_path,
        domain_plan=domain_plan,
        ledgercore_plan=ledgercore_plan,
        blockers=tuple(blockers),
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
    blockers = [
        MigrationIssue(
            severity="blocker",
            code="PLANLEDGER_LEGACY_SOURCE_AMBIGUOUS",
            message=str(blocker),
        )
        for blocker in legacy.blockers
    ]
    if legacy.legacy_data_root is None:
        blockers.append(
            MigrationIssue(
                severity="blocker",
                code="PLANLEDGER_LEGACY_DATA_MISSING",
                message="No Planledger legacy data source was discovered.",
            )
        )
    project_uuid = legacy.project_uuid
    if project_uuid is None:
        blockers.append(
            MigrationIssue(
                severity="blocker",
                code="PLANLEDGER_PROJECT_UUID_MISSING",
                message="Migration requires a project UUID from the legacy source.",
            )
        )

    target_external_root_path: Path | None = None
    if target_data_storage == "external":
        target_external_root_path = resolve_planledger_external_root(
            target_external_root, project_root=project_root
        )
    target_data_root: Path | None = None
    if project_uuid is not None:
        target_manifest = build_planledger_migration_manifest(
            project_root,
            project_uuid=project_uuid,
            project_name=project_root.name,
            data_storage=target_data_storage,
            external_root=(
                str(target_external_root_path)
                if target_external_root_path is not None
                else None
            ),
        )
        try:
            target_data_root = resolve_planledger_migration_data_path(
                project_root, target_manifest
            )
        except PlanledgerError as exc:
            blockers.append(
                MigrationIssue(
                    severity="blocker",
                    code=exc.code,
                    message=exc.message,
                )
            )

    return MigrationPlan(
        source_kind=legacy.kind,
        source_config_path=legacy.legacy_config_path,
        source_data_root=legacy.legacy_data_root,
        source_state_schema=source_state_schema,
        project_uuid=project_uuid,
        target_data_storage=target_data_storage,
        target_external_root=target_external_root_path,
        target_data_root=target_data_root,
        target_config_path=project_root / ".ledger" / "ledger.toml",
        domain_plan=domain_plan,
        ledgercore_plan=None,
        blockers=tuple(blockers),
        warnings=(),
        migration_required=legacy.kind != "canonical"
        and legacy.legacy_data_root is not None,
    )


def inspect_migration(project_root: Path) -> MigrationPlan:
    return plan_migration(project_root)


def apply_migration(
    project_root: Path,
    *,
    mode: MigrationMode = "copy",
    target_data_storage: MigrationTarget = "external",
    target_external_root: str = "../ledger",
    dry_run: bool = False,
) -> MigrationResult:
    project_root = project_root.resolve(strict=False)
    if mode != "copy":
        raise PlanledgerError(
            "PLANLEDGER_MIGRATION_MOVE_UNSUPPORTED",
            "Ledgercore storage migrations are copy-only and preserve the source.",
            remediation=["Use --mode copy or omit --mode."],
        )
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
    project_uuid = plan.project_uuid
    if project_uuid is None:
        raise PlanledgerError(
            "PLANLEDGER_PROJECT_UUID_MISSING",
            "Migration cannot start without a project UUID.",
        )
    with acquire_planledger_write_lock(
        project_root,
        command="migrate apply",
        project_uuid=project_uuid,
    ):
        staged_root: Path | None = None
        ledger_plan = plan.ledgercore_plan
        if plan.domain_plan is not None and plan.source_data_root is not None:
            staged_root = _prepare_staged_layout(plan)
            apply_domain_migration(
                plan.source_data_root,
                staged_root,
                plan.domain_plan,
                migration_tag="planledger-domain-schema-4",
            )
            write_planledger_migration_stage_binding(
                staged_root,
                project_uuid=project_uuid,
                storage=plan.target_data_storage,
            )
            if ledger_plan is None:
                target_manifest = build_planledger_migration_manifest(
                    project_root,
                    project_uuid=project_uuid,
                    project_name=project_root.name,
                    data_storage=plan.target_data_storage,
                    external_root=(
                        str(plan.target_external_root)
                        if plan.target_external_root is not None
                        else None
                    ),
                )
                ledger_plan = plan_planledger_prepared_migration(
                    staged_root,
                    plan.target_data_root or staged_root,
                    project_root=project_root,
                    project_uuid=project_uuid,
                    storage=plan.target_data_storage,
                    replace_owned=(
                        plan.source_data_root is not None
                        and plan.target_data_root is not None
                        and plan.source_data_root.resolve(strict=False)
                        == plan.target_data_root.resolve(strict=False)
                    ),
                    config_changes=target_manifest,
                )
        if ledger_plan is None:
            raise PlanledgerError(
                "PLANLEDGER_DOMAIN_MIGRATION_REQUIRES_TRANSACTION",
                "Migration requires a real Ledgercore plan or a domain transaction.",
            )
        validation = validate_planledger_layout_migration(
            ledger_plan, project_root=project_root
        )
        if not validation.valid:
            raise PlanledgerError(
                "PLANLEDGER_STORAGE_MIGRATION_PLAN_INVALID",
                "Migration plan validation failed: " + "; ".join(validation.errors),
            )
        ledger_result = execute_planledger_layout_migration(
            ledger_plan,
            quiescence_check=lambda: require_planledger_quiescent(project_root),
            verify="sha256",
            project_root=project_root,
        )
        receipt_path = write_migration_receipt(
            plan.target_data_root or staged_root or project_root,
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
            ledgercore_migration_id=ledger_result.migration_id,
            ledgercore_journal_path=ledger_result.journal_path,
            ledgercore_phase=ledger_result.phase,
            ledgercore_items_completed=ledger_result.items_completed,
            ledgercore_source_removed=ledger_result.source_removed,
            mode=mode,
        )
        if staged_root is not None and ledger_result.phase == "complete":
            shutil.rmtree(staged_root, ignore_errors=True)
        domain_receipt = replace(
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
            ledgercore_migration_id=ledger_result.migration_id,
            ledgercore_journal_path=ledger_result.journal_path,
            ledgercore_phase=ledger_result.phase,
            ledgercore_items_completed=ledger_result.items_completed,
            ledgercore_source_removed=ledger_result.source_removed,
        )
    return MigrationResult(
        plan=plan,
        receipt_path=receipt_path,
        mode=mode,
        copied=("storage.yaml",),
        skipped=(),
        source_preserved=True,
        domain_receipt=domain_receipt,
    )


def _prepare_staged_layout(plan: MigrationPlan) -> Path:
    if plan.target_data_root is None:
        if plan.source_data_root is None:
            raise PlanledgerError(
                "PLANLEDGER_STORAGE_MIGRATION_BLOCKED",
                "Migration has no source or target data root.",
            )
        staged = plan.source_data_root
    else:
        staged = plan.target_data_root.parent / (plan.target_data_root.name + ".staged")
    staged.mkdir(parents=True, exist_ok=True)
    return staged


__all__ = [
    "MigrationIssue",
    "MigrationMode",
    "MigrationPlan",
    "MigrationResult",
    "MigrationTarget",
    "apply_migration",
    "inspect_migration",
    "inspect_storage_migration",
    "inspection_to_dict",
    "plan_migration",
    "recover_storage_migration",
    "result_to_dict",
]

def _select_storage_migration_journal(
    project_root: Path, journal_path: Path | None = None
) -> tuple[Path, object] | None:
    from planledger.ledgercore_backend import (
        discover_planledger_storage_migration_journals,
    )

    candidates = discover_planledger_storage_migration_journals(
        project_root, journal_path=journal_path
    )
    if journal_path is not None and not candidates:
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_JOURNAL_INVALID",
            f"No Planledger migration journal found at {journal_path}.",
        )
    if not candidates:
        return None
    incomplete = [
        candidate
        for candidate in candidates
        if getattr(candidate[1], "phase", None) != "complete"
    ]
    if len(incomplete) > 1 and journal_path is None:
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_MIGRATION_AMBIGUOUS",
            "Multiple incomplete Planledger migration journals exist.",
            remediation=["Specify --journal PATH."],
        )
    if incomplete:
        return incomplete[0]
    return max(candidates, key=lambda candidate: candidate[0].stat().st_mtime_ns)


def _assessment_to_dict(
    path: Path, assessment: RecoveryAssessment
) -> dict[str, object]:
    return {
        "exists": True,
        "migration_id": assessment.migration_id,
        "journal_path": str(path),
        "phase": assessment.phase,
        "recommendation": assessment.recommendation,
        "blockers": list(assessment.blockers),
        "resumable": assessment.resumable,
        "rollbackable": assessment.rollbackable,
        "complete": assessment.complete,
    }


def inspect_storage_migration(
    project_root: Path, *, journal_path: Path | None = None
) -> dict[str, object]:
    """Assess a Planledger Ledgercore schema-3 migration journal read-only."""
    from planledger.ledgercore_backend import assess_planledger_storage_migration

    selected = _select_storage_migration_journal(project_root, journal_path)
    if selected is None:
        return {
            "exists": False,
            "journal_path": None,
            "phase": "absent",
            "recommendation": "complete",
            "blockers": [],
            "resumable": False,
            "rollbackable": False,
            "complete": True,
        }
    path, _journal = selected
    assessment = assess_planledger_storage_migration(
        path, project_root=project_root.resolve(strict=False)
    )
    return _assessment_to_dict(path, assessment)


def recover_storage_migration(
    project_root: Path,
    *,
    journal_path: Path | None = None,
    policy: Literal["auto", "resume", "rollback"] = "auto",
    dry_run: bool = False,
) -> dict[str, object]:
    """Assess or recover a Ledgercore storage migration safely."""
    from planledger.ledgercore_backend import (
        assess_planledger_storage_migration,
        recover_planledger_storage_migration,
    )

    selected = _select_storage_migration_journal(project_root, journal_path)
    if selected is None:
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_RECOVERY_REQUIRED",
            "No Planledger storage migration journal exists.",
        )
    path, journal = selected
    if dry_run:
        assessment = assess_planledger_storage_migration(
            path, project_root=project_root.resolve(strict=False)
        )
        return _assessment_to_dict(path, assessment)
    project_uuid = getattr(journal, "project_uuid", None)
    if not isinstance(project_uuid, str) or not project_uuid:
        raise PlanledgerError(
            "PLANLEDGER_STORAGE_JOURNAL_INVALID",
            "Selected migration journal has no project UUID.",
        )
    with acquire_planledger_write_lock(
        project_root.resolve(strict=False),
        command="storage recover",
        project_uuid=project_uuid,
    ):
        result = recover_planledger_storage_migration(
            path,
            policy=policy,
            dry_run=False,
            quiescence_check=lambda: require_planledger_quiescent(
                project_root
            ),
            project_root=project_root.resolve(strict=False),
        )
    if isinstance(result, RecoveryAssessment):
        return _assessment_to_dict(path, result)
    return {
        "exists": True,
        "migration_id": result.migration_id,
        "journal_path": str(result.journal_path),
        "phase": result.phase,
        "items_completed": result.items_completed,
        "source_removed": result.source_removed,
        "recommendation": result.recommendation,
        "complete": result.phase == "complete",
    }
