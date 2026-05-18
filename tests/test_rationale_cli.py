from __future__ import annotations

import json
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
    ws = initialize_project(tmp_path, "Rationale Test")
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


def test_rationale_create_requires_all_gate_flags(workspace_with_initiative):
    from typer.testing import CliRunner

    from planledger.cli import app

    ws, init_id = workspace_with_initiative
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(ws.root),
            "--json",
            "rationale",
            "create",
            "Use events",
            "--initiative",
            init_id,
            "--hard-to-reverse",
            "--real-tradeoff",
        ],
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["kind"] == "invalid_rationale_gate"
    assert payload["error"]["remediation"]


def test_rationale_create_writes_rationale_record(workspace_with_initiative):
    from typer.testing import CliRunner

    from planledger.cli import app

    ws, init_id = workspace_with_initiative
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(ws.root),
            "rationale",
            "create",
            "Use events",
            "--initiative",
            init_id,
            "--summary",
            "Events keep downstream failures from blocking order placement.",
            "--hard-to-reverse",
            "--surprising-without-context",
            "--real-tradeoff",
        ],
    )
    assert result.exit_code == 0, result.stdout

    decisions = list_records(ws, "decision")
    assert len(decisions) == 1
    record = decisions[0]
    assert record.front_matter["decision_type"] == "rationale"
    assert record.front_matter["rationale_gate"] == {
        "hard_to_reverse": True,
        "surprising_without_context": True,
        "real_tradeoff": True,
    }
    assert "Events keep downstream failures" in record.body


def test_rationale_list_excludes_ordinary_decisions(workspace_with_initiative):
    from typer.testing import CliRunner

    from planledger.cli import app

    ws, init_id = workspace_with_initiative
    create_record(
        ws,
        "decision",
        {
            "id": allocate_id(ws, "decision"),
            "type": "decision",
            "initiative": init_id,
            "title": "Legacy architecture",
            "decision_type": "architecture",
            "status": "open",
            "chosen_option": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "accepted_at": None,
        },
        "",
    )
    create_record(
        ws,
        "decision",
        {
            "id": allocate_id(ws, "decision"),
            "type": "decision",
            "initiative": init_id,
            "title": "Current rationale",
            "decision_type": "rationale",
            "status": "open",
            "chosen_option": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "accepted_at": None,
            "rationale_gate": {
                "hard_to_reverse": True,
                "surprising_without_context": True,
                "real_tradeoff": True,
            },
        },
        "",
    )
    create_record(
        ws,
        "decision",
        {
            "id": allocate_id(ws, "decision"),
            "type": "decision",
            "initiative": init_id,
            "title": "Ordinary decision",
            "status": "open",
            "chosen_option": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "accepted_at": None,
        },
        "",
    )

    runner = CliRunner()
    result = runner.invoke(
        app, ["--cwd", str(ws.root), "--json", "rationale", "list", "--initiative", init_id]
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    titles = [item["title"] for item in payload["result"]["decisions"]]
    assert titles == ["Legacy architecture", "Current rationale"]


def test_adr_create_alias_still_works(workspace_with_initiative):
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
            "Legacy alias",
            "--initiative",
            init_id,
        ],
    )
    assert result.exit_code == 0, result.stdout
    decision = list_records(ws, "decision")[0]
    assert decision.front_matter["decision_type"] == "rationale"
