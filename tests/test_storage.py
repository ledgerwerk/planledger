from __future__ import annotations

from pathlib import Path

from planledger.storage import (
    create_plan,
    initialize_project,
    list_plans,
    load_component_content,
    load_plan,
    plan_status_counts,
    validate_plan,
)


def test_storage_creates_loads_and_lists_independent_plans(tmp_path: Path) -> None:
    workspace = initialize_project(tmp_path, "Test Project")

    first = create_plan(workspace, "First plan", "Please plan feature A.")
    second = create_plan(
        workspace,
        "Second plan",
        "Please plan feature B.",
        status="in_progress",
        components={
            "summary": "A concise summary.",
            "context": "Repository context.",
            "approach": "Recommended approach.",
            "todo_items": "1. Do the work.",
            "validation": "Run pytest.",
        },
    )

    assert first.plan_id == "plan-0001"
    assert second.plan_id == "plan-0002"
    assert load_plan(workspace, "plan-0002").title == "Second plan"
    assert load_component_content(second, "request") == "Please plan feature B."
    assert [plan.plan_id for plan in list_plans(workspace)] == [
        "plan-0001",
        "plan-0002",
    ]
    assert validate_plan(second) == []
    assert plan_status_counts(workspace) == {"new": 1, "in_progress": 1}
