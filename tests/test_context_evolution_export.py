from __future__ import annotations

from pathlib import Path

import pytest

from planledger.context import export_context
from planledger.storage import create_record, initialize_project


@pytest.fixture
def workspace(tmp_path: Path):
    return initialize_project(tmp_path, "Context Evolution")


def _create_goal(ws, goal_id: str, title: str, status: str, **extra):
    front = {
        "id": goal_id,
        "type": "goal",
        "title": title,
        "status": status,
        "horizon": "quarter",
        "priority": "high",
        "success_metrics": [],
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }
    front.update(extra)
    return create_record(ws, "goal", front, "")


def test_active_and_exploring_goals_are_exported(workspace):
    _create_goal(workspace, "goal-0001", "Active goal", "active")
    _create_goal(workspace, "goal-0002", "Exploring goal", "exploring")
    result = export_context(workspace)
    assert [item["id"] for item in result["current"]["active_goals"]] == ["goal-0001"]
    assert [item["id"] for item in result["current"]["exploring_goals"]] == ["goal-0002"]


def test_closed_goals_questions_and_assumptions_are_exported(workspace):
    _create_goal(
        workspace,
        "goal-0001",
        "Cancelled goal",
        "cancelled",
        closed_at="2025-01-02T00:00:00Z",
        close_reason="Feature A removed the need for feature B.",
    )
    create_record(
        workspace,
        "question",
        {
            "id": "q-0001",
            "type": "question",
            "scope_kind": "goal",
            "scope_id": "goal-0001",
            "title": "What changed?",
            "status": "open",
            "priority": "high",
            "answer": None,
            "answered_at": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )
    create_record(
        workspace,
        "assumption",
        {
            "id": "asm-0001",
            "type": "assumption",
            "scope_kind": "goal",
            "scope_id": "goal-0001",
            "title": "The old goal is obsolete.",
            "status": "unverified",
            "confidence": "medium",
            "evidence": [],
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )
    result = export_context(workspace)
    assert result["records"]["recently_closed_goals"][0]["id"] == "goal-0001"
    assert (
        result["records"]["recently_closed_goals"][0]["front_matter"]["close_reason"]
        == "Feature A removed the need for feature B."
    )
    assert [item["id"] for item in result["questions"]["open"]] == ["q-0001"]
    assert [item["id"] for item in result["assumptions"]["unverified"]] == [
        "asm-0001"
    ]


def test_ready_slice_under_cancelled_goal_is_blocked_from_handoff(workspace):
    _create_goal(
        workspace,
        "goal-0001",
        "Cancelled goal",
        "cancelled",
        closed_at="2025-01-02T00:00:00Z",
        close_reason="No longer useful.",
    )
    create_record(
        workspace,
        "initiative",
        {
            "id": "init-0001",
            "type": "initiative",
            "goal": "goal-0001",
            "title": "Init",
            "status": "cancelled",
            "owner": "human",
            "priority": "high",
            "active": False,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "closed_at": "2025-01-02T00:00:00Z",
            "close_reason": "Goal was cancelled.",
        },
        "",
    )
    create_record(
        workspace,
        "plan",
        {
            "id": "plan-0001",
            "type": "plan",
            "goal": "goal-0001",
            "initiative": "init-0001",
            "version": 1,
            "status": "accepted",
            "supersedes": None,
            "accepted_at": "2025-01-01T00:00:00Z",
            "accepted_by": "human",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "# Plan\n",
    )
    create_record(
        workspace,
        "slice",
        {
            "id": "slice-0001",
            "type": "slice",
            "initiative": "init-0001",
            "plan": "plan-0001",
            "milestone": "ms-0001",
            "title": "Blocked slice",
            "status": "ready-for-execution",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )
    result = export_context(workspace)
    assert result["handoff"]["ready_for_taskledger"] == []
    assert result["handoff"]["blocked_from_taskledger"][0]["id"] == "slice-0001"
    assert "parent goal goal-0001 is cancelled" in result["handoff"][
        "blocked_from_taskledger"
    ][0]["blocked_reason"]
