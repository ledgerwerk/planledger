from __future__ import annotations

import json
from pathlib import Path

import pytest

from planledger.errors import PlanledgerError
from planledger.storage import load_workspace_from_root
from planledger.taskledger import push_plan, push_slice


def _setup_ready_slice(invoke, workspace: Path) -> None:
    assert invoke(workspace, "goal", "create", "Goal").exit_code == 0
    assert (
        invoke(workspace, "initiative", "create", "Init", "--goal", "goal-0001").exit_code
        == 0
    )
    assert invoke(workspace, "initiative", "activate", "init-0001").exit_code == 0
    assert invoke(workspace, "plan", "draft", "--initiative", "init-0001").exit_code == 0
    assert invoke(workspace, "milestone", "add", "Milestone", "--plan", "plan-0001").exit_code == 0
    assert invoke(workspace, "slice", "add", "Slice one", "--milestone", "ms-0001").exit_code == 0
    assert invoke(workspace, "slice", "ready", "slice-0001").exit_code == 0


def test_push_plan_rejects_plan_under_cancelled_goal(
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
    ws = load_workspace_from_root(workspace)
    with pytest.raises(PlanledgerError, match="parent goal goal-0001 is cancelled"):
        push_plan(ws, "plan-0001", create_tasks=True)


def test_push_rejects_slice_under_fulfilled_initiative(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    _setup_ready_slice(invoke, workspace)
    assert (
        invoke(
            workspace,
            "initiative",
            "complete",
            "init-0001",
            "--reason",
            "Delivered the intended outcome.",
        ).exit_code
        == 0
    )
    ws = load_workspace_from_root(workspace)
    with pytest.raises(PlanledgerError, match="parent initiative init-0001 is fulfilled"):
        push_slice(ws, "slice-0001", create_task=True, activate=False)


def test_cancelled_and_obsolete_slices_are_skipped_from_push_plan(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    _setup_ready_slice(invoke, workspace)
    assert invoke(workspace, "slice", "add", "Slice two", "--milestone", "ms-0001").exit_code == 0
    assert (
        invoke(
            workspace,
            "slice",
            "obsolete",
            "slice-0002",
            "--reason",
            "Changed direction.",
        ).exit_code
        == 0
    )
    ws = load_workspace_from_root(workspace)
    result = push_plan(ws, "plan-0001", dry_run=True)
    assert result["ready_slice_count"] == 1
    assert result["created"][0]["slice"] == "slice-0001"
    assert result["skipped"] == [{"slice": "slice-0002", "reason": "obsolete"}]


def test_push_plan_json_error_includes_remediation(
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
    result = invoke(
        workspace,
        "--json",
        "taskledger",
        "push-plan",
        "plan-0001",
        "--create-tasks",
    )
    payload = json.loads(result.stdout)
    assert result.exit_code != 0
    assert payload["error"]["kind"] == "terminal_parent"
    assert payload["error"]["remediation"]
