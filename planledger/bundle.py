from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from planledger.errors import PlanledgerError
from planledger.lifecycle import link_records, transition_record
from planledger.models import Workspace
from planledger.storage import (
    allocate_id,
    append_event,
    create_record,
    list_records,
    load_record,
    now_iso,
    save_record,
)


def load_bundle(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanledgerError(
            "invalid_bundle",
            f"Bundle is not valid JSON: {exc}",
            remediation=[f"Inspect: {path}"],
        ) from exc
    if not isinstance(data, dict):
        raise PlanledgerError(
            "invalid_bundle",
            "Bundle must be a JSON object.",
            remediation=[f"Inspect: {path}"],
        )
    return data


ALLOWED_TOP_LEVEL_FIELDS = {
    "schema",
    "request",
    "goal",
    "initiative",
    "plan",
    "milestones",
    "decisions",
    "risks",
}
ALLOWED_DECISION_STATUSES = {"open", "accepted", "rejected"}
ALLOWED_OPTION_STATUSES = {"candidate", "accepted", "rejected"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high"}
EVOLUTION_SCHEMA = "planledger.evolution_bundle.v1"
_PREVIEW_NEW_GOAL_SCOPE = "__preview_new_goal__"


@dataclass
class BundleValidationDetails:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class BundleSliceModel:
    key: str | None
    title: str
    objective: str | None
    target_files: list[str]
    implementation_steps: list[str]
    acceptance_criteria: list[str]
    validation_commands: list[str]
    ready_for_taskledger: bool


@dataclass
class BundleMilestoneModel:
    title: str
    slices: list[BundleSliceModel]


@dataclass
class BundleOptionModel:
    title: str
    status: str


@dataclass
class BundleDecisionModel:
    title: str
    status: str
    decision_type: str | None
    rationale: str | None
    options: list[BundleOptionModel]


@dataclass
class BundleRiskModel:
    title: str
    impact: str
    likelihood: str
    mitigation: str


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _string_list(value: Any, *, field_name: str, errors: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        errors.append(f"'{field_name}' must be a list of strings.")
        return []
    cleaned: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            errors.append(f"'{field_name}[{idx}]' must be a string.")
            continue
        cleaned.append(item)
    return cleaned


def _validate_top_level_fields(
    bundle: dict[str, Any],
    details: BundleValidationDetails,
    *,
    strict_unknown_fields: bool,
) -> None:
    unknown = sorted(set(bundle) - ALLOWED_TOP_LEVEL_FIELDS)
    if not unknown:
        return
    for field in unknown:
        message = f"Unknown top-level field: {field!r}."
        if strict_unknown_fields:
            details.errors.append(message)
        else:
            details.warnings.append(message)


def validate_bundle_details(
    bundle: dict[str, Any],
    *,
    strict_unknown_fields: bool = False,
) -> BundleValidationDetails:
    details = BundleValidationDetails()
    _validate_top_level_fields(
        bundle,
        details,
        strict_unknown_fields=strict_unknown_fields,
    )

    schema = bundle.get("schema")
    if schema != "planledger.plan_bundle.v1":
        details.errors.append(
            "Missing or invalid schema: expected "
            f"'planledger.plan_bundle.v1', got {schema!r}."
        )

    request_data = bundle.get("request")
    if not isinstance(request_data, dict):
        details.errors.append("Missing or invalid 'request' section.")
    elif not _is_non_empty_string(request_data.get("title")):
        details.errors.append("request.title is required.")

    plan_data = bundle.get("plan")
    if not isinstance(plan_data, dict):
        details.errors.append("Missing or invalid 'plan' section.")
    else:
        if not _is_non_empty_string(plan_data.get("title")):
            details.errors.append("Plan title is required.")
        objectives = _string_list(
            plan_data.get("objectives"),
            field_name="plan.objectives",
            errors=details.errors,
        )
        if not objectives:
            details.errors.append("Plan objectives are required.")

    seen_slice_keys: set[str] = set()
    milestones = bundle.get("milestones")
    if milestones is not None:
        if not isinstance(milestones, list):
            details.errors.append("'milestones' must be a list.")
        else:
            for i, ms in enumerate(milestones):
                if not isinstance(ms, dict):
                    details.errors.append(f"Milestone {i} must be an object.")
                    continue
                if not _is_non_empty_string(ms.get("title")):
                    details.errors.append(f"Milestone {i} missing title.")
                slices = ms.get("slices", [])
                if not isinstance(slices, list):
                    details.errors.append(f"Milestone {i} 'slices' must be a list.")
                    continue
                for j, sl in enumerate(slices):
                    if not isinstance(sl, dict):
                        details.errors.append(f"Milestone {i} slice {j} must be an object.")
                        continue
                    if not _is_non_empty_string(sl.get("title")):
                        details.errors.append(f"Milestone {i} slice {j} missing title.")
                    key = sl.get("key")
                    if key is not None:
                        if not _is_non_empty_string(key):
                            details.errors.append(
                                f"Milestone {i} slice {j} key must be a non-empty string."
                            )
                        elif key in seen_slice_keys:
                            details.errors.append(f"Duplicate slice key detected: {key!r}.")
                        else:
                            seen_slice_keys.add(key)
                    if sl.get("ready_for_taskledger") is True:
                        required_lists = (
                            ("target_files", sl.get("target_files")),
                            ("implementation_steps", sl.get("implementation_steps")),
                            ("acceptance_criteria", sl.get("acceptance_criteria")),
                            ("validation_commands", sl.get("validation_commands")),
                        )
                        if not _is_non_empty_string(sl.get("objective")):
                            details.errors.append(
                                f"Milestone {i} slice {j} requires objective when ready_for_taskledger=true."
                            )
                        for field_name, value in required_lists:
                            values = _string_list(
                                value,
                                field_name=f"milestones[{i}].slices[{j}].{field_name}",
                                errors=details.errors,
                            )
                            if not values:
                                details.errors.append(
                                    f"Milestone {i} slice {j} requires non-empty {field_name} when ready_for_taskledger=true."
                                )
                    _ = BundleSliceModel(
                        key=key if isinstance(key, str) else None,
                        title=str(sl.get("title", "")),
                        objective=str(sl.get("objective"))
                        if sl.get("objective") is not None
                        else None,
                        target_files=_string_list(
                            sl.get("target_files"),
                            field_name=f"milestones[{i}].slices[{j}].target_files",
                            errors=details.errors,
                        ),
                        implementation_steps=_string_list(
                            sl.get("implementation_steps"),
                            field_name=(
                                f"milestones[{i}].slices[{j}].implementation_steps"
                            ),
                            errors=details.errors,
                        ),
                        acceptance_criteria=_string_list(
                            sl.get("acceptance_criteria"),
                            field_name=(
                                f"milestones[{i}].slices[{j}].acceptance_criteria"
                            ),
                            errors=details.errors,
                        ),
                        validation_commands=_string_list(
                            sl.get("validation_commands"),
                            field_name=(
                                f"milestones[{i}].slices[{j}].validation_commands"
                            ),
                            errors=details.errors,
                        ),
                        ready_for_taskledger=sl.get("ready_for_taskledger") is True,
                    )
                _ = BundleMilestoneModel(
                    title=str(ms.get("title", "")),
                    slices=[],
                )

    decisions = bundle.get("decisions")
    if decisions is not None:
        if not isinstance(decisions, list):
            details.errors.append("'decisions' must be a list.")
        else:
            for i, decision in enumerate(decisions):
                if not isinstance(decision, dict):
                    details.errors.append(f"Decision {i} must be an object.")
                    continue
                if not _is_non_empty_string(decision.get("title")):
                    details.errors.append(f"Decision {i} missing title.")
                status = str(decision.get("status", "open"))
                if status not in ALLOWED_DECISION_STATUSES:
                    details.errors.append(
                        f"Decision {i} has invalid status {status!r}. "
                        f"Allowed: {sorted(ALLOWED_DECISION_STATUSES)}."
                    )
                options = decision.get("options", [])
                if options is None:
                    options = []
                if not isinstance(options, list):
                    details.errors.append(f"Decision {i} options must be a list.")
                    continue
                accepted_options = 0
                parsed_options: list[BundleOptionModel] = []
                for j, option in enumerate(options):
                    if not isinstance(option, dict):
                        details.errors.append(f"Decision {i} option {j} must be an object.")
                        continue
                    option_title = option.get("title")
                    option_status = str(option.get("status", "candidate"))
                    if option_status not in ALLOWED_OPTION_STATUSES:
                        details.errors.append(
                            f"Decision {i} option {j} has invalid status {option_status!r}. "
                            f"Allowed: {sorted(ALLOWED_OPTION_STATUSES)}."
                        )
                    if option_status in {"accepted", "rejected"} and not _is_non_empty_string(
                        option_title
                    ):
                        details.errors.append(
                            f"Decision {i} option {j} requires title for status {option_status!r}."
                        )
                    if option_status == "accepted":
                        accepted_options += 1
                    parsed_options.append(
                        BundleOptionModel(
                            title=str(option_title or ""),
                            status=option_status,
                        )
                    )
                if status == "accepted" and accepted_options != 1:
                    details.errors.append(
                        f"Decision {i} is accepted but has {accepted_options} accepted options; exactly one is required."
                    )
                _ = BundleDecisionModel(
                    title=str(decision.get("title", "")),
                    status=status,
                    decision_type=str(decision.get("decision_type"))
                    if decision.get("decision_type") is not None
                    else None,
                    rationale=str(decision.get("rationale"))
                    if decision.get("rationale") is not None
                    else None,
                    options=parsed_options,
                )

    risks = bundle.get("risks")
    if risks is not None:
        if not isinstance(risks, list):
            details.errors.append("'risks' must be a list.")
        else:
            for i, risk in enumerate(risks):
                if not isinstance(risk, dict):
                    details.errors.append(f"Risk {i} must be an object.")
                    continue
                if not _is_non_empty_string(risk.get("title")):
                    details.errors.append(f"Risk {i} missing title.")
                impact = str(risk.get("impact", "medium"))
                likelihood = str(risk.get("likelihood", "medium"))
                if impact not in ALLOWED_RISK_LEVELS:
                    details.errors.append(
                        f"Risk {i} has invalid impact {impact!r}. "
                        f"Allowed: {sorted(ALLOWED_RISK_LEVELS)}."
                    )
                if likelihood not in ALLOWED_RISK_LEVELS:
                    details.errors.append(
                        f"Risk {i} has invalid likelihood {likelihood!r}. "
                        f"Allowed: {sorted(ALLOWED_RISK_LEVELS)}."
                    )
                if impact == "high" and not _is_non_empty_string(risk.get("mitigation")):
                    details.errors.append(
                        f"Risk {i} with high impact requires a mitigation."
                    )
                _ = BundleRiskModel(
                    title=str(risk.get("title", "")),
                    impact=impact,
                    likelihood=likelihood,
                    mitigation=str(risk.get("mitigation", "")),
                )

    return details


def validate_bundle(
    bundle: dict[str, Any],
    *,
    strict_unknown_fields: bool = False,
) -> list[str]:
    return validate_bundle_details(
        bundle,
        strict_unknown_fields=strict_unknown_fields,
    ).errors


def _find_existing_by_key(
    workspace: Workspace,
    kind: str,
    initiative_id: str,
    external_key: str,
) -> str | None:
    for record in list_records(workspace, kind):
        if (
            record.front_matter.get("initiative") == initiative_id
            and record.front_matter.get("external_key") == external_key
        ):
            return record.record_id
    return None


def _find_existing_by_title(
    workspace: Workspace,
    kind: str,
    title: str,
    *,
    goal_id: str | None = None,
    initiative_id: str | None = None,
) -> str | None:
    for record in list_records(workspace, kind):
        if record.front_matter.get("title") != title:
            continue
        if goal_id is not None and record.front_matter.get("goal") != goal_id:
            continue
        if initiative_id is not None and (
            record.front_matter.get("initiative") != initiative_id
        ):
            continue
        return record.record_id
    return None


@dataclass
class BundleApplyResult:
    created: list[dict[str, Any]] = field(default_factory=list)
    reused: list[dict[str, Any]] = field(default_factory=list)
    updated: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    plan_id: str | None = None


@dataclass
class _ApplyCtx:
    workspace: Workspace
    run_id: str = ""
    timestamp: str = ""
    actor: str = "agent"
    provenance: str = "agent-generated"
    source_context: list[dict[str, str]] = field(default_factory=list)
    result: BundleApplyResult = field(default_factory=BundleApplyResult)


def _validate_or_raise(bundle: dict[str, Any]) -> None:
    details = validate_bundle_details(bundle)
    if details.errors:
        raise PlanledgerError(
            "invalid_bundle",
            "Bundle validation failed.",
            remediation=details.errors,
        )


def _resolve_goal(
    ctx: _ApplyCtx,
    goal_data: dict[str, Any],
) -> str | None:
    title = goal_data.get("title", "")
    existing = _find_existing_by_title(ctx.workspace, "goal", title)
    if existing and goal_data.get("reuse") == "active-or-create":
        ctx.result.reused.append({"kind": "goal", "id": existing})
        return existing
    goal_id = allocate_id(ctx.workspace, "goal")
    goal_front = {
        "id": goal_id,
        "type": "goal",
        "title": title,
        "status": "active",
        "horizon": "quarter",
        "priority": "high",
        "success_metrics": [],
        "source_run": ctx.run_id,
        "provenance": ctx.provenance,
        "created_at": ctx.timestamp,
        "updated_at": ctx.timestamp,
    }
    create_record(ctx.workspace, "goal", goal_front, "")
    ctx.result.created.append({"kind": "goal", "id": goal_id})
    return goal_id


def _resolve_initiative(
    ctx: _ApplyCtx,
    init_data: dict[str, Any],
    goal_id: str | None,
) -> str | None:
    title = init_data.get("title", "")
    existing = _find_existing_by_title(
        ctx.workspace,
        "initiative",
        title,
        goal_id=goal_id,
    )
    if existing and init_data.get("reuse") == "active-or-create":
        ctx.result.reused.append({"kind": "initiative", "id": existing})
        return existing
    init_id = allocate_id(ctx.workspace, "initiative")
    init_front = {
        "id": init_id,
        "type": "initiative",
        "goal": goal_id,
        "title": title,
        "status": "shaping",
        "owner": ctx.actor,
        "priority": "high",
        "active": False,
        "source_run": ctx.run_id,
        "provenance": ctx.provenance,
        "created_at": ctx.timestamp,
        "updated_at": ctx.timestamp,
    }
    create_record(ctx.workspace, "initiative", init_front, "")
    ctx.result.created.append({"kind": "initiative", "id": init_id})
    return init_id


def _create_plan(
    ctx: _ApplyCtx,
    plan_data: dict[str, Any],
    goal_id: str | None,
    init_id: str | None,
) -> None:
    if not plan_data or not init_id:
        return
    plan_id = allocate_id(ctx.workspace, "plan")
    body_parts = [
        f"# Plan: {plan_data.get('title', '')}",
        "",
        "## Context",
        "",
    ]
    for ctx_line in plan_data.get("context", []):
        body_parts.append(f"- {ctx_line}")
    body_parts.extend(["", "## Objectives", ""])
    for obj in plan_data.get("objectives", []):
        body_parts.append(f"- {obj}")
    body_parts.append("")
    if plan_data.get("non_goals"):
        body_parts.extend(["## Non-goals", ""])
        for ng in plan_data["non_goals"]:
            body_parts.append(f"- {ng}")
        body_parts.append("")
    plan_body = "\n".join(body_parts)
    plan_front = {
        "id": plan_id,
        "type": "plan",
        "goal": goal_id,
        "initiative": init_id,
        "version": 1,
        "status": "draft",
        "supersedes": None,
        "accepted_at": None,
        "accepted_by": None,
        "source_run": ctx.run_id,
        "provenance": ctx.provenance,
        "created_at": ctx.timestamp,
        "updated_at": ctx.timestamp,
    }
    create_record(ctx.workspace, "plan", plan_front, plan_body)
    ctx.result.created.append({"kind": "plan", "id": plan_id})
    ctx.result.plan_id = plan_id


def _create_milestones_and_slices(
    ctx: _ApplyCtx,
    milestones_data: list[dict[str, Any]],
    init_id: str | None,
    plan_id: str | None,
) -> list[str]:
    created_ids: list[str] = []
    milestone_order = 10
    ws = ctx.workspace
    for ms_data in milestones_data:
        if not isinstance(ms_data, dict):
            continue
        ms_id = allocate_id(ws, "milestone")
        ms_front = {
            "id": ms_id,
            "type": "milestone",
            "initiative": init_id,
            "plan": plan_id,
            "title": ms_data.get("title", ""),
            "status": "planned",
            "order": milestone_order,
            "target": None,
            "exit_criteria": [],
            "source_run": ctx.run_id,
            "created_at": ctx.timestamp,
            "updated_at": ctx.timestamp,
        }
        create_record(ws, "milestone", ms_front, "")
        ctx.result.created.append({"kind": "milestone", "id": ms_id})
        created_ids.append(ms_id)
        milestone_order += 10
        for sl_data in ms_data.get("slices", []):
            sl_id = _create_slice(
                ctx,
                sl_data,
                init_id,
                plan_id,
                ms_id,
            )
            if sl_id:
                created_ids.append(sl_id)
    return created_ids


def _create_slice(
    ctx: _ApplyCtx,
    sl_data: dict[str, Any],
    init_id: str | None,
    plan_id: str | None,
    ms_id: str,
) -> str | None:
    if not isinstance(sl_data, dict):
        return None
    ws = ctx.workspace
    ext_key = sl_data.get("key")
    if ext_key and init_id:
        existing = _find_existing_by_key(ws, "slice", init_id, ext_key)
        if existing:
            ctx.result.reused.append({"kind": "slice", "id": existing})
            return None
    sl_id = allocate_id(ws, "slice")
    sl_front: dict[str, Any] = {
        "id": sl_id,
        "type": "slice",
        "initiative": init_id,
        "plan": plan_id,
        "milestone": ms_id,
        "title": sl_data.get("title", ""),
        "status": "shaping",
        "priority": "high",
        "size": "M",
        "risk": "medium",
        "depends_on": [],
        "blocked_by": [],
        "taskledger_bindings": [],
        "source_run": ctx.run_id,
        "provenance": ctx.provenance,
        "created_at": ctx.timestamp,
        "updated_at": ctx.timestamp,
    }
    if ext_key:
        sl_front["external_key"] = ext_key
    for fname in (
        "objective",
        "target_files",
        "implementation_steps",
        "acceptance_criteria",
        "validation_commands",
    ):
        if sl_data.get(fname):
            sl_front[fname] = sl_data[fname]
    if sl_data.get("ready_for_taskledger"):
        sl_front["ready_for_taskledger"] = True
        sl_front["status"] = "ready-for-execution"
    create_record(ws, "slice", sl_front, "")
    ctx.result.created.append({"kind": "slice", "id": sl_id})
    return sl_id


def _create_decisions_and_options(
    ctx: _ApplyCtx,
    decisions_data: list[dict[str, Any]],
    init_id: str | None,
    plan_id: str | None,
) -> list[str]:
    created_ids: list[str] = []
    ws = ctx.workspace
    for dec_data in decisions_data:
        if not isinstance(dec_data, dict):
            continue
        dec_id = allocate_id(ws, "decision")
        dec_front: dict[str, Any] = {
            "id": dec_id,
            "type": "decision",
            "initiative": init_id,
            "plan": plan_id,
            "title": dec_data.get("title", ""),
            "status": dec_data.get("status", "open"),
            "chosen_option": None,
            "decision_type": dec_data.get("decision_type"),
            "source_run": ctx.run_id,
            "provenance": ctx.provenance,
            "created_at": ctx.timestamp,
            "updated_at": ctx.timestamp,
            "accepted_at": None,
        }
        body = "# Decision\n\n## Context\n\n## Rationale\n\n"
        rationale = dec_data.get("rationale")
        if rationale:
            body += f"{rationale}\n"

        # Build option id map before writing decision
        option_ids_by_title: dict[str, str] = {}
        for opt_data in dec_data.get("options", []):
            if not isinstance(opt_data, dict):
                continue
            opt_id = allocate_id(ws, "option")
            opt_title = str(opt_data.get("title", ""))
            option_ids_by_title[opt_title] = opt_id
            opt_front = {
                "id": opt_id,
                "type": "option",
                "decision": dec_id,
                "title": opt_data.get("title", ""),
                "status": opt_data.get("status", "candidate"),
                "source_run": ctx.run_id,
                "created_at": ctx.timestamp,
                "updated_at": ctx.timestamp,
            }
            create_record(ws, "option", opt_front, "")
            ctx.result.created.append(
                {
                    "kind": "option",
                    "id": opt_id,
                    "title": opt_data.get("title", ""),
                }
            )
            created_ids.append(opt_id)

        # Set chosen_option and accepted_at if accepted
        if dec_data.get("status") == "accepted" and dec_data.get("options"):
            accepted = next(
                (
                    o
                    for o in dec_data["options"]
                    if isinstance(o, dict) and o.get("status") == "accepted"
                ),
                None,
            )
            if accepted:
                dec_front["chosen_option"] = option_ids_by_title.get(
                    str(accepted.get("title", ""))
                )
                dec_front["accepted_at"] = ctx.timestamp

        create_record(ws, "decision", dec_front, body)
        ctx.result.created.append({"kind": "decision", "id": dec_id})
        created_ids.append(dec_id)
    return created_ids


def _create_risks(
    ctx: _ApplyCtx,
    risks_data: list[dict[str, Any]],
    init_id: str | None,
) -> list[str]:
    created_ids: list[str] = []
    ws = ctx.workspace
    for risk_data in risks_data:
        if not isinstance(risk_data, dict):
            continue
        risk_id = allocate_id(ws, "risk")
        risk_front = {
            "id": risk_id,
            "type": "risk",
            "initiative": init_id,
            "title": risk_data.get("title", ""),
            "status": "open",
            "likelihood": risk_data.get("likelihood", "medium"),
            "impact": risk_data.get("impact", "medium"),
            "mitigation": risk_data.get("mitigation", ""),
            "source_run": ctx.run_id,
            "provenance": ctx.provenance,
            "created_at": ctx.timestamp,
            "updated_at": ctx.timestamp,
        }
        create_record(ws, "risk", risk_front, "")
        ctx.result.created.append({"kind": "risk", "id": risk_id})
        created_ids.append(risk_id)
    return created_ids


def apply_bundle(
    workspace: Workspace,
    bundle: dict[str, Any],
    *,
    dry_run: bool = False,
    actor: str = "agent",
    provenance: str = "agent-generated",
    evidence: list[dict[str, str]] | None = None,
) -> BundleApplyResult:
    _validate_or_raise(bundle)
    if dry_run:
        return _preview_bundle(
            workspace,
            bundle,
            actor=actor,
            provenance=provenance,
        )
    ctx = _ApplyCtx(
        workspace=workspace,
        timestamp=now_iso(),
        actor=actor,
        provenance=provenance,
        source_context=evidence or [],
    )
    run_front: dict[str, Any] = {
        "id": "",
        "type": "run",
        "actor": actor,
        "harness": None,
        "skill_version": None,
        "user_request": bundle.get("request", {}).get("title", ""),
        "planning_mode": (bundle.get("request", {}).get("planning_mode", "full")),
        "provenance": provenance,
        "source_context": ctx.source_context,
        "created_records": [],
        "created_at": ctx.timestamp,
        "updated_at": ctx.timestamp,
    }
    ctx.run_id = allocate_id(workspace, "run")
    run_front["id"] = ctx.run_id
    create_record(workspace, "run", run_front, "")
    ctx.result.created.append({"kind": "run", "id": ctx.run_id})

    goal_id = _resolve_goal(ctx, bundle.get("goal", {}))
    init_id = _resolve_initiative(ctx, bundle.get("initiative", {}), goal_id)
    _create_plan(ctx, bundle.get("plan", {}), goal_id, init_id)
    plan_id = ctx.result.plan_id
    ms_ids = _create_milestones_and_slices(
        ctx,
        bundle.get("milestones", []),
        init_id,
        plan_id,
    )
    dec_ids = _create_decisions_and_options(
        ctx,
        bundle.get("decisions", []),
        init_id,
        plan_id,
    )
    risk_ids = _create_risks(ctx, bundle.get("risks", []), init_id)
    all_created = [r["id"] for r in ctx.result.created] + ms_ids + dec_ids + risk_ids
    if all_created:
        run_record = load_record(workspace, "run", ctx.run_id)
        run_record.front_matter["created_records"] = all_created
        run_record.front_matter["source_context"] = ctx.source_context
        save_record(run_record)

    evt = append_event(
        workspace,
        command="planledger bundle apply",
        object_type="run",
        object_id=ctx.run_id,
        event_type="bundle_applied",
        after={
            "created": len(ctx.result.created),
            "reused": len(ctx.result.reused),
        },
        actor=actor,
        source_run=ctx.run_id,
        provenance=ctx.provenance,
        correlation_id=ctx.run_id,
    )
    ctx.result.events.append(evt)
    return ctx.result


def _preview_bundle(
    workspace: Workspace,
    bundle: dict[str, Any],
    *,
    actor: str = "agent",
    provenance: str = "agent-generated",
) -> BundleApplyResult:
    """Compute what apply_bundle would create without writing anything."""
    result = BundleApplyResult()

    goal_scope: str | None = None
    # Simulate goal
    goal_data = bundle.get("goal", {})
    if goal_data:
        title = goal_data.get("title", "")
        existing = _find_existing_by_title(workspace, "goal", title)
        if existing and goal_data.get("reuse") == "active-or-create":
            goal_scope = existing
            result.reused.append(
                {
                    "kind": "goal",
                    "id": existing,
                    "title": title,
                }
            )
        else:
            result.created.append(
                {
                    "kind": "goal",
                    "id": "goal-preview",
                    "title": title,
                }
            )
            goal_scope = _PREVIEW_NEW_GOAL_SCOPE

    # Simulate initiative
    init_data = bundle.get("initiative", {})
    if init_data:
        title = init_data.get("title", "")
        existing = _find_existing_by_title(
            workspace,
            "initiative",
            title,
            goal_id=goal_scope,
        )
        if existing and init_data.get("reuse") == "active-or-create":
            result.reused.append(
                {
                    "kind": "initiative",
                    "id": existing,
                    "title": title,
                }
            )
        else:
            result.created.append(
                {
                    "kind": "initiative",
                    "id": "init-preview",
                    "title": title,
                }
            )

    # Simulate plan
    plan_data = bundle.get("plan", {})
    if plan_data:
        result.created.append(
            {
                "kind": "plan",
                "title": plan_data.get("title", ""),
            }
        )
        result.plan_id = "plan-preview"

    # Simulate milestones and slices
    for ms_data in bundle.get("milestones", []):
        if not isinstance(ms_data, dict):
            continue
        result.created.append(
            {
                "kind": "milestone",
                "title": ms_data.get("title", ""),
            }
        )
        for sl_data in ms_data.get("slices", []):
            if not isinstance(sl_data, dict):
                continue
            result.created.append(
                {
                    "kind": "slice",
                    "title": sl_data.get("title", ""),
                }
            )

    # Simulate decisions and options
    for dec_data in bundle.get("decisions", []):
        if not isinstance(dec_data, dict):
            continue
        result.created.append(
            {
                "kind": "decision",
                "title": dec_data.get("title", ""),
            }
        )
        for opt_data in dec_data.get("options", []):
            if not isinstance(opt_data, dict):
                continue
            result.created.append(
                {
                    "kind": "option",
                    "title": opt_data.get("title", ""),
                }
            )

    # Simulate risks
    for risk_data in bundle.get("risks", []):
        if not isinstance(risk_data, dict):
            continue
        result.created.append(
            {
                "kind": "risk",
                "title": risk_data.get("title", ""),
            }
        )

    # Simulate run
    result.created.insert(0, {"kind": "run", "title": "preview"})

    return result


def validate_evolution_details(bundle: dict[str, Any]) -> BundleValidationDetails:
    details = BundleValidationDetails()
    schema = bundle.get("schema")
    if schema != EVOLUTION_SCHEMA:
        details.errors.append(
            f"Missing or invalid schema: expected {EVOLUTION_SCHEMA!r}, got {schema!r}."
        )
    request_data = bundle.get("request")
    if not isinstance(request_data, dict):
        details.errors.append("Missing or invalid 'request' section.")
    elif not _is_non_empty_string(request_data.get("title")):
        details.errors.append("request.title is required.")

    allowed_actions = {
        "goal": {"complete", "cancel", "park"},
        "initiative": {"complete", "cancel", "park"},
        "plan": {"retire"},
        "slice": {"cancel", "obsolete", "validate"},
    }
    updates = bundle.get("updates", [])
    if not isinstance(updates, list):
        details.errors.append("'updates' must be a list.")
    else:
        for index, update in enumerate(updates):
            if not isinstance(update, dict):
                details.errors.append(f"Update {index} must be an object.")
                continue
            kind = str(update.get("kind", ""))
            action = str(update.get("action", ""))
            if kind not in allowed_actions:
                details.errors.append(f"Update {index} has invalid kind {kind!r}.")
                continue
            if not _is_non_empty_string(update.get("id")):
                details.errors.append(f"Update {index} missing id.")
            if action not in allowed_actions[kind]:
                details.errors.append(
                    f"Update {index} has invalid action {action!r} for {kind}."
                )
            if action == "validate":
                evidence = update.get("evidence")
                if not isinstance(evidence, list) or not evidence:
                    details.errors.append(
                        f"Update {index} requires non-empty evidence for validate."
                    )
            elif not _is_non_empty_string(update.get("reason")):
                details.errors.append(f"Update {index} requires reason.")

    creates = bundle.get("creates", {})
    if creates is not None and not isinstance(creates, dict):
        details.errors.append("'creates' must be an object when present.")
    elif isinstance(creates, dict):
        for field_name in ("questions", "assumptions", "constraints", "reviews"):
            value = creates.get(field_name, [])
            if value is not None and not isinstance(value, list):
                details.errors.append(f"creates.{field_name} must be a list.")

    if not updates and not any((bundle.get("creates") or {}).values()):
        details.errors.append("Evolution bundle must include updates or creates.")
    return details


def _find_scoped_existing(
    workspace: Workspace,
    kind: str,
    title: str,
    *,
    scope_kind: str,
    scope_id: str | None,
) -> str | None:
    for record in list_records(workspace, kind):
        if record.front_matter.get("title") != title:
            continue
        if record.front_matter.get("scope_kind") != scope_kind:
            continue
        if record.front_matter.get("scope_id") != scope_id:
            continue
        return record.record_id
    return None


def _preview_evolution_bundle(
    workspace: Workspace, bundle: dict[str, Any]
) -> BundleApplyResult:
    result = BundleApplyResult()
    for update in bundle.get("updates", []):
        if not isinstance(update, dict):
            continue
        result.updated.append(
            {
                "kind": update.get("kind"),
                "id": update.get("id"),
                "action": update.get("action"),
            }
        )
    creates = bundle.get("creates", {})
    if isinstance(creates, dict):
        for field_name, kind in (
            ("questions", "question"),
            ("assumptions", "assumption"),
            ("constraints", "constraint"),
            ("reviews", "review"),
        ):
            for item in creates.get(field_name, []):
                if not isinstance(item, dict):
                    continue
                existing = _find_scoped_existing(
                    workspace,
                    kind,
                    str(item.get("title", "")),
                    scope_kind=str(item.get("scope_kind", "project")),
                    scope_id=(
                        str(item.get("scope_id"))
                        if item.get("scope_id") is not None
                        else None
                    ),
                )
                if existing:
                    result.reused.append({"kind": kind, "id": existing})
                else:
                    result.created.append({"kind": kind, "title": item.get("title", "")})
    return result


def _apply_evolution_update(ctx: _ApplyCtx, update: dict[str, Any]) -> None:
    workspace = ctx.workspace
    kind = str(update["kind"])
    record_id = str(update["id"])
    action = str(update["action"])
    record = load_record(workspace, kind, record_id)
    reason = str(update.get("reason", ""))
    if kind == "goal":
        if action == "complete":
            transition_record(
                workspace,
                record,
                new_status="fulfilled",
                command="planledger evolution apply",
                reason=reason,
                extra={"evidence": list(update.get("evidence") or [])},
            )
        elif action == "cancel":
            transition_record(
                workspace,
                record,
                new_status="cancelled",
                command="planledger evolution apply",
                reason=reason,
            )
        else:
            transition_record(
                workspace,
                record,
                new_status="parked",
                command="planledger evolution apply",
                reason=reason,
                extra={"park_reason": reason},
            )
        for related_goal in update.get("related_goals", []) or []:
            if isinstance(related_goal, str):
                link_records(
                    workspace,
                    record,
                    "related_goals",
                    related_goal,
                    command="planledger evolution apply",
                )
    elif kind == "initiative":
        mapping = {"complete": "fulfilled", "cancel": "cancelled", "park": "parked"}
        extra = {"park_reason": reason} if action == "park" else None
        transition_record(
            workspace,
            record,
            new_status=mapping[action],
            command="planledger evolution apply",
            reason=reason,
            extra=extra,
        )
    elif kind == "plan":
        transition_record(
            workspace,
            record,
            new_status="retired",
            command="planledger evolution apply",
            reason=reason,
        )
    elif kind == "slice":
        if action == "validate":
            transition_record(
                workspace,
                record,
                new_status="validated",
                command="planledger evolution apply",
                reason="Validation completed.",
                extra={"validation_evidence": list(update.get("evidence") or [])},
            )
        else:
            transition_record(
                workspace,
                record,
                new_status="cancelled" if action == "cancel" else "obsolete",
                command="planledger evolution apply",
                reason=reason,
            )
    ctx.result.updated.append({"kind": kind, "id": record_id, "action": action})


def _create_evolution_records(ctx: _ApplyCtx, creates: dict[str, Any]) -> None:
    workspace = ctx.workspace
    for field_name, kind in (
        ("questions", "question"),
        ("assumptions", "assumption"),
        ("constraints", "constraint"),
        ("reviews", "review"),
    ):
        for item in creates.get(field_name, []) or []:
            if not isinstance(item, dict):
                continue
            scope_kind = str(item.get("scope_kind", "project"))
            scope_id = (
                str(item.get("scope_id")) if item.get("scope_id") is not None else None
            )
            title = str(item.get("title", ""))
            existing = _find_scoped_existing(
                workspace,
                kind,
                title,
                scope_kind=scope_kind,
                scope_id=scope_id,
            )
            if existing is not None:
                ctx.result.reused.append({"kind": kind, "id": existing})
                continue
            record_id = allocate_id(workspace, kind)
            front: dict[str, Any] = {
                "id": record_id,
                "type": kind,
                "scope_kind": scope_kind,
                "scope_id": scope_id,
                "title": title,
                "created_at": ctx.timestamp,
                "updated_at": ctx.timestamp,
            }
            body = ""
            if kind == "question":
                front.update(
                    {
                        "status": "open",
                        "priority": item.get("priority", "medium"),
                        "answer": None,
                        "answered_at": None,
                    }
                )
                body = "# Question\n"
            elif kind == "assumption":
                front.update(
                    {
                        "status": "unverified",
                        "confidence": item.get("confidence", "medium"),
                        "evidence": list(item.get("evidence") or []),
                    }
                )
                body = "# Assumption\n"
            elif kind == "constraint":
                front.update({"status": "active"})
                body = "# Constraint\n"
            elif kind == "review":
                front.update(
                    {
                        "status": "completed",
                        "outcome": item.get("outcome", "needs-followup"),
                        "findings": list(item.get("findings") or []),
                        "recommendations": list(item.get("recommendations") or []),
                        "closed_at": ctx.timestamp,
                    }
                )
                body = "# Review\n"
            create_record(workspace, kind, front, body)
            ctx.result.created.append({"kind": kind, "id": record_id})


def apply_evolution_bundle(
    workspace: Workspace,
    bundle: dict[str, Any],
    *,
    dry_run: bool = False,
    actor: str = "agent",
    provenance: str = "agent-generated",
) -> BundleApplyResult:
    details = validate_evolution_details(bundle)
    if details.errors:
        raise PlanledgerError(
            "invalid_bundle",
            "Bundle validation failed.",
            remediation=details.errors,
        )
    if dry_run:
        return _preview_evolution_bundle(workspace, bundle)
    ctx = _ApplyCtx(
        workspace=workspace,
        timestamp=now_iso(),
        actor=actor,
        provenance=provenance,
    )
    ctx.run_id = allocate_id(workspace, "run")
    run_front: dict[str, Any] = {
        "id": ctx.run_id,
        "type": "run",
        "actor": actor,
        "harness": None,
        "skill_version": None,
        "user_request": bundle.get("request", {}).get("title", ""),
        "planning_mode": bundle.get("request", {}).get("planning_mode", "repair"),
        "provenance": provenance,
        "source_context": [],
        "created_records": [],
        "created_at": ctx.timestamp,
        "updated_at": ctx.timestamp,
    }
    create_record(workspace, "run", run_front, "")
    ctx.result.created.append({"kind": "run", "id": ctx.run_id})
    for update in bundle.get("updates", []):
        if isinstance(update, dict):
            _apply_evolution_update(ctx, update)
    creates = bundle.get("creates", {})
    if isinstance(creates, dict):
        _create_evolution_records(ctx, creates)
    run_record = load_record(workspace, "run", ctx.run_id)
    run_record.front_matter["created_records"] = [
        item["id"] for item in ctx.result.created if "id" in item
    ]
    save_record(run_record)
    evt = append_event(
        workspace,
        command="planledger evolution apply",
        object_type="run",
        object_id=ctx.run_id,
        event_type="evolution_applied",
        after={
            "created": len(ctx.result.created),
            "updated": len(ctx.result.updated),
            "reused": len(ctx.result.reused),
        },
        actor=actor,
        source_run=ctx.run_id,
        provenance=ctx.provenance,
        correlation_id=ctx.run_id,
    )
    ctx.result.events.append(evt)
    return ctx.result
