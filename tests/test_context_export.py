from __future__ import annotations

import json
from pathlib import Path

import pytest

from planledger.context import export_context
from planledger.storage import (
    allocate_id,
    create_record,
    initialize_project,
    set_active_initiative,
)


@pytest.fixture
def workspace(tmp_path: Path):
    ws = initialize_project(tmp_path, "Test Export")
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


def test_export_empty_workspace(workspace):
    result = export_context(workspace)
    assert result["kind"] == "planledger_context_export"
    assert result["schema"] == "planledger.context.v1"
    assert result["project"]["name"] == "Test Export"
    assert result["active"] == {}
    assert result["records"]["open_decisions"] == []
    assert result["records"]["rationales"] == []
    assert result["records"]["risks"] == []
    assert result["records"]["ready_slices"] == []
    assert result["records"]["bindings"] == []
    assert result["language"]["areas"] == []
    assert result["language"]["terms"] == []
    assert result["language"]["ambiguities"] == []
    assert "counts" in result
    assert "next_action" in result


def test_export_with_active_initiative(workspace):
    goal_id = _create_goal(workspace)
    init_id = _create_initiative(workspace, goal_id)

    result = export_context(workspace)
    assert result["active"]["initiative"]["id"] == init_id
    assert result["active"]["goal"]["id"] == goal_id


def test_export_with_plan(workspace):
    goal_id = _create_goal(workspace)
    init_id = _create_initiative(workspace, goal_id)

    plan_id = allocate_id(workspace, "plan")
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
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    create_record(workspace, "plan", plan_front, "# Plan\n\n## Context\n")

    result = export_context(workspace)
    assert result["active"]["latest_plan"]["id"] == plan_id


def test_export_with_open_decision(workspace):
    goal_id = _create_goal(workspace)
    init_id = _create_initiative(workspace, goal_id)

    dec_id = allocate_id(workspace, "decision")
    front = {
        "id": dec_id,
        "type": "decision",
        "initiative": init_id,
        "title": "Test decision",
        "status": "open",
        "chosen_option": None,
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "accepted_at": None,
    }
    create_record(workspace, "decision", front, "")

    result = export_context(workspace)
    assert len(result["records"]["open_decisions"]) == 1
    assert result["records"]["open_decisions"][0]["id"] == dec_id


def test_export_with_risk(workspace):
    goal_id = _create_goal(workspace)
    init_id = _create_initiative(workspace, goal_id)

    risk_id = allocate_id(workspace, "risk")
    front = {
        "id": risk_id,
        "type": "risk",
        "initiative": init_id,
        "title": "Test risk",
        "status": "open",
        "likelihood": "high",
        "impact": "high",
        "mitigation": "",
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    create_record(workspace, "risk", front, "")

    result = export_context(workspace)
    assert len(result["records"]["risks"]) == 1
    assert result["records"]["risks"][0]["id"] == risk_id


def test_export_include_bodies(workspace):
    goal_id = _create_goal(workspace)
    _create_initiative(workspace, goal_id)

    result = export_context(workspace, include_bodies=True)
    initiative = result["active"]["initiative"]
    assert "front_matter" in initiative


def test_export_with_events(workspace):
    from planledger.storage import append_event

    append_event(
        workspace,
        command="test",
        object_type="goal",
        object_id="goal-0001",
        event_type="created",
    )

    result = export_context(workspace, max_events=10)
    assert "recent_events" in result
    assert len(result["recent_events"]) == 1


def test_context_export_cli(workspace, runner):
    from typer.testing import CliRunner

    from planledger.cli import app

    r = CliRunner()
    result = r.invoke(
        app, ["--cwd", str(workspace.root), "--json", "context", "export"]
    )
    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["result"]["schema"] == "planledger.context.v1"
    assert "language" in data["result"]
