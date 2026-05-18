from __future__ import annotations

from pathlib import Path

import pytest

from planledger.bundle import apply_bundle, load_bundle
from planledger.storage import (
    allocate_id,
    create_record,
    initialize_project,
    list_records,
    load_record,
    save_record,
    set_active_initiative,
)
from planledger.taskledger import generate_plan_template, push_plan

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "harness_bundle_v1.json"


@pytest.fixture
def workspace_with_bundle(tmp_path: Path):
    ws = initialize_project(tmp_path, "Push Plan Test")
    bundle = load_bundle(FIXTURE)
    apply_bundle(ws, bundle)
    return ws


def test_push_plan_dry_run(workspace_with_bundle):
    ws = workspace_with_bundle
    plans = list_records(ws, "plan")
    plan_id = plans[0].record_id

    result = push_plan(ws, plan_id, dry_run=True)
    assert result["dry_run"] is True
    assert result["ready_slice_count"] == 1
    assert result["requested_create_tasks"] is False
    assert result["handoff_complete"] is False
    assert len(result["created"]) == 1
    assert result["created"][0]["slice"] is not None
    assert "description_preview" in result["created"][0]


def test_push_plan_dry_run_includes_rich_description(workspace_with_bundle):
    ws = workspace_with_bundle
    plans = list_records(ws, "plan")
    plan_id = plans[0].record_id

    result = push_plan(ws, plan_id, dry_run=True)
    preview = result["created"][0].get("description_preview", "")
    assert "Objective" in preview or "objective" in preview.lower()


def test_push_plan_no_create_tasks_skips(workspace_with_bundle):
    ws = workspace_with_bundle
    plans = list_records(ws, "plan")
    plan_id = plans[0].record_id

    result = push_plan(ws, plan_id, create_tasks=False)
    assert result["handoff_complete"] is False
    assert result["requested_create_tasks"] is False
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == "create_tasks_not_set"


def test_push_plan_no_ready_slices(tmp_path: Path):
    ws = initialize_project(tmp_path, "Empty Push")
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
    plan_id = allocate_id(ws, "plan")
    create_record(
        ws,
        "plan",
        {
            "id": plan_id,
            "type": "plan",
            "goal": goal_id,
            "initiative": init_id,
            "version": 1,
            "status": "draft",
            "supersedes": None,
            "accepted_at": None,
            "accepted_by": None,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "# Plan\n\n## Context\n",
    )

    result = push_plan(ws, plan_id, create_tasks=True)
    assert result["ready_slice_count"] == 0
    assert result["requested_create_tasks"] is True
    assert result["handoff_complete"] is False
    assert len(result["created"]) == 0
    assert len(result["skipped"]) == 0
    assert result["warnings"] == [
        "No taskledger tasks were created; no ready slices were found."
    ]


def test_generate_plan_template_uses_slice_fields(workspace_with_bundle):
    ws = workspace_with_bundle
    output = ws.root / "task-plan.md"
    result = generate_plan_template(ws, "slice-0001", output)
    assert result["output"] == str(output)
    text = output.read_text(encoding="utf-8")
    assert "# Taskledger plan for Add context export command" in text
    assert "## Objective" in text
    assert "Provide stable JSON context for harnesses." in text
    assert "## Target files" in text
    assert "planledger/context.py" in text
    assert "## Validation hints" in text
    assert "python -m pytest tests/test_context_export.py -q" in text


def test_push_plan_blocks_when_required_challenge_is_incomplete(workspace_with_bundle):
    ws = workspace_with_bundle
    plan = list_records(ws, "plan")[0]
    plan.front_matter["planning_mode"] = "full"
    plan.front_matter["requires_challenge"] = True
    plan.front_matter["challenge_status"] = "active"
    save_record(plan)

    with pytest.raises(Exception, match="challenge_incomplete"):
        push_plan(ws, plan.record_id, dry_run=True)

    refreshed = load_record(ws, "plan", plan.record_id)
    refreshed.front_matter["challenge_status"] = "completed"
    save_record(refreshed)
    result = push_plan(ws, plan.record_id, dry_run=True)
    assert result["dry_run"] is True
