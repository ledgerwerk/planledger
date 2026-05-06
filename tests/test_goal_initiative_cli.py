from __future__ import annotations

from pathlib import Path


def test_goal_and_initiative_flow(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace

    goal_result = invoke(workspace, "goal", "create", "Test goal")
    assert goal_result.exit_code == 0
    assert "goal-0001" in goal_result.stdout

    goal_path = (
        workspace / ".planledger" / "ledgers" / "main" / "goals" / "goal-0001.md"
    )
    assert goal_path.exists()

    initiative_result = invoke(
        workspace,
        "initiative",
        "create",
        "Test initiative",
        "--goal",
        "goal-0001",
    )
    assert initiative_result.exit_code == 0
    assert "init-0001" in initiative_result.stdout

    activate_result = invoke(workspace, "initiative", "activate", "init-0001")
    assert activate_result.exit_code == 0

    active_result = invoke(workspace, "initiative", "active")
    assert active_result.exit_code == 0
    assert "init-0001" in active_result.stdout

    list_result = invoke(workspace, "initiative", "list")
    assert "init-0001" in list_result.stdout

    show_result = invoke(workspace, "initiative", "show", "init-0001")
    assert "Test initiative" in show_result.stdout
