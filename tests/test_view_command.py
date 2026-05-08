from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planledger.cli import app
from planledger.storage import (
    allocate_id,
    create_record,
    initialize_project,
    set_active_initiative,
)


@pytest.fixture
def workspace(tmp_path: Path):
    ws = initialize_project(tmp_path, "Test View")
    return ws


def _create_goal(ws) -> str:
    goal_id = allocate_id(ws, "goal")
    front = {
        "id": goal_id,
        "type": "goal",
        "title": "Test goal",
        "status": "active",
        "horizon": "quarter",
        "priority": "high",
        "success_metrics": [],
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    create_record(ws, "goal", front, "")
    return goal_id


def _create_initiative(ws, goal_id: str) -> str:
    init_id = allocate_id(ws, "initiative")
    front = {
        "id": init_id,
        "type": "initiative",
        "goal": goal_id,
        "title": "Test initiative",
        "status": "shaping",
        "owner": "human",
        "priority": "high",
        "active": True,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    create_record(ws, "initiative", front, "")
    set_active_initiative(ws, init_id)
    return init_id


def _create_plan(ws, init_id: str) -> str:
    plan_id = allocate_id(ws, "plan")
    front = {
        "id": plan_id,
        "type": "plan",
        "initiative": init_id,
        "version": 1,
        "status": "accepted",
        "supersedes": None,
        "accepted_at": "2025-01-01T00:00:00Z",
        "accepted_by": "human",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    create_record(ws, "plan", front, "# Plan\n\n## Context\n")
    return plan_id


def _create_milestone(ws, plan_id: str, status: str = "planned") -> str:
    ms_id = allocate_id(ws, "milestone")
    front = {
        "id": ms_id,
        "type": "milestone",
        "plan": plan_id,
        "title": "Test milestone",
        "status": status,
        "order": 10,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    create_record(ws, "milestone", front, "")
    return ms_id


def _create_slice(ws, plan_id: str, milestone_id: str, status: str = "shaping") -> str:
    slice_id = allocate_id(ws, "slice")
    front = {
        "id": slice_id,
        "type": "slice",
        "plan": plan_id,
        "milestone": milestone_id,
        "title": "Test slice",
        "status": status,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    create_record(ws, "slice", front, "")
    return slice_id


def _create_decision(ws, init_id: str, status: str = "open") -> str:
    dec_id = allocate_id(ws, "decision")
    front = {
        "id": dec_id,
        "type": "decision",
        "initiative": init_id,
        "title": "Test decision",
        "status": status,
        "chosen_option": None,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "accepted_at": None,
    }
    create_record(ws, "decision", front, "")
    return dec_id


def _create_risk(ws, init_id: str, status: str = "open") -> str:
    risk_id = allocate_id(ws, "risk")
    front = {
        "id": risk_id,
        "type": "risk",
        "initiative": init_id,
        "title": "Test risk",
        "status": status,
        "likelihood": "high",
        "impact": "high",
        "mitigation": "",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    create_record(ws, "risk", front, "")
    return risk_id


def _run_view(workspace, *extra_args: str):
    runner = CliRunner()
    args = ["--cwd", str(workspace.root), "view", *extra_args]
    return runner.invoke(app, args)


def _run_view_json(workspace):
    runner = CliRunner()
    args = ["--cwd", str(workspace.root), "--json", "view"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def test_view_empty_workspace(workspace):
    result = _run_view(workspace)
    assert result.exit_code == 0, result.stdout
    assert "Project: Test View" in result.stdout
    assert "Active initiative: none" in result.stdout
    assert "Plan: none" in result.stdout
    assert "Next action:" in result.stdout


def test_view_empty_workspace_json(workspace):
    data = _run_view_json(workspace)
    assert data["ok"] is True
    assert data["result"]["kind"] == "planledger_view"
    assert data["result"]["project"]["name"] == "Test View"
    assert data["result"]["active_initiative"] is None
    assert data["result"]["goal"] is None
    assert data["result"]["initiative"] is None
    assert data["result"]["plan"] is None
    assert data["result"]["open_decisions"] == []
    assert data["result"]["open_risks"] == []


def test_view_with_active_initiative(workspace):
    goal_id = _create_goal(workspace)
    init_id = _create_initiative(workspace, goal_id)

    result = _run_view(workspace)
    assert result.exit_code == 0, result.stdout
    assert f"Active initiative: {init_id}" in result.stdout
    assert f"Goal: {goal_id}" in result.stdout


def test_view_with_plan_milestones_slices(workspace):
    goal_id = _create_goal(workspace)
    init_id = _create_initiative(workspace, goal_id)
    plan_id = _create_plan(workspace, init_id)
    ms_id = _create_milestone(workspace, plan_id)
    slice_id = _create_slice(workspace, plan_id, ms_id, status="ready-for-execution")

    result = _run_view(workspace)
    assert result.exit_code == 0, result.stdout
    assert f"Plan: {plan_id}" in result.stdout
    assert "ms_id" not in result.stdout  # should show the actual id
    assert ms_id in result.stdout
    assert slice_id in result.stdout


def test_view_with_plan_milestones_slices_json(workspace):
    goal_id = _create_goal(workspace)
    init_id = _create_initiative(workspace, goal_id)
    plan_id = _create_plan(workspace, init_id)
    ms_id = _create_milestone(workspace, plan_id)
    slice_id = _create_slice(workspace, plan_id, ms_id, status="ready-for-execution")

    data = _run_view_json(workspace)
    plan = data["result"]["plan"]
    assert plan is not None
    assert plan["id"] == plan_id
    assert plan["version"] == 1
    assert plan["status"] == "accepted"
    assert len(plan["milestones"]) == 1
    assert plan["milestones"][0]["id"] == ms_id
    assert len(plan["slices"]) == 1
    assert plan["slices"][0]["id"] == slice_id
    assert plan["slices"][0]["status"] == "ready-for-execution"


def test_view_with_decisions(workspace):
    goal_id = _create_goal(workspace)
    init_id = _create_initiative(workspace, goal_id)
    dec_id = _create_decision(workspace, init_id, status="open")

    result = _run_view(workspace)
    assert result.exit_code == 0, result.stdout
    assert "Open decisions (1):" in result.stdout
    assert dec_id in result.stdout


def test_view_with_risks(workspace):
    goal_id = _create_goal(workspace)
    init_id = _create_initiative(workspace, goal_id)
    risk_id = _create_risk(workspace, init_id, status="open")

    result = _run_view(workspace)
    assert result.exit_code == 0, result.stdout
    assert "Open risks (1):" in result.stdout
    assert risk_id in result.stdout
    assert "impact: high" in result.stdout


def test_view_with_risks_json(workspace):
    goal_id = _create_goal(workspace)
    init_id = _create_initiative(workspace, goal_id)
    risk_id = _create_risk(workspace, init_id, status="open")

    data = _run_view_json(workspace)
    risks = data["result"]["open_risks"]
    assert len(risks) == 1
    assert risks[0]["id"] == risk_id
    assert risks[0]["impact"] == "high"


def test_view_next_action_shown(workspace):
    result = _run_view(workspace)
    assert result.exit_code == 0, result.stdout
    assert "Next action:" in result.stdout
