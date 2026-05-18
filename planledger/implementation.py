from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from planledger.errors import PlanledgerError
from planledger.language import add_language_term
from planledger.lifecycle import link_records, transition_record
from planledger.models import Workspace
from planledger.storage import (
    RATIONALE_TEMPLATE,
    allocate_id,
    create_record,
    is_rationale_decision,
    list_records,
    load_record,
    now_iso,
)
from planledger.taskledger import reconcile

try:
    import json
except ModuleNotFoundError:  # pragma: no cover
    json = None  # type: ignore[assignment]

IMPLEMENTATION_REPORT_SCHEMA = "planledger.implementation_report.v1"


@dataclass
class ImplementationValidationDetails:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    drift: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class ImplementationApplyResult:
    updated: list[dict[str, Any]] = field(default_factory=list)
    created: list[dict[str, Any]] = field(default_factory=list)
    reused: list[dict[str, Any]] = field(default_factory=list)
    drift: list[dict[str, Any]] = field(default_factory=list)


def load_implementation_report(path: Path) -> dict[str, Any]:
    if json is None:  # pragma: no cover
        raise PlanledgerError("internal_error", "JSON support unavailable.")
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanledgerError(
            "invalid_bundle",
            f"Implementation report is not valid JSON: {exc}",
            remediation=[f"Inspect: {path}"],
        ) from exc
    if not isinstance(data, dict):
        raise PlanledgerError(
            "invalid_bundle", "Implementation report must be a JSON object."
        )
    return data


def validate_implementation_report(
    report: dict[str, Any],
    *,
    workspace: Workspace | None = None,
) -> ImplementationValidationDetails:
    details = ImplementationValidationDetails()
    schema = report.get("schema")
    if schema != IMPLEMENTATION_REPORT_SCHEMA:
        details.errors.append(
            "Missing or invalid schema: expected "
            f"{IMPLEMENTATION_REPORT_SCHEMA!r}, got {schema!r}."
        )

    for field_name in ("slice_updates", "goal_updates", "language_terms", "rationales"):
        value = report.get(field_name, [])
        if not isinstance(value, list):
            details.errors.append(f"{field_name} must be a list.")
            continue
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                details.errors.append(f"{field_name}[{index}] must be an object.")
                continue
            if field_name == "slice_updates":
                if not isinstance(item.get("id"), str) or not str(item["id"]).strip():
                    details.errors.append(f"{field_name}[{index}] missing id.")
                if str(item.get("action", "")) not in {"validate", "cancel", "obsolete"}:
                    details.errors.append(
                        f"{field_name}[{index}] has invalid action {item.get('action')!r}."
                    )
                evidence = item.get("evidence")
                if not isinstance(evidence, str) or not evidence.strip():
                    details.errors.append(
                        f"{field_name}[{index}] requires non-empty evidence."
                    )
            elif field_name == "goal_updates":
                if not isinstance(item.get("id"), str) or not str(item["id"]).strip():
                    details.errors.append(f"{field_name}[{index}] missing id.")
                if str(item.get("action", "")) not in {"complete", "cancel", "supersede"}:
                    details.errors.append(
                        f"{field_name}[{index}] has invalid action {item.get('action')!r}."
                    )
                evidence = item.get("evidence")
                if not isinstance(evidence, str) or not evidence.strip():
                    details.errors.append(
                        f"{field_name}[{index}] requires non-empty evidence."
                    )
                if str(item.get("action", "")) in {"cancel", "supersede"}:
                    reason = item.get("reason")
                    if not isinstance(reason, str) or not reason.strip():
                        details.errors.append(
                            f"{field_name}[{index}] requires non-empty reason."
                        )
            elif field_name == "language_terms":
                if not isinstance(item.get("canonical"), str) or not str(
                    item.get("canonical")
                ).strip():
                    details.errors.append(f"{field_name}[{index}] missing canonical.")
                definition = item.get("definition")
                if not isinstance(definition, str) or not definition.strip():
                    details.errors.append(f"{field_name}[{index}] missing definition.")
                evidence = item.get("evidence")
                if evidence is not None and (
                    not isinstance(evidence, list) or not all(isinstance(v, dict) for v in evidence)
                ):
                    details.errors.append(
                        f"{field_name}[{index}] evidence must be a list of objects when present."
                    )
            elif field_name == "rationales":
                if not isinstance(item.get("title"), str) or not str(item.get("title")).strip():
                    details.errors.append(f"{field_name}[{index}] missing title.")
                evidence = item.get("evidence")
                if not isinstance(evidence, str) or not evidence.strip():
                    details.errors.append(
                        f"{field_name}[{index}] requires non-empty evidence."
                    )
                summary = item.get("summary")
                if not isinstance(summary, str) or not summary.strip():
                    details.errors.append(f"{field_name}[{index}] missing summary.")

    if workspace is not None and report.get("ignore_taskledger_drift") is not True:
        drift = reconcile(workspace).get("drift", [])
        if isinstance(drift, list) and drift:
            details.drift = drift
            details.errors.append("Unresolved taskledger drift blocks implementation closeout.")
    return details


def _apply_slice_update(
    workspace: Workspace,
    result: ImplementationApplyResult,
    update: dict[str, Any],
) -> None:
    record = load_record(workspace, "slice", str(update["id"]))
    action = str(update["action"])
    evidence = str(update["evidence"])
    target_status = {"validate": "validated", "cancel": "cancelled", "obsolete": "obsolete"}[
        action
    ]
    if str(record.front_matter.get("status", "")) == target_status:
        result.reused.append({"kind": "slice", "id": record.record_id, "action": action})
        return
    reason = evidence if action == "validate" else str(update.get("reason") or evidence)
    extra = (
        {"validation_evidence": [evidence]}
        if action == "validate"
        else {"close_evidence": [evidence]}
    )
    transition_record(
        workspace,
        record,
        new_status=target_status,
        command="planledger implementation report apply",
        reason=reason,
        extra=extra,
    )
    result.updated.append({"kind": "slice", "id": record.record_id, "action": action})


def _apply_goal_update(
    workspace: Workspace,
    result: ImplementationApplyResult,
    update: dict[str, Any],
) -> None:
    record = load_record(workspace, "goal", str(update["id"]))
    action = str(update["action"])
    evidence = str(update["evidence"])
    mapping = {
        "complete": "fulfilled",
        "cancel": "cancelled",
        "supersede": "superseded",
    }
    target_status = mapping[action]
    if str(record.front_matter.get("status", "")) == target_status:
        result.reused.append({"kind": "goal", "id": record.record_id, "action": action})
        return
    extra: dict[str, Any] = {"evidence": [evidence]}
    if action == "supersede":
        superseded_by = str(update.get("superseded_by") or "").strip()
        if not superseded_by:
            raise PlanledgerError(
                "invalid_bundle",
                f"Goal update for {record.record_id} requires superseded_by.",
            )
        extra["superseded_by"] = superseded_by
    reason = str(update.get("reason") or evidence)
    transition_record(
        workspace,
        record,
        new_status=target_status,
        command="planledger implementation report apply",
        reason=reason,
        extra=extra,
    )
    related_goal = update.get("related_goal")
    if isinstance(related_goal, str) and related_goal.strip():
        link_records(
            workspace,
            record,
            "related_goals",
            related_goal,
            command="planledger implementation report apply",
        )
    result.updated.append({"kind": "goal", "id": record.record_id, "action": action})


def _apply_language_terms(
    workspace: Workspace,
    result: ImplementationApplyResult,
    terms: list[dict[str, Any]],
) -> None:
    for term_data in terms:
        record, created = add_language_term(
            workspace,
            canonical=str(term_data.get("canonical", "")),
            area=term_data.get("area"),
            definition=str(term_data.get("definition", "")),
            avoid=list(term_data.get("avoid", []) or []),
            aliases=list(term_data.get("aliases", []) or []),
            provenance=str(term_data.get("provenance", "agent-generated")),
            confidence=str(term_data.get("confidence", "high")),
            evidence=list(term_data.get("evidence", []) or []),
            status=str(term_data.get("status", "active")),
        )
        target = result.created if created else result.reused
        target.append({"kind": "language_term", "id": record.record_id})


def _apply_rationales(
    workspace: Workspace,
    result: ImplementationApplyResult,
    rationales: list[dict[str, Any]],
) -> None:
    for rationale_data in rationales:
        title = str(rationale_data.get("title", "")).strip()
        initiative = rationale_data.get("initiative")
        existing = next(
            (
                record
                for record in list_records(workspace, "decision")
                if is_rationale_decision(record)
                and str(record.front_matter.get("title", "")).strip() == title
                and record.front_matter.get("initiative") == initiative
            ),
            None,
        )
        if existing is not None:
            result.reused.append({"kind": "decision", "id": existing.record_id})
            continue
        decision_id = allocate_id(workspace, "decision")
        timestamp = now_iso()
        front = {
            "id": decision_id,
            "type": "decision",
            "decision_type": "rationale",
            "initiative": initiative,
            "area": rationale_data.get("area"),
            "title": title,
            "status": str(rationale_data.get("status", "open")),
            "chosen_option": None,
            "rationale_gate": rationale_data.get("rationale_gate")
            or {
                "hard_to_reverse": True,
                "surprising_without_context": True,
                "real_tradeoff": True,
            },
            "evidence": [str(rationale_data.get("evidence", "")).strip()],
            "created_at": timestamp,
            "updated_at": timestamp,
            "accepted_at": None,
            "provenance": str(rationale_data.get("provenance", "agent-generated")),
        }
        body = (
            f"# Rationale\n\n{str(rationale_data.get('summary', '')).strip()}\n\n## Evidence\n"
        )
        create_record(workspace, "decision", front, body or RATIONALE_TEMPLATE)
        result.created.append({"kind": "decision", "id": decision_id})


def apply_implementation_report(
    workspace: Workspace,
    report: dict[str, Any],
    *,
    dry_run: bool = False,
) -> ImplementationApplyResult:
    details = validate_implementation_report(report, workspace=workspace)
    if details.errors:
        raise PlanledgerError(
            "invalid_bundle",
            "Implementation report validation failed.",
            remediation=details.errors,
        )
    result = ImplementationApplyResult(drift=details.drift)
    if dry_run:
        result.updated.extend(
            {"kind": "slice", "id": item.get("id"), "action": item.get("action")}
            for item in report.get("slice_updates", [])
            if isinstance(item, dict)
        )
        result.updated.extend(
            {"kind": "goal", "id": item.get("id"), "action": item.get("action")}
            for item in report.get("goal_updates", [])
            if isinstance(item, dict)
        )
        result.created.extend(
            {"kind": "language_term", "canonical": item.get("canonical")}
            for item in report.get("language_terms", [])
            if isinstance(item, dict)
        )
        result.created.extend(
            {"kind": "decision", "title": item.get("title")}
            for item in report.get("rationales", [])
            if isinstance(item, dict)
        )
        return result

    for update in report.get("slice_updates", []):
        if isinstance(update, dict):
            _apply_slice_update(workspace, result, update)
    for update in report.get("goal_updates", []):
        if isinstance(update, dict):
            _apply_goal_update(workspace, result, update)
    _apply_language_terms(
        workspace, result, [item for item in report.get("language_terms", []) if isinstance(item, dict)]
    )
    _apply_rationales(
        workspace, result, [item for item in report.get("rationales", []) if isinstance(item, dict)]
    )
    return result
