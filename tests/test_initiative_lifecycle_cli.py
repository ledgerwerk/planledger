from __future__ import annotations

from pathlib import Path

from planledger.storage import active_initiative, load_record, load_workspace_from_root


def _setup_goal_and_initiative(invoke, workspace: Path) -> None:
    assert invoke(workspace, "goal", "create", "Goal").exit_code == 0
    assert (
        invoke(workspace, "initiative", "create", "Init", "--goal", "goal-0001").exit_code
        == 0
    )


def test_cannot_activate_initiative_whose_parent_goal_is_cancelled(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    _setup_goal_and_initiative(invoke, workspace)
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
    result = invoke(workspace, "initiative", "activate", "init-0001")
    assert result.exit_code != 0
    assert "Cannot activate initiative init-0001" in result.stdout


def test_cancelling_goal_cascades_child_initiatives(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    _setup_goal_and_initiative(invoke, workspace)
    assert invoke(workspace, "initiative", "activate", "init-0001").exit_code == 0
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
    initiative = load_record(ws, "initiative", "init-0001")
    assert initiative.front_matter["status"] == "cancelled"
    assert active_initiative(ws) is None


def test_initiative_complete_sets_terminal_metadata(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    _setup_goal_and_initiative(invoke, workspace)
    result = invoke(
        workspace,
        "initiative",
        "complete",
        "init-0001",
        "--reason",
        "Delivered the intended outcome.",
    )
    assert result.exit_code == 0, result.stdout
    ws = load_workspace_from_root(workspace)
    initiative = load_record(ws, "initiative", "init-0001")
    assert initiative.front_matter["status"] == "fulfilled"
    assert initiative.front_matter["close_reason"] == "Delivered the intended outcome."
    assert initiative.front_matter.get("closed_at")
