# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from planledger.lifecycle import ACTIVE_GOAL_STATUSES, blocks_execution, is_terminal
from planledger.models import Record, Workspace
from planledger.storage import (
    active_initiative,
    doctor,
    latest_plan_for_initiative,
    lint_plan,
    list_records,
    load_record,
)
from planledger.taskledger import reconcile


def _action(
    action: str,
    next_command: str,
    *,
    next_item: dict[str, Any] | None = None,
    commands: list[dict[str, Any]] | None = None,
    blocking: list[Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "kind": "planledger_next_action",
        "action": action,
        "next_command": next_command,
    }
    if next_item is not None:
        result["next_item"] = next_item
    if commands is not None:
        result["commands"] = commands
    if blocking is not None:
        result["blocking"] = blocking
    return result


def _cmd(
    kind: str,
    label: str,
    command: str,
    *,
    primary: bool = True,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "label": label,
        "command": command,
        "primary": primary,
    }


def _priority_rank(value: str | None) -> int:
    order = {"high": 0, "medium": 1, "low": 2}
    return order.get(str(value or "medium"), 1)


def _active_goal_ids(workspace: Workspace) -> set[str]:
    return {
        goal.record_id
        for goal in list_records(workspace, "goal")
        if goal.front_matter.get("status") in ACTIVE_GOAL_STATUSES
    }


def _eligible_active_initiative(workspace: Workspace) -> Record | None:
    active_id = active_initiative(workspace)
    if active_id is None:
        return None
    initiative = load_record(workspace, "initiative", active_id)
    status = str(initiative.front_matter.get("status", ""))
    if blocks_execution("initiative", status):
        return None
    goal_ref = initiative.front_matter.get("goal")
    if goal_ref is not None:
        goal = load_record(workspace, "goal", str(goal_ref))
        if blocks_execution("goal", str(goal.front_matter.get("status", ""))):
            return None
    return initiative


def _plan_goal_status(workspace: Workspace, plan: Record) -> str | None:
    goal_ref = plan.front_matter.get("goal")
    if goal_ref is None:
        initiative = load_record(workspace, "initiative", str(plan.front_matter.get("initiative")))
        goal_ref = initiative.front_matter.get("goal")
    if goal_ref is None:
        return None
    goal = load_record(workspace, "goal", str(goal_ref))
    return str(goal.front_matter.get("status", ""))


def _ready_slice_is_actionable(workspace: Workspace, slice_record: Record) -> bool:
    plan = load_record(workspace, "plan", str(slice_record.front_matter.get("plan")))
    if blocks_execution("plan", str(plan.front_matter.get("status", ""))):
        return False
    initiative = load_record(workspace, "initiative", str(plan.front_matter.get("initiative")))
    if blocks_execution("initiative", str(initiative.front_matter.get("status", ""))):
        return False
    goal_ref = plan.front_matter.get("goal") or initiative.front_matter.get("goal")
    if goal_ref is not None:
        goal = load_record(workspace, "goal", str(goal_ref))
        if blocks_execution("goal", str(goal.front_matter.get("status", ""))):
            return False
    return True


def _goal_ready_for_completion(workspace: Workspace, goal: Record) -> bool:
    initiatives = [
        initiative
        for initiative in list_records(workspace, "initiative")
        if initiative.front_matter.get("goal") == goal.record_id
    ]
    if not initiatives:
        return False
    plan_ids = {
        plan.record_id
        for plan in list_records(workspace, "plan")
        if plan.front_matter.get("goal") == goal.record_id
        or plan.front_matter.get("initiative") in {item.record_id for item in initiatives}
    }
    slices = [
        slice_record
        for slice_record in list_records(workspace, "slice")
        if slice_record.front_matter.get("plan") in plan_ids
    ]
    if not slices:
        return False
    return all(
        slice_record.front_matter.get("status") == "validated" for slice_record in slices
    )


def _action_for_doctor_issues(workspace: Workspace) -> dict[str, Any] | None:
    issues = list(doctor(workspace).get("issues", []))
    if not issues:
        return None
    return _action(
        "repair-ledger",
        "planledger doctor",
        commands=[_cmd("inspect", "Inspect ledger health", "planledger doctor")],
        blocking=[{"kind": "doctor", "reason": issue} for issue in issues],
    )


def _action_for_open_question(workspace: Workspace) -> dict[str, Any] | None:
    active_goal_ids = _active_goal_ids(workspace)
    questions = [
        question
        for question in list_records(workspace, "question")
        if question.front_matter.get("status") == "open"
        and (
            question.front_matter.get("scope_kind") != "goal"
            or question.front_matter.get("scope_id") in active_goal_ids
        )
    ]
    if not questions:
        return None
    question = sorted(
        questions,
        key=lambda item: (_priority_rank(item.front_matter.get("priority")), item.record_id),
    )[0]
    return _action(
        "answer-question",
        f"planledger question show {question.record_id}",
        next_item={
            "kind": "question",
            "id": question.record_id,
            "title": question.front_matter.get("title"),
        },
        commands=[
            _cmd("inspect", "Show question", f"planledger question show {question.record_id}"),
            _cmd(
                "complete",
                "Answer question",
                f'planledger question answer {question.record_id} --answer "..."',
                primary=False,
            ),
        ],
    )


def _action_for_exploring_goal(workspace: Workspace) -> dict[str, Any] | None:
    open_goal_ids = {
        question.front_matter.get("scope_id")
        for question in list_records(workspace, "question")
        if question.front_matter.get("status") == "open"
        and question.front_matter.get("scope_kind") == "goal"
    }
    exploring_goals = [
        goal
        for goal in list_records(workspace, "goal")
        if goal.front_matter.get("status") == "exploring"
        and goal.record_id not in open_goal_ids
    ]
    if not exploring_goals:
        return None
    goal = sorted(exploring_goals, key=lambda item: item.record_id)[0]
    return _action(
        "review-exploring-goal",
        f"planledger goal show {goal.record_id}",
        next_item={"kind": "goal", "id": goal.record_id, "title": goal.front_matter.get("title")},
        commands=[
            _cmd("inspect", "Review goal", f"planledger goal show {goal.record_id}"),
            _cmd(
                "complete",
                "Activate goal",
                f'planledger goal activate {goal.record_id} --reason "Goal is now clear enough to plan."',
                primary=False,
            ),
        ],
    )


def _action_for_unverified_assumption(workspace: Workspace) -> dict[str, Any] | None:
    assumptions = [
        assumption
        for assumption in list_records(workspace, "assumption")
        if assumption.front_matter.get("status") == "unverified"
    ]
    if not assumptions:
        return None
    assumption = sorted(
        assumptions,
        key=lambda item: (_priority_rank(item.front_matter.get("confidence")), item.record_id),
    )[0]
    return _action(
        "resolve-assumption",
        f"planledger assumption show {assumption.record_id}",
        next_item={
            "kind": "assumption",
            "id": assumption.record_id,
            "title": assumption.front_matter.get("title"),
        },
        commands=[
            _cmd(
                "inspect",
                "Show assumption",
                f"planledger assumption show {assumption.record_id}",
            ),
            _cmd(
                "complete",
                "Confirm assumption",
                f'planledger assumption confirm {assumption.record_id} --evidence "..."',
                primary=False,
            ),
        ],
    )


def _action_for_open_decision(workspace: Workspace) -> dict[str, Any] | None:
    decisions = [
        decision
        for decision in list_records(workspace, "decision")
        if decision.front_matter.get("status") == "open"
    ]
    if not decisions:
        return None
    decision = decisions[0]
    return _action(
        "decision-needed",
        f"planledger option compare {decision.record_id}",
        next_item={
            "kind": "decision",
            "id": decision.record_id,
            "title": decision.front_matter.get("title"),
        },
        commands=[
            _cmd(
                "inspect",
                "Compare options",
                f"planledger option compare {decision.record_id}",
            )
        ],
    )


def _action_for_draft_plan(workspace: Workspace) -> dict[str, Any] | None:
    draft_plans = [
        plan for plan in list_records(workspace, "plan") if plan.front_matter.get("status") == "draft"
    ]
    if not draft_plans:
        return None
    plan = draft_plans[0]
    goal_status = _plan_goal_status(workspace, plan)
    if goal_status is not None and blocks_execution("goal", goal_status):
        return None
    lint = lint_plan(workspace, plan)
    if lint.issues:
        return _action(
            "fix-plan-lint",
            f"planledger plan lint {plan.record_id}",
            next_item={"kind": "plan", "id": plan.record_id},
            blocking=[{"kind": "lint", "reason": issue} for issue in lint.issues],
            commands=[_cmd("inspect", "Run lint", f"planledger plan lint {plan.record_id}")],
        )
    return _action(
        "accept-plan",
        f'planledger plan accept {plan.record_id} --note "Ready"',
        next_item={"kind": "plan", "id": plan.record_id},
        commands=[
            _cmd(
                "complete",
                "Accept plan",
                f'planledger plan accept {plan.record_id} --note "Ready"',
            )
        ],
    )


def _action_for_missing_initiative(workspace: Workspace) -> dict[str, Any] | None:
    if _eligible_active_initiative(workspace) is not None:
        return None
    active_goals = [
        goal for goal in list_records(workspace, "goal") if goal.front_matter.get("status") == "active"
    ]
    initiatives = [
        initiative
        for initiative in list_records(workspace, "initiative")
        if not blocks_execution("initiative", str(initiative.front_matter.get("status", "")))
    ]
    if initiatives:
        target = initiatives[0]
        return _action(
            "activate-initiative",
            f"planledger initiative activate {target.record_id}",
            next_item={
                "kind": "initiative",
                "id": target.record_id,
                "title": target.front_matter.get("title"),
            },
            commands=[
                _cmd(
                    "complete",
                    "Activate initiative",
                    f"planledger initiative activate {target.record_id}",
                )
            ],
        )
    if not active_goals:
        return _action(
            "create-initiative",
            'planledger initiative create "<title>" --goal goal-0001',
            commands=[
                _cmd(
                    "complete",
                    "Create initiative",
                    'planledger initiative create "<title>" --goal goal-0001',
                )
            ],
        )
    goal = active_goals[0]
    return _action(
        "create-initiative",
        f'planledger initiative create "<title>" --goal {goal.record_id}',
        next_item={"kind": "goal", "id": goal.record_id, "title": goal.front_matter.get("title")},
        commands=[
            _cmd(
                "complete",
                "Create initiative",
                f'planledger initiative create "<title>" --goal {goal.record_id}',
            )
        ],
    )


def _action_for_missing_plan(workspace: Workspace) -> dict[str, Any] | None:
    initiative = _eligible_active_initiative(workspace)
    if initiative is None:
        return None
    plan = latest_plan_for_initiative(workspace, initiative.record_id)
    if plan is not None:
        return None
    return _action(
        "plan-needed",
        f"planledger plan draft --initiative {initiative.record_id}",
        next_item={"kind": "initiative", "id": initiative.record_id},
        commands=[
            _cmd(
                "complete",
                "Draft plan",
                f"planledger plan draft --initiative {initiative.record_id}",
            )
        ],
    )


def _action_for_missing_milestones(workspace: Workspace) -> dict[str, Any] | None:
    initiative = _eligible_active_initiative(workspace)
    if initiative is None:
        return None
    plan = latest_plan_for_initiative(workspace, initiative.record_id)
    if plan is None:
        return None
    if blocks_execution("plan", str(plan.front_matter.get("status", ""))):
        return None
    milestones = [
        milestone
        for milestone in list_records(workspace, "milestone")
        if milestone.front_matter.get("plan") == plan.record_id
    ]
    if milestones:
        return None
    return _action(
        "milestone-needed",
        f'planledger milestone add --plan {plan.record_id} "<title>"',
        next_item={"kind": "plan", "id": plan.record_id},
        commands=[
            _cmd(
                "complete",
                "Add milestone",
                f'planledger milestone add --plan {plan.record_id} "<title>"',
            )
        ],
    )


def _action_for_missing_slices(workspace: Workspace) -> dict[str, Any] | None:
    initiative = _eligible_active_initiative(workspace)
    if initiative is None:
        return None
    plan = latest_plan_for_initiative(workspace, initiative.record_id)
    if plan is None:
        return None
    milestones = [
        milestone
        for milestone in list_records(workspace, "milestone")
        if milestone.front_matter.get("plan") == plan.record_id
    ]
    if not milestones:
        return None
    slices = [
        item
        for item in list_records(workspace, "slice")
        if item.front_matter.get("plan") == plan.record_id
    ]
    if slices:
        return None
    milestone = milestones[0]
    return _action(
        "slice-needed",
        f'planledger slice add --milestone {milestone.record_id} "<title>"',
        next_item={"kind": "milestone", "id": milestone.record_id},
        commands=[
            _cmd(
                "complete",
                "Add slice",
                f'planledger slice add --milestone {milestone.record_id} "<title>"',
            )
        ],
    )


def _action_for_shaping_slice(workspace: Workspace) -> dict[str, Any] | None:
    slices = [
        item
        for item in list_records(workspace, "slice")
        if item.front_matter.get("status") in {"idea", "shaping"}
    ]
    if not slices:
        return None
    candidate = slices[0]
    return _action(
        "slice-ready",
        f"planledger slice ready {candidate.record_id}",
        next_item={"kind": "slice", "id": candidate.record_id},
        commands=[
            _cmd("complete", "Mark ready", f"planledger slice ready {candidate.record_id}")
        ],
    )


def _action_for_ready_slice(workspace: Workspace) -> dict[str, Any] | None:
    ready = [
        item
        for item in list_records(workspace, "slice")
        if item.front_matter.get("status") == "ready-for-execution"
        and _ready_slice_is_actionable(workspace, item)
    ]
    if not ready:
        return None
    candidate = ready[0]
    bindings = list(candidate.front_matter.get("taskledger_bindings") or [])
    if bindings:
        return None
    return _action(
        "push-taskledger",
        f"planledger taskledger push {candidate.record_id} --create-task",
        next_item={"kind": "slice", "id": candidate.record_id},
        commands=[
            _cmd(
                "complete",
                "Push to taskledger",
                f"planledger taskledger push {candidate.record_id} --create-task",
            )
        ],
    )


def _action_for_executing_slice(workspace: Workspace) -> dict[str, Any] | None:
    executing = [
        item
        for item in list_records(workspace, "slice")
        if item.front_matter.get("status") == "in-execution"
    ]
    if not executing:
        return None
    drift = reconcile(workspace).get("drift")
    if isinstance(drift, list) and drift:
        return _action(
            "reconcile-drift",
            "planledger taskledger reconcile",
            commands=[_cmd("inspect", "Reconcile drift", "planledger taskledger reconcile")],
            blocking=drift,
        )
    candidate = executing[0]
    return _action(
        "pull-taskledger",
        f"planledger taskledger pull --slice {candidate.record_id}",
        next_item={"kind": "slice", "id": candidate.record_id},
        commands=[
            _cmd(
                "inspect",
                "Pull task status",
                f"planledger taskledger pull --slice {candidate.record_id}",
            )
        ],
    )


def _action_for_completed_goal(workspace: Workspace) -> dict[str, Any] | None:
    active_goals = [
        goal for goal in list_records(workspace, "goal") if goal.front_matter.get("status") == "active"
    ]
    for goal in active_goals:
        if _goal_ready_for_completion(workspace, goal):
            return _action(
                "close-fulfilled-goal",
                f'planledger goal complete {goal.record_id} --reason "All slices were validated."',
                next_item={
                    "kind": "goal",
                    "id": goal.record_id,
                    "title": goal.front_matter.get("title"),
                },
                commands=[
                    _cmd("inspect", "Review goal", f"planledger goal show {goal.record_id}"),
                    _cmd(
                        "complete",
                        "Complete goal",
                        f'planledger goal complete {goal.record_id} --reason "All slices were validated."',
                        primary=False,
                    ),
                ],
            )
    return None


def _action_for_closed_goal_review(workspace: Workspace) -> dict[str, Any] | None:
    closed_goals = [
        goal
        for goal in list_records(workspace, "goal")
        if goal.front_matter.get("status") in {"fulfilled", "cancelled", "superseded"}
    ]
    if not closed_goals:
        return None
    goal = closed_goals[0]
    return _action(
        "review-closed-goals",
        f"planledger goal show {goal.record_id}",
        next_item={"kind": "goal", "id": goal.record_id, "title": goal.front_matter.get("title")},
        commands=[_cmd("inspect", "Review closed goal", f"planledger goal show {goal.record_id}")],
    )


CHECKERS = [
    _action_for_doctor_issues,
    _action_for_open_question,
    _action_for_exploring_goal,
    _action_for_unverified_assumption,
    _action_for_open_decision,
    _action_for_draft_plan,
    _action_for_missing_initiative,
    _action_for_missing_plan,
    _action_for_missing_milestones,
    _action_for_missing_slices,
    _action_for_shaping_slice,
    _action_for_ready_slice,
    _action_for_executing_slice,
    _action_for_completed_goal,
    _action_for_closed_goal_review,
]


def suggest_next_action(workspace: Workspace) -> dict[str, Any]:
    for checker in CHECKERS:
        action = checker(workspace)
        if action is not None:
            return action
    return _action(
        "inspect-status",
        "planledger status --full",
        commands=[_cmd("inspect", "Inspect status", "planledger status --full")],
    )
