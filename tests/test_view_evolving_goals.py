from __future__ import annotations

import json
from pathlib import Path

from planledger.storage import create_record, initialize_project


def _seed_dashboard(workspace: Path) -> None:
    ws = initialize_project(workspace, "View Evolution")
    create_record(
        ws,
        "goal",
        {
            "id": "goal-0001",
            "type": "goal",
            "title": "Fulfilled goal",
            "status": "fulfilled",
            "horizon": "quarter",
            "priority": "high",
            "success_metrics": [],
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-02T00:00:00Z",
            "closed_at": "2025-01-02T00:00:00Z",
            "close_reason": "Implemented and validated.",
        },
        "",
    )
    create_record(
        ws,
        "goal",
        {
            "id": "goal-0002",
            "type": "goal",
            "title": "Exploring goal",
            "status": "exploring",
            "horizon": "quarter",
            "priority": "medium",
            "success_metrics": [],
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )
    create_record(
        ws,
        "question",
        {
            "id": "q-0001",
            "type": "question",
            "scope_kind": "goal",
            "scope_id": "goal-0002",
            "title": "What exactly should be reshaped?",
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
        ws,
        "assumption",
        {
            "id": "asm-0001",
            "type": "assumption",
            "scope_kind": "goal",
            "scope_id": "goal-0002",
            "title": "Planning memory is the bigger problem.",
            "status": "unverified",
            "confidence": "medium",
            "evidence": [],
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )


def test_view_displays_evolving_goal_sections(invoke, tmp_path: Path) -> None:
    _seed_dashboard(tmp_path)
    result = invoke(tmp_path, "view")
    assert result.exit_code == 0, result.stdout
    assert "Goals:" in result.stdout
    assert "Exploring (1)" in result.stdout
    assert "Recently closed (1)" in result.stdout
    assert "Implemented and validated." in result.stdout
    assert "Open questions (1):" in result.stdout


def test_view_json_includes_structured_lifecycle_sections(invoke, tmp_path: Path) -> None:
    _seed_dashboard(tmp_path)
    result = invoke(tmp_path, "--json", "view")
    payload = json.loads(result.stdout)
    assert result.exit_code == 0, result.stdout
    assert payload["result"]["goals"]["exploring"][0]["id"] == "goal-0002"
    assert payload["result"]["goals"]["closed_recent"][0]["id"] == "goal-0001"
    assert payload["result"]["questions"]["open"][0]["id"] == "q-0001"
    assert payload["result"]["assumptions"]["unverified"][0]["id"] == "asm-0001"
