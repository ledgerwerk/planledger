from __future__ import annotations

import json
from pathlib import Path


def _seed_until_ready_slice(invoke, workspace: Path) -> None:
    invoke(workspace, "goal", "create", "Goal")
    invoke(workspace, "initiative", "create", "Init", "--goal", "goal-0001")
    invoke(workspace, "initiative", "activate", "init-0001")
    invoke(workspace, "plan", "draft", "--initiative", "init-0001")
    invoke(workspace, "milestone", "add", "Milestone", "--plan", "plan-0001")
    invoke(workspace, "slice", "add", "Slice", "--milestone", "ms-0001")
    invoke(workspace, "slice", "ready", "slice-0001")
    invoke(workspace, "plan", "accept", "plan-0001", "--note", "Ready")


def test_next_action_returns_concrete_command(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    result = invoke(workspace, "next-action")
    assert result.exit_code == 0
    assert "planledger" in result.stdout


def test_next_action_json_kind(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    _seed_until_ready_slice(invoke, workspace)

    result = invoke(workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["result"]["kind"] == "planledger_next_action"
    assert payload["result"]["next_command"].startswith("planledger")
