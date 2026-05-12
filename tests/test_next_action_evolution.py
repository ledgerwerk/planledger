from __future__ import annotations

import json
from pathlib import Path


def _setup_ready_slice(invoke, workspace: Path) -> None:
    assert invoke(workspace, "goal", "create", "Goal").exit_code == 0
    assert (
        invoke(workspace, "initiative", "create", "Init", "--goal", "goal-0001").exit_code
        == 0
    )
    assert invoke(workspace, "initiative", "activate", "init-0001").exit_code == 0
    assert invoke(workspace, "plan", "draft", "--initiative", "init-0001").exit_code == 0
    assert invoke(workspace, "milestone", "add", "Milestone", "--plan", "plan-0001").exit_code == 0
    assert invoke(workspace, "slice", "add", "Slice", "--milestone", "ms-0001").exit_code == 0
    assert invoke(workspace, "slice", "ready", "slice-0001").exit_code == 0
    assert invoke(workspace, "plan", "accept", "plan-0001", "--note", "Ready").exit_code == 0


def test_open_question_under_exploring_goal_produces_answer_question(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    assert (
        invoke(workspace, "goal", "create", "Improve planning", "--status", "exploring").exit_code
        == 0
    )
    assert (
        invoke(
            workspace,
            "question",
            "add",
            "What exact outcome should improve?",
            "--goal",
            "goal-0001",
            "--priority",
            "high",
        ).exit_code
        == 0
    )
    result = invoke(workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["result"]["action"] == "answer-question"


def test_exploring_goal_without_open_questions_produces_review_goal(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    assert (
        invoke(workspace, "goal", "create", "Improve planning", "--status", "exploring").exit_code
        == 0
    )
    result = invoke(workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["result"]["action"] == "review-exploring-goal"


def test_cancelled_goal_with_ready_slice_does_not_produce_push_taskledger(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    _setup_ready_slice(invoke, workspace)
    assert (
        invoke(
            workspace,
            "goal",
            "cancel",
            "goal-0001",
            "--reason",
            "No longer useful.",
        ).exit_code
        == 0
    )
    result = invoke(workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["result"]["action"] != "push-taskledger"


def test_active_goal_with_all_slices_validated_produces_close_goal(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    _setup_ready_slice(invoke, workspace)
    assert invoke(workspace, "slice", "done", "slice-0001").exit_code == 0
    assert (
        invoke(
            workspace,
            "slice",
            "validate",
            "slice-0001",
            "--evidence",
            "pytest -q",
        ).exit_code
        == 0
    )
    result = invoke(workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["result"]["action"] == "close-fulfilled-goal"
