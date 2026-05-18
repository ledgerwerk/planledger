from __future__ import annotations

from pathlib import Path

import pytest

from planledger.storage import (
    allocate_id,
    create_record,
    initialize_project,
    list_records,
    set_active_initiative,
)


@pytest.fixture
def workspace_with_initiative(tmp_path: Path):
    ws = initialize_project(tmp_path, "ADR Test")
    goal_id = allocate_id(ws, "goal")
    create_record(
        ws,
        "goal",
        {
            "id": goal_id,
            "type": "goal",
            "title": "G",
            "status": "active",
            "horizon": "quarter",
            "priority": "high",
            "success_metrics": [],
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )
    init_id = allocate_id(ws, "initiative")
    create_record(
        ws,
        "initiative",
        {
            "id": init_id,
            "type": "initiative",
            "goal": goal_id,
            "title": "I",
            "status": "shaping",
            "owner": "human",
            "priority": "high",
            "active": True,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )
    set_active_initiative(ws, init_id)
    return ws, init_id


def test_adr_create(workspace_with_initiative):
    from typer.testing import CliRunner

    from planledger.cli import app

    ws, init_id = workspace_with_initiative
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(ws.root),
            "adr",
            "create",
            "Use PostgreSQL",
            "--initiative",
            init_id,
        ],
    )
    assert result.exit_code == 0, result.stdout

    decisions = list_records(ws, "decision")
    assert len(decisions) == 1
    dec = decisions[0]
    assert dec.front_matter.get("decision_type") == "rationale"
    assert dec.front_matter.get("title") == "Use PostgreSQL"
    assert dec.front_matter.get("status") == "open"
    assert dec.body.startswith("# Rationale")


def test_adr_list(workspace_with_initiative):
    from typer.testing import CliRunner

    from planledger.cli import app

    ws, init_id = workspace_with_initiative
    runner = CliRunner()
    runner.invoke(
        app,
        ["--cwd", str(ws.root), "adr", "create", "ADR1", "--initiative", init_id],
    )
    result = runner.invoke(
        app,
        ["--cwd", str(ws.root), "--json", "adr", "list", "--initiative", init_id],
    )
    assert result.exit_code == 0, result.stdout
    import json

    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert len(data["result"]["decisions"]) == 1


def test_adr_accept(workspace_with_initiative):
    from typer.testing import CliRunner

    from planledger.cli import app

    ws, init_id = workspace_with_initiative
    runner = CliRunner()
    runner.invoke(
        app,
        [
            "--cwd",
            str(ws.root),
            "adr",
            "create",
            "Use bundles",
            "--initiative",
            init_id,
        ],
    )

    decisions = list_records(ws, "decision")
    dec_id = decisions[0].record_id

    runner.invoke(
        app,
        [
            "--cwd",
            str(ws.root),
            "option",
            "add",
            "Option A",
            "--decision",
            dec_id,
        ],
    )
    runner.invoke(
        app,
        [
            "--cwd",
            str(ws.root),
            "option",
            "add",
            "Option B",
            "--decision",
            dec_id,
        ],
    )

    options = list_records(ws, "option")
    opt_a = [o for o in options if o.front_matter.get("title") == "Option A"][0]

    result = runner.invoke(
        app,
        [
            "--cwd",
            str(ws.root),
            "adr",
            "accept",
            dec_id,
            "--option",
            opt_a.record_id,
            "--rationale",
            "Better fit.",
        ],
    )
    assert result.exit_code == 0, result.stdout

    from planledger.storage import load_record

    dec = load_record(ws, "decision", dec_id)
    assert dec.front_matter.get("status") == "accepted"
    assert dec.front_matter.get("chosen_option") == opt_a.record_id


def test_adr_only_lists_rationale_records(workspace_with_initiative):
    from planledger.storage import allocate_id as alloc
    from planledger.storage import create_record as create

    ws, init_id = workspace_with_initiative

    # Create a non-rationale decision.
    dec_id = alloc(ws, "decision")
    create(
        ws,
        "decision",
        {
            "id": dec_id,
            "type": "decision",
            "initiative": init_id,
            "title": "Non-ADR decision",
            "status": "open",
            "chosen_option": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "accepted_at": None,
        },
        "",
    )

    from typer.testing import CliRunner

    from planledger.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["--cwd", str(ws.root), "--json", "adr", "list"],
    )
    assert result.exit_code == 0, result.stdout
    import json

    data = json.loads(result.stdout)
    assert len(data["result"]["decisions"]) == 0


def test_adr_list_includes_legacy_architecture_records(workspace_with_initiative):
    from planledger.storage import allocate_id as alloc
    from planledger.storage import create_record as create

    ws, init_id = workspace_with_initiative
    dec_id = alloc(ws, "decision")
    create(
        ws,
        "decision",
        {
            "id": dec_id,
            "type": "decision",
            "initiative": init_id,
            "title": "Legacy architecture record",
            "decision_type": "architecture",
            "status": "open",
            "chosen_option": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "accepted_at": None,
        },
        "",
    )

    from typer.testing import CliRunner

    from planledger.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--cwd", str(ws.root), "--json", "adr", "list"])
    assert result.exit_code == 0, result.stdout

    import json

    data = json.loads(result.stdout)
    assert [item["id"] for item in data["result"]["decisions"]] == [dec_id]
