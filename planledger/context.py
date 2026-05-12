from __future__ import annotations

from typing import Any

from planledger.lifecycle import TERMINAL_GOAL_STATUSES, blocks_execution
from planledger.models import Workspace
from planledger.next_action import suggest_next_action
from planledger.storage import (
    active_initiative,
    latest_plan_for_initiative,
    list_events,
    list_records,
    load_record,
    parse_ref_numeric,
    record_counts,
)


def _record_summary(
    record: Any,
    include_body: bool = False,
    max_body_chars: int = 4000,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "id": record.record_id,
        "kind": record.kind,
        "front_matter": dict(record.front_matter),
    }
    if include_body:
        body = record.body
        if len(body) > max_body_chars:
            body = body[:max_body_chars] + "\n... (truncated)"
        summary["body"] = body
    return summary


def _sort_recent_goals(goals: list[Any]) -> list[Any]:
    def _key(record: Any) -> tuple[str, str, int]:
        front = record.front_matter
        return (
            str(front.get("closed_at") or ""),
            str(front.get("updated_at") or ""),
            parse_ref_numeric(record.record_id),
        )

    return sorted(goals, key=_key, reverse=True)


def _slice_block_reason(workspace: Workspace, slice_record: Any) -> str | None:
    plan_id = slice_record.front_matter.get("plan")
    if plan_id is None:
        return "missing parent plan"
    plan = load_record(workspace, "plan", str(plan_id))
    initiative = load_record(workspace, "initiative", str(plan.front_matter.get("initiative")))
    goal_ref = plan.front_matter.get("goal") or initiative.front_matter.get("goal")
    if goal_ref is not None:
        goal = load_record(workspace, "goal", str(goal_ref))
        goal_status = str(goal.front_matter.get("status", ""))
        if blocks_execution("goal", goal_status):
            return f"parent goal {goal.record_id} is {goal_status}"
    initiative_status = str(initiative.front_matter.get("status", ""))
    if blocks_execution("initiative", initiative_status):
        return f"parent initiative {initiative.record_id} is {initiative_status}"
    plan_status = str(plan.front_matter.get("status", ""))
    if blocks_execution("plan", plan_status):
        return f"parent plan {plan.record_id} is {plan_status}"
    return None


def export_context(
    workspace: Workspace,
    *,
    include_taskledger: bool = False,
    include_bodies: bool = False,
    max_body_chars: int = 4000,
    max_events: int = 0,
    allow_external: bool = False,
) -> dict[str, Any]:
    project_config = workspace.config.get("project", {})

    result: dict[str, Any] = {
        "kind": "planledger_context_export",
        "schema": "planledger.context.v1",
        "project": {
            "name": project_config.get("name", "Planledger"),
            "root": str(workspace.root),
            "ledger_ref": workspace.ledger_ref,
        },
    }

    all_goals = list_records(workspace, "goal")
    active_goal_records = [
        goal for goal in all_goals if goal.front_matter.get("status") == "active"
    ]
    exploring_goal_records = [
        goal for goal in all_goals if goal.front_matter.get("status") == "exploring"
    ]
    parked_goal_records = [
        goal for goal in all_goals if goal.front_matter.get("status") == "parked"
    ]
    closed_goal_records = _sort_recent_goals(
        [
            goal
            for goal in all_goals
            if goal.front_matter.get("status") in TERMINAL_GOAL_STATUSES
        ]
    )
    active_goals = [
        _record_summary(
            goal,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        for goal in active_goal_records
    ]
    exploring_goals = [
        _record_summary(
            goal,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        for goal in exploring_goal_records
    ]
    parked_goals = [
        _record_summary(
            goal,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        for goal in parked_goal_records
    ]
    closed_goals = [
        _record_summary(
            goal,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        for goal in closed_goal_records[:10]
    ]

    active: dict[str, Any] = {}
    active_init_id = active_initiative(workspace)
    if active_init_id is not None:
        try:
            initiative = load_record(
                workspace,
                "initiative",
                active_init_id,
            )
            active["initiative"] = _record_summary(
                initiative,
                include_body=include_bodies,
                max_body_chars=max_body_chars,
            )

            goal_ref = initiative.front_matter.get("goal")
            if goal_ref is not None:
                try:
                    goal = load_record(workspace, "goal", str(goal_ref))
                    active["goal"] = _record_summary(
                        goal,
                        include_body=include_bodies,
                        max_body_chars=max_body_chars,
                    )
                except Exception:
                    active["goal"] = {
                        "id": str(goal_ref),
                        "kind": "goal",
                        "error": "not_found",
                    }

            latest_plan = latest_plan_for_initiative(
                workspace,
                active_init_id,
            )
            if latest_plan is not None:
                active["latest_plan"] = _record_summary(
                    latest_plan,
                    include_body=include_bodies,
                    max_body_chars=max_body_chars,
                )
        except Exception:
            active["initiative"] = {
                "id": active_init_id,
                "error": "not_found",
            }

    result["active"] = active

    all_initiatives = list_records(workspace, "initiative")
    active_initiatives = [
        _record_summary(
            initiative,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        for initiative in all_initiatives
        if initiative.front_matter.get("status") in {"shaping", "planned", "executing"}
    ]
    accepted_plans = [
        _record_summary(
            plan,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        for plan in list_records(workspace, "plan")
        if plan.front_matter.get("status") == "accepted"
    ]
    all_decisions = list_records(workspace, "decision")
    open_decisions = [
        _record_summary(
            d,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        for d in all_decisions
        if d.front_matter.get("status") == "open"
    ]

    all_risks = list_records(workspace, "risk")
    risks = [
        _record_summary(
            r,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        for r in all_risks
        if r.front_matter.get("status") == "open"
    ]

    all_slices = list_records(workspace, "slice")
    ready_slices: list[dict[str, Any]] = []
    blocked_from_taskledger: list[dict[str, Any]] = []
    for slice_record in all_slices:
        if slice_record.front_matter.get("status") != "ready-for-execution":
            continue
        summary = _record_summary(
            slice_record,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        blocked_reason = _slice_block_reason(workspace, slice_record)
        if blocked_reason is None:
            ready_slices.append(summary)
        else:
            summary["blocked_reason"] = blocked_reason
            blocked_from_taskledger.append(summary)
    executing_slices = [
        _record_summary(
            s,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        for s in all_slices
        if s.front_matter.get("status") == "in-execution"
    ]

    all_bindings = list_records(workspace, "binding")
    bindings = [
        _record_summary(
            b,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        for b in all_bindings
    ]

    result["records"] = {
        "open_decisions": open_decisions,
        "risks": risks,
        "ready_slices": ready_slices,
        "executing_slices": executing_slices,
        "bindings": bindings,
        "open_questions": [
            _record_summary(
                question,
                include_body=include_bodies,
                max_body_chars=max_body_chars,
            )
            for question in list_records(workspace, "question")
            if question.front_matter.get("status") == "open"
        ],
        "unverified_assumptions": [
            _record_summary(
                assumption,
                include_body=include_bodies,
                max_body_chars=max_body_chars,
            )
            for assumption in list_records(workspace, "assumption")
            if assumption.front_matter.get("status") == "unverified"
        ],
        "active_constraints": [
            _record_summary(
                constraint,
                include_body=include_bodies,
                max_body_chars=max_body_chars,
            )
            for constraint in list_records(workspace, "constraint")
            if constraint.front_matter.get("status") == "active"
        ],
        "recently_closed_goals": closed_goals,
        "blocked_from_taskledger": blocked_from_taskledger,
    }

    open_questions = result["records"]["open_questions"]
    unverified_assumptions = result["records"]["unverified_assumptions"]
    active_constraints = result["records"]["active_constraints"]
    recent_reviews = [
        _record_summary(
            review,
            include_body=include_bodies,
            max_body_chars=max_body_chars,
        )
        for review in _sort_recent_goals(list_records(workspace, "review"))[:10]
    ]
    result["current"] = {
        "active_goals": active_goals,
        "exploring_goals": exploring_goals,
        "active_initiatives": active_initiatives,
        "accepted_plans": accepted_plans,
        "ready_slices": ready_slices,
        "executing_slices": executing_slices,
    }
    result["blocked"] = {
        "open_questions": open_questions,
        "unverified_assumptions": unverified_assumptions,
        "open_decisions": open_decisions,
        "open_risks": risks,
    }
    result["history"] = {
        "recently_fulfilled_goals": [
            item
            for item in closed_goals
            if item["front_matter"].get("status") == "fulfilled"
        ],
        "recently_cancelled_goals": [
            item
            for item in closed_goals
            if item["front_matter"].get("status") == "cancelled"
        ],
        "recently_superseded_goals": [
            item
            for item in closed_goals
            if item["front_matter"].get("status") == "superseded"
        ],
        "recent_reviews": recent_reviews,
        "recent_events": [],
    }
    result["handoff"] = {
        "ready_for_taskledger": ready_slices,
        "blocked_from_taskledger": blocked_from_taskledger,
    }
    result["goals"] = {
        "active": active_goals,
        "exploring": exploring_goals,
        "parked": parked_goals,
        "closed_recent": closed_goals,
    }
    result["questions"] = {"open": open_questions}
    result["assumptions"] = {"unverified": unverified_assumptions}
    result["constraints"] = {"active": active_constraints}

    if include_taskledger:
        try:
            from planledger.taskledger import detect

            result["taskledger"] = detect(workspace)
        except Exception:
            result["taskledger"] = {"detected": False}

    if max_events > 0:
        events = list_events(workspace, limit=max_events)
        if events:
            result["recent_events"] = events
            result["history"]["recent_events"] = events
    result["counts"] = record_counts(workspace)
    if allow_external:
        result["next_action"] = suggest_next_action(workspace)
    else:
        result["next_action"] = {
            "kind": "planledger_next_action",
            "action": "inspect-status",
            "next_command": "planledger status --full",
            "note": "allow_external=False; full next action skipped",
        }

    return result
