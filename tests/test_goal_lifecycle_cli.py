from __future__ import annotations

from pathlib import Path

import pytest

from planledger.errors import PlanledgerError
from planledger.lifecycle import (
    is_terminal,
    link_records,
    require_not_terminal,
    transition_record,
)
from planledger.storage import (
    create_record,
    initialize_project,
    list_events,
    load_record,
    load_workspace_from_root,
)


def _goal_front(goal_id: str, *, status: str = "active") -> dict[str, object]:
    return {
        "id": goal_id,
        "type": "goal",
        "title": "Test goal",
        "status": status,
        "horizon": "quarter",
        "priority": "high",
        "success_metrics": [],
        "created_at": "2025-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
    }


def test_is_terminal_uses_kind_specific_status_sets() -> None:
    assert is_terminal("goal", "fulfilled") is True
    assert is_terminal("goal", "active") is False
    assert is_terminal("plan", "retired") is True
    assert is_terminal("slice", "validated") is True
    assert is_terminal("slice", "ready-for-execution") is False


def test_transition_record_sets_terminal_goal_fields_and_event(tmp_path: Path) -> None:
    workspace = initialize_project(tmp_path, "Goal lifecycle")
    record = create_record(workspace, "goal", _goal_front("goal-0001"), "")

    event = transition_record(
        workspace,
        record,
        new_status="cancelled",
        command='planledger goal cancel goal-0001 --reason "No longer useful."',
        reason="No longer useful.",
    )

    reloaded = load_record(workspace, "goal", "goal-0001")
    assert reloaded.front_matter["status"] == "cancelled"
    assert reloaded.front_matter["closed_by"] == "human"
    assert reloaded.front_matter["close_reason"] == "No longer useful."
    assert reloaded.front_matter.get("closed_at")
    assert event["event_type"] == "status_changed"
    assert event["before"] == {"status": "active"}
    assert event["after"]["status"] == "cancelled"
    assert event["after"]["reason"] == "No longer useful."
    stored_events = list_events(workspace)
    assert stored_events[-1]["object_id"] == "goal-0001"


def test_link_records_updates_relation_and_emits_event(tmp_path: Path) -> None:
    workspace = initialize_project(tmp_path, "Goal relations")
    record = create_record(workspace, "goal", _goal_front("goal-0001"), "")

    event = link_records(
        workspace,
        record,
        "invalidated_by",
        "goal-0002",
        command="planledger goal cancel goal-0001 --because-goal goal-0002",
    )

    reloaded = load_record(workspace, "goal", "goal-0001")
    assert reloaded.front_matter["invalidated_by"] == ["goal-0002"]
    assert event["event_type"] == "linked"
    assert event["after"] == {"relation": "invalidated_by", "target_id": "goal-0002"}


def test_require_not_terminal_rejects_terminal_goal(tmp_path: Path) -> None:
    workspace = initialize_project(tmp_path, "Terminal guard")
    record = create_record(
        workspace,
        "goal",
        _goal_front("goal-0001", status="fulfilled"),
        "",
    )

    with pytest.raises(PlanledgerError, match="Cannot revise goal goal-0001"):
        require_not_terminal(record, "revise")


def test_goal_create_supports_exploring_status(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    result = invoke(
        workspace,
        "goal",
        "create",
        "Improve planning",
        "--status",
        "exploring",
        "--priority",
        "medium",
        "--horizon",
        "month",
    )
    assert result.exit_code == 0, result.stdout
    ws = load_workspace_from_root(workspace)
    goal = load_record(ws, "goal", "goal-0001")
    assert goal.front_matter["status"] == "exploring"
    assert goal.front_matter["priority"] == "medium"
    assert goal.front_matter["horizon"] == "month"


def test_goal_activate_moves_exploring_to_active(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    assert (
        invoke(workspace, "goal", "create", "Improve planning", "--status", "exploring").exit_code
        == 0
    )
    result = invoke(
        workspace,
        "goal",
        "activate",
        "goal-0001",
        "--reason",
        "Goal is now clear enough to plan.",
    )
    assert result.exit_code == 0, result.stdout
    ws = load_workspace_from_root(workspace)
    goal = load_record(ws, "goal", "goal-0001")
    assert goal.front_matter["status"] == "active"
    assert list_events(ws)[-1]["after"]["reason"] == "Goal is now clear enough to plan."


def test_goal_complete_and_cancel_record_terminal_metadata(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    assert invoke(workspace, "goal", "create", "Feature A").exit_code == 0
    assert invoke(workspace, "goal", "create", "Feature B").exit_code == 0
    assert (
        invoke(
            workspace,
            "goal",
            "complete",
            "goal-0001",
            "--reason",
            "Feature A implemented and validated.",
            "--evidence",
            "taskledger:task-0007",
        ).exit_code
        == 0
    )
    assert (
        invoke(
            workspace,
            "goal",
            "cancel",
            "goal-0002",
            "--reason",
            "Feature A removed the need for feature B.",
            "--because-goal",
            "goal-0001",
        ).exit_code
        == 0
    )
    ws = load_workspace_from_root(workspace)
    completed = load_record(ws, "goal", "goal-0001")
    cancelled = load_record(ws, "goal", "goal-0002")
    assert completed.front_matter["status"] == "fulfilled"
    assert completed.front_matter.get("closed_at")
    assert cancelled.front_matter["status"] == "cancelled"
    assert cancelled.front_matter["close_reason"] == (
        "Feature A removed the need for feature B."
    )
    assert "goal-0001" in cancelled.front_matter["invalidated_by"]


def test_goal_supersede_creates_linked_replacement(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    assert invoke(workspace, "goal", "create", "Original goal").exit_code == 0
    result = invoke(
        workspace,
        "goal",
        "supersede",
        "goal-0001",
        "--new-title",
        "Replacement goal",
        "--reason",
        "The goal became more precise.",
    )
    assert result.exit_code == 0, result.stdout
    ws = load_workspace_from_root(workspace)
    old_goal = load_record(ws, "goal", "goal-0001")
    new_goal = load_record(ws, "goal", "goal-0002")
    assert old_goal.front_matter["status"] == "superseded"
    assert old_goal.front_matter["superseded_by"] == "goal-0002"
    assert new_goal.front_matter["status"] == "active"
    assert new_goal.front_matter["supersedes"] == ["goal-0001"]


def test_goal_list_closed_filters_terminal_goals(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    assert invoke(workspace, "goal", "create", "Feature A").exit_code == 0
    assert invoke(workspace, "goal", "create", "Feature B").exit_code == 0
    assert (
        invoke(
            workspace,
            "goal",
            "complete",
            "goal-0001",
            "--reason",
            "Feature A implemented and validated.",
        ).exit_code
        == 0
    )
    assert (
        invoke(
            workspace,
            "goal",
            "cancel",
            "goal-0002",
            "--reason",
            "Feature A removed the need for feature B.",
        ).exit_code
        == 0
    )
    result = invoke(workspace, "goal", "list", "--closed")
    assert result.exit_code == 0, result.stdout
    assert "goal-0001" in result.stdout
    assert "goal-0002" in result.stdout
