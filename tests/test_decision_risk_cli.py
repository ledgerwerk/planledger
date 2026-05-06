from __future__ import annotations

import json
from pathlib import Path


def _setup(invoke, workspace: Path) -> None:
    invoke(workspace, "goal", "create", "Test goal")
    invoke(workspace, "initiative", "create", "Test initiative", "--goal", "goal-0001")
    invoke(workspace, "initiative", "activate", "init-0001")


def test_decision_option_and_risk(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    _setup(invoke, workspace)

    create = invoke(
        workspace, "decision", "create", "Choose approach", "--initiative", "init-0001"
    )
    assert create.exit_code == 0

    add_a = invoke(workspace, "option", "add", "Option A", "--decision", "dec-0001")
    add_b = invoke(workspace, "option", "add", "Option B", "--decision", "dec-0001")
    assert add_a.exit_code == 0
    assert add_b.exit_code == 0

    compare = invoke(workspace, "option", "compare", "dec-0001")
    assert compare.exit_code == 0
    assert "opt-0001" in compare.stdout

    accept = invoke(
        workspace,
        "decision",
        "accept",
        "dec-0001",
        "--option",
        "opt-0001",
        "--rationale",
        "Best fit",
    )
    assert accept.exit_code == 0

    show = invoke(workspace, "--json", "decision", "show", "dec-0001")
    payload = json.loads(show.stdout)
    assert payload["result"]["front_matter"]["status"] == "accepted"
    assert payload["result"]["front_matter"]["chosen_option"] == "opt-0001"

    risk_add = invoke(
        workspace, "risk", "add", "Potential drift", "--initiative", "init-0001"
    )
    assert risk_add.exit_code == 0
    risk_list = invoke(workspace, "risk", "list", "--open")
    assert "risk-0001" in risk_list.stdout
