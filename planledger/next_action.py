# ruff: noqa: E501
from __future__ import annotations

from typing import Any

from planledger.models import Workspace
from planledger.storage import (
    active_initiative,
    latest_plan_for_initiative,
    lint_plan,
    list_records,
)
from planledger.taskledger import reconcile


def suggest_next_action(workspace: Workspace) -> dict[str, Any]:
    active = active_initiative(workspace)
    if active is None:
        initiatives = list_records(workspace, "initiative")
        if initiatives:
            target = initiatives[0]
            return {
                "kind": "planledger_next_action",
                "action": "activate-initiative",
                "next_command": f"planledger initiative activate {target.record_id}",
                "next_item": {
                    "kind": "initiative",
                    "id": target.record_id,
                    "title": target.front_matter.get("title"),
                },
                "commands": [
                    {
                        "kind": "complete",
                        "label": "Activate initiative",
                        "command": f"planledger initiative activate {target.record_id}",
                        "primary": True,
                    }
                ],
            }

        return {
            "kind": "planledger_next_action",
            "action": "create-initiative",
            "next_command": 'planledger initiative create "<title>" --goal goal-0001',
            "commands": [
                {
                    "kind": "complete",
                    "label": "Create initiative",
                    "command": 'planledger initiative create "<title>" --goal goal-0001',
                    "primary": True,
                }
            ],
        }

    plan = latest_plan_for_initiative(workspace, active)
    if plan is None:
        return {
            "kind": "planledger_next_action",
            "action": "plan-needed",
            "next_command": f"planledger plan draft --initiative {active}",
            "next_item": {"kind": "initiative", "id": active},
            "commands": [
                {
                    "kind": "complete",
                    "label": "Draft plan",
                    "command": f"planledger plan draft --initiative {active}",
                    "primary": True,
                }
            ],
        }

    decisions = [
        decision
        for decision in list_records(workspace, "decision")
        if decision.front_matter.get("initiative") == active
        and decision.front_matter.get("status") == "open"
    ]
    if decisions:
        decision = decisions[0]
        return {
            "kind": "planledger_next_action",
            "action": "decision-needed",
            "next_command": f"planledger option compare {decision.record_id}",
            "next_item": {
                "kind": "decision",
                "id": decision.record_id,
                "title": decision.front_matter.get("title"),
            },
            "commands": [
                {
                    "kind": "inspect",
                    "label": "Compare options",
                    "command": f"planledger option compare {decision.record_id}",
                    "primary": True,
                },
                {
                    "kind": "complete",
                    "label": "Accept decision",
                    "command": (
                        f"planledger decision accept {decision.record_id} --option OPT "
                        '--rationale "..."'
                    ),
                    "primary": False,
                },
            ],
        }

    if plan.front_matter.get("status") == "draft":
        lint = lint_plan(workspace, plan)
        if lint.issues:
            return {
                "kind": "planledger_next_action",
                "action": "fix-plan-lint",
                "next_command": f"planledger plan lint {plan.record_id}",
                "next_item": {"kind": "plan", "id": plan.record_id},
                "blocking": [
                    {"kind": "lint", "reason": issue} for issue in lint.issues
                ],
                "commands": [
                    {
                        "kind": "inspect",
                        "label": "Run lint",
                        "command": f"planledger plan lint {plan.record_id}",
                        "primary": True,
                    }
                ],
            }
        return {
            "kind": "planledger_next_action",
            "action": "accept-plan",
            "next_command": f'planledger plan accept {plan.record_id} --note "Ready"',
            "next_item": {"kind": "plan", "id": plan.record_id},
            "commands": [
                {
                    "kind": "complete",
                    "label": "Accept plan",
                    "command": f'planledger plan accept {plan.record_id} --note "Ready"',
                    "primary": True,
                }
            ],
        }

    milestones = [
        milestone
        for milestone in list_records(workspace, "milestone")
        if milestone.front_matter.get("plan") == plan.record_id
    ]
    if not milestones:
        return {
            "kind": "planledger_next_action",
            "action": "milestone-needed",
            "next_command": f'planledger milestone add --plan {plan.record_id} "<title>"',
            "next_item": {"kind": "plan", "id": plan.record_id},
            "commands": [
                {
                    "kind": "complete",
                    "label": "Add milestone",
                    "command": f'planledger milestone add --plan {plan.record_id} "<title>"',
                    "primary": True,
                }
            ],
        }

    slices = [
        item
        for item in list_records(workspace, "slice")
        if item.front_matter.get("plan") == plan.record_id
    ]
    if not slices:
        milestone = milestones[0]
        return {
            "kind": "planledger_next_action",
            "action": "slice-needed",
            "next_command": f'planledger slice add --milestone {milestone.record_id} "<title>"',
            "next_item": {"kind": "milestone", "id": milestone.record_id},
            "commands": [
                {
                    "kind": "complete",
                    "label": "Add slice",
                    "command": f'planledger slice add --milestone {milestone.record_id} "<title>"',
                    "primary": True,
                }
            ],
        }

    shaping = [
        item
        for item in slices
        if item.front_matter.get("status") in {"idea", "shaping"}
    ]
    if shaping:
        candidate = shaping[0]
        return {
            "kind": "planledger_next_action",
            "action": "slice-ready",
            "next_command": f"planledger slice ready {candidate.record_id}",
            "next_item": {"kind": "slice", "id": candidate.record_id},
            "commands": [
                {
                    "kind": "complete",
                    "label": "Mark ready",
                    "command": f"planledger slice ready {candidate.record_id}",
                    "primary": True,
                }
            ],
        }

    ready = [
        item
        for item in slices
        if item.front_matter.get("status") == "ready-for-execution"
    ]
    if ready:
        candidate = ready[0]
        bindings = list(candidate.front_matter.get("taskledger_bindings") or [])
        if not bindings:
            return {
                "kind": "planledger_next_action",
                "action": "push-taskledger",
                "next_command": (
                    f"planledger taskledger push {candidate.record_id} --create-task"
                ),
                "next_item": {"kind": "slice", "id": candidate.record_id},
                "commands": [
                    {
                        "kind": "complete",
                        "label": "Push to taskledger",
                        "command": (
                            f"planledger taskledger push {candidate.record_id} --create-task"
                        ),
                        "primary": True,
                    }
                ],
            }

    executing = [
        item for item in slices if item.front_matter.get("status") == "in-execution"
    ]
    if executing:
        candidate = executing[0]
        drift = reconcile(workspace).get("drift")
        if isinstance(drift, list) and drift:
            return {
                "kind": "planledger_next_action",
                "action": "reconcile-drift",
                "next_command": "planledger taskledger reconcile",
                "commands": [
                    {
                        "kind": "inspect",
                        "label": "Reconcile drift",
                        "command": "planledger taskledger reconcile",
                        "primary": True,
                    }
                ],
                "blocking": drift,
            }
        return {
            "kind": "planledger_next_action",
            "action": "pull-taskledger",
            "next_command": f"planledger taskledger pull --slice {candidate.record_id}",
            "next_item": {"kind": "slice", "id": candidate.record_id},
            "commands": [
                {
                    "kind": "inspect",
                    "label": "Pull task status",
                    "command": f"planledger taskledger pull --slice {candidate.record_id}",
                    "primary": True,
                }
            ],
        }

    if slices and all(
        item.front_matter.get("status") in {"executed", "validated"} for item in slices
    ):
        return {
            "kind": "planledger_next_action",
            "action": "review-initiative",
            "next_command": f"planledger initiative show {active}",
            "next_item": {"kind": "initiative", "id": active},
            "commands": [
                {
                    "kind": "inspect",
                    "label": "Review initiative",
                    "command": f"planledger initiative show {active}",
                    "primary": True,
                }
            ],
        }

    return {
        "kind": "planledger_next_action",
        "action": "inspect-status",
        "next_command": "planledger status --full",
        "commands": [
            {
                "kind": "inspect",
                "label": "Inspect status",
                "command": "planledger status --full",
                "primary": True,
            }
        ],
    }
