from __future__ import annotations

from pathlib import Path

from planledger.storage import (
    allocate_id,
    create_record,
    ensure_default_language_area,
    initialize_project,
    is_rationale_decision,
    list_rationale_records,
    load_workspace_from_root,
)


def test_initialize_project_creates_extension_directories(tmp_path: Path) -> None:
    ws = initialize_project(tmp_path, "Extended Storage")

    assert (ws.ledger_dir / "language_areas").exists()
    assert (ws.ledger_dir / "language_terms").exists()
    assert (ws.ledger_dir / "language_ambiguities").exists()
    assert (ws.ledger_dir / "challenge_sessions").exists()

    reloaded = load_workspace_from_root(tmp_path)
    assert allocate_id(reloaded, "language_area").startswith("area-")
    assert allocate_id(reloaded, "language_term").startswith("term-")
    assert allocate_id(reloaded, "language_ambiguity").startswith("amb-")
    assert allocate_id(reloaded, "challenge_session").startswith("challenge-")


def test_ensure_default_language_area_is_idempotent(tmp_path: Path) -> None:
    ws = initialize_project(tmp_path, "Language Defaults")

    first = ensure_default_language_area(ws)
    second = ensure_default_language_area(ws)

    assert first.record_id == second.record_id
    assert first.front_matter["is_default"] is True
    assert first.front_matter["title"] == "Project"


def test_rationale_helpers_include_legacy_architecture_decisions(tmp_path: Path) -> None:
    ws = initialize_project(tmp_path, "Rationale Helpers")
    initiative_id = allocate_id(ws, "initiative")
    create_record(
        ws,
        "initiative",
        {
            "id": initiative_id,
            "type": "initiative",
            "goal": None,
            "title": "I",
            "status": "shaping",
            "owner": "agent",
            "priority": "high",
            "active": False,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )

    architecture_id = allocate_id(ws, "decision")
    create_record(
        ws,
        "decision",
        {
            "id": architecture_id,
            "type": "decision",
            "initiative": initiative_id,
            "title": "Legacy ADR",
            "decision_type": "architecture",
            "status": "open",
            "chosen_option": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "accepted_at": None,
        },
        "",
    )
    rationale_id = allocate_id(ws, "decision")
    create_record(
        ws,
        "decision",
        {
            "id": rationale_id,
            "type": "decision",
            "initiative": initiative_id,
            "title": "New rationale",
            "decision_type": "rationale",
            "status": "open",
            "chosen_option": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "accepted_at": None,
        },
        "",
    )
    ordinary_id = allocate_id(ws, "decision")
    create_record(
        ws,
        "decision",
        {
            "id": ordinary_id,
            "type": "decision",
            "initiative": initiative_id,
            "title": "Ordinary decision",
            "status": "open",
            "chosen_option": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "accepted_at": None,
        },
        "",
    )

    listed = list_rationale_records(ws, initiative=initiative_id)
    ids = {record.record_id for record in listed}

    assert listed
    assert all(is_rationale_decision(record) for record in listed)
    assert ids == {architecture_id, rationale_id}
