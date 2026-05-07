from __future__ import annotations

import json
from pathlib import Path


def _setup_core(invoke, workspace: Path) -> None:
    assert invoke(workspace, "goal", "create", "Test goal").exit_code == 0
    assert (
        invoke(
            workspace, "initiative", "create", "Test initiative", "--goal", "goal-0001"
        ).exit_code
        == 0
    )
    assert invoke(workspace, "initiative", "activate", "init-0001").exit_code == 0


def test_plan_milestone_slice_flow(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    _setup_core(invoke, workspace)

    draft_result = invoke(workspace, "plan", "draft", "--initiative", "init-0001")
    assert draft_result.exit_code == 0
    assert "plan-0001" in draft_result.stdout

    plan_show_initial = invoke(workspace, "plan", "show", "plan-0001")
    assert plan_show_initial.exit_code == 0
    assert "Goal: goal-0001 — Test goal" in plan_show_initial.stdout
    assert "Initiative: init-0001 — Test initiative" in plan_show_initial.stdout

    ms_result = invoke(
        workspace, "milestone", "add", "Milestone one", "--plan", "plan-0001"
    )
    assert ms_result.exit_code == 0
    assert "ms-0001" in ms_result.stdout

    slice_result = invoke(
        workspace, "slice", "add", "Slice one", "--milestone", "ms-0001"
    )
    assert slice_result.exit_code == 0
    assert "slice-0001" in slice_result.stdout

    ready_result = invoke(workspace, "slice", "ready", "slice-0001")
    assert ready_result.exit_code == 0

    lint_result = invoke(workspace, "plan", "lint", "plan-0001")
    assert lint_result.exit_code == 0
    assert "pass" in lint_result.stdout

    accept_result = invoke(
        workspace, "plan", "accept", "plan-0001", "--note", "Accepted"
    )
    assert accept_result.exit_code == 0

    slice_show = invoke(workspace, "--json", "slice", "show", "slice-0001")
    slice_payload = json.loads(slice_show.stdout)
    assert slice_payload["result"]["front_matter"]["status"] == "ready-for-execution"

    plan_show = invoke(workspace, "--json", "plan", "show", "plan-0001")
    plan_payload = json.loads(plan_show.stdout)
    assert plan_payload["result"]["front_matter"]["status"] == "accepted"
