from __future__ import annotations

from typing import Any

from planledger.errors import PlanledgerError
from planledger.models import Record, Workspace
from planledger.storage import append_event, now_iso, save_record, update_record_timestamp

GOAL_STATUSES = {"exploring", "active", "fulfilled", "cancelled", "superseded", "parked"}
INITIATIVE_STATUSES = {
    "shaping",
    "planned",
    "executing",
    "fulfilled",
    "cancelled",
    "superseded",
    "parked",
}
PLAN_STATUSES = {"draft", "accepted", "superseded", "retired"}
SLICE_STATUSES = {
    "idea",
    "shaping",
    "ready-for-execution",
    "in-execution",
    "executed",
    "validated",
    "cancelled",
    "obsolete",
}

TERMINAL_GOAL_STATUSES = {"fulfilled", "cancelled", "superseded"}
ACTIVE_GOAL_STATUSES = {"exploring", "active"}
TERMINAL_INITIATIVE_STATUSES = {"fulfilled", "cancelled", "superseded"}
TERMINAL_PLAN_STATUSES = {"superseded", "retired"}
TERMINAL_SLICE_STATUSES = {"executed", "validated", "cancelled", "obsolete"}
EXECUTION_BLOCKING_GOAL_STATUSES = TERMINAL_GOAL_STATUSES | {"parked"}
EXECUTION_BLOCKING_INITIATIVE_STATUSES = TERMINAL_INITIATIVE_STATUSES | {"parked"}
EXECUTION_BLOCKING_PLAN_STATUSES = TERMINAL_PLAN_STATUSES
EXECUTION_BLOCKING_SLICE_STATUSES = {"cancelled", "obsolete"}

STATUS_SETS: dict[str, set[str]] = {
    "goal": GOAL_STATUSES,
    "initiative": INITIATIVE_STATUSES,
    "plan": PLAN_STATUSES,
    "slice": SLICE_STATUSES,
}
TERMINAL_STATUSES: dict[str, set[str]] = {
    "goal": TERMINAL_GOAL_STATUSES,
    "initiative": TERMINAL_INITIATIVE_STATUSES,
    "plan": TERMINAL_PLAN_STATUSES,
    "slice": TERMINAL_SLICE_STATUSES,
}
STATUSES_WITH_CLOSE_METADATA: dict[str, set[str]] = {
    "goal": TERMINAL_GOAL_STATUSES,
    "initiative": TERMINAL_INITIATIVE_STATUSES,
    "plan": TERMINAL_PLAN_STATUSES,
    "slice": {"cancelled", "obsolete"},
}
EXECUTION_BLOCKING_STATUSES: dict[str, set[str]] = {
    "goal": EXECUTION_BLOCKING_GOAL_STATUSES,
    "initiative": EXECUTION_BLOCKING_INITIATIVE_STATUSES,
    "plan": EXECUTION_BLOCKING_PLAN_STATUSES,
    "slice": EXECUTION_BLOCKING_SLICE_STATUSES,
}
MULTI_RELATION_FIELDS = {"related_goals", "invalidated_by", "supersedes"}


def is_terminal(kind: str, status: str | None) -> bool:
    if status is None:
        return False
    return status in TERMINAL_STATUSES.get(kind, set())


def require_not_terminal(record: Record, action: str) -> None:
    status_value = record.front_matter.get("status")
    status = str(status_value) if status_value is not None else None
    if not is_terminal(record.kind, status):
        return
    raise PlanledgerError(
        "terminal_record",
        f"Cannot {action} {record.kind} {record.record_id} because it is {status}.",
        remediation=[f"Inspect: planledger {record.kind} show {record.record_id}"],
    )


def blocks_execution(kind: str, status: str | None) -> bool:
    if status is None:
        return False
    return status in EXECUTION_BLOCKING_STATUSES.get(kind, set())


def _require_valid_status(kind: str, status: str) -> None:
    valid = STATUS_SETS.get(kind)
    if valid is None or status in valid:
        return
    raise PlanledgerError(
        "invalid_status",
        f"Invalid status {status!r} for {kind}. Allowed: {sorted(valid)}.",
    )


def _apply_close_metadata(
    record: Record,
    *,
    new_status: str,
    reason: str,
    actor: str,
) -> None:
    if new_status not in STATUSES_WITH_CLOSE_METADATA.get(record.kind, set()):
        return
    if not reason.strip():
        raise PlanledgerError(
            "invalid_transition",
            f"{record.kind} {record.record_id} requires a reason for status {new_status}.",
        )
    record.front_matter["closed_at"] = now_iso()
    record.front_matter["closed_by"] = actor
    record.front_matter["close_reason"] = reason


def transition_record(
    workspace: Workspace,
    record: Record,
    *,
    new_status: str,
    command: str,
    reason: str,
    actor: str = "human",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _require_valid_status(record.kind, new_status)

    before = {"status": record.front_matter.get("status")}
    record.front_matter["status"] = new_status
    _apply_close_metadata(record, new_status=new_status, reason=reason, actor=actor)

    merged_extra = dict(extra or {})
    if new_status == "fulfilled":
        merged_extra.setdefault("outcome_summary", reason)
    if new_status == "superseded":
        superseded_by = merged_extra.get("superseded_by")
        if not isinstance(superseded_by, str) or not superseded_by.strip():
            raise PlanledgerError(
                "invalid_transition",
                f"{record.kind} {record.record_id} requires superseded_by for status {new_status}.",
            )

    for key, value in merged_extra.items():
        record.front_matter[key] = value

    update_record_timestamp(record)
    save_record(record)

    after: dict[str, Any] = {"status": new_status}
    if reason.strip():
        after["reason"] = reason
    for field_name in ("closed_at", "closed_by", "close_reason"):
        if field_name in record.front_matter:
            after[field_name] = record.front_matter[field_name]
    for key, value in merged_extra.items():
        after[key] = value

    return append_event(
        workspace,
        command=command,
        object_type=record.kind,
        object_id=record.record_id,
        event_type="status_changed",
        before=before,
        after=after,
        actor=actor,
    )


def link_records(
    workspace: Workspace,
    source: Record,
    relation: str,
    target_id: str,
    *,
    command: str,
) -> dict[str, Any]:
    current = source.front_matter.get(relation)
    if relation in MULTI_RELATION_FIELDS or isinstance(current, list) or current is None:
        values = [str(item) for item in current or []]
        if target_id not in values:
            values.append(target_id)
        source.front_matter[relation] = values
    else:
        source.front_matter[relation] = target_id

    update_record_timestamp(source)
    save_record(source)

    return append_event(
        workspace,
        command=command,
        object_type=source.kind,
        object_id=source.record_id,
        event_type="linked",
        after={"relation": relation, "target_id": target_id},
    )
