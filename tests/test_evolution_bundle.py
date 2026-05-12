from __future__ import annotations

from planledger.bundle import apply_evolution_bundle, validate_evolution_details
from planledger.storage import create_record, initialize_project, list_records, load_record


def _seed_goal(workspace, goal_id: str, title: str, status: str = "active") -> None:
    create_record(
        workspace,
        "goal",
        {
            "id": goal_id,
            "type": "goal",
            "title": title,
            "status": status,
            "horizon": "quarter",
            "priority": "high",
            "success_metrics": [],
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )


def test_evolution_bundle_validates(tmp_path) -> None:
    workspace = initialize_project(tmp_path, "Evolution Validate")
    _seed_goal(workspace, "goal-0001", "Feature A")
    bundle = {
        "schema": "planledger.evolution_bundle.v1",
        "request": {"title": "Close goals"},
        "updates": [
            {
                "kind": "goal",
                "id": "goal-0001",
                "action": "cancel",
                "reason": "No longer useful.",
            }
        ],
    }
    details = validate_evolution_details(bundle)
    assert details.errors == []


def test_evolution_bundle_apply_updates_goals_and_creates_review(tmp_path) -> None:
    workspace = initialize_project(tmp_path, "Evolution Apply")
    _seed_goal(workspace, "goal-0001", "Feature A")
    _seed_goal(workspace, "goal-0002", "Feature B")
    bundle = {
        "schema": "planledger.evolution_bundle.v1",
        "request": {"title": "Close fulfilled and obsolete goals"},
        "updates": [
            {
                "kind": "goal",
                "id": "goal-0001",
                "action": "complete",
                "reason": "Feature A implemented and validated.",
                "evidence": ["taskledger:task-0007"],
            },
            {
                "kind": "goal",
                "id": "goal-0002",
                "action": "cancel",
                "reason": "Feature A removed the need for feature B.",
                "related_goals": ["goal-0001"],
            },
        ],
        "creates": {
            "reviews": [
                {
                    "scope_kind": "goal",
                    "scope_id": "goal-0001",
                    "title": "Feature A outcome review",
                    "outcome": "fulfilled",
                    "findings": ["Goal 1 is complete."],
                    "recommendations": ["Cancel goal-0002."],
                }
            ]
        },
    }
    result = apply_evolution_bundle(workspace, bundle)
    goal_one = load_record(workspace, "goal", "goal-0001")
    goal_two = load_record(workspace, "goal", "goal-0002")
    review = load_record(workspace, "review", "review-0001")
    assert result.updated
    assert goal_one.front_matter["status"] == "fulfilled"
    assert goal_two.front_matter["status"] == "cancelled"
    assert goal_two.front_matter["related_goals"] == ["goal-0001"]
    assert review.front_matter["outcome"] == "fulfilled"


def test_evolution_bundle_dry_run_does_not_write(tmp_path) -> None:
    workspace = initialize_project(tmp_path, "Evolution Dry Run")
    _seed_goal(workspace, "goal-0001", "Feature A")
    bundle = {
        "schema": "planledger.evolution_bundle.v1",
        "request": {"title": "Preview"},
        "updates": [
            {
                "kind": "goal",
                "id": "goal-0001",
                "action": "cancel",
                "reason": "No longer useful.",
            }
        ],
        "creates": {
            "questions": [
                {
                    "scope_kind": "goal",
                    "scope_id": "goal-0001",
                    "title": "What changed?",
                }
            ]
        },
    }
    result = apply_evolution_bundle(workspace, bundle, dry_run=True)
    assert result.updated == [{"kind": "goal", "id": "goal-0001", "action": "cancel"}]
    assert result.created == [{"kind": "question", "title": "What changed?"}]
    goal = load_record(workspace, "goal", "goal-0001")
    assert goal.front_matter["status"] == "active"
    assert list_records(workspace, "question") == []


def test_evolution_bundle_reapply_reuses_scoped_records(tmp_path) -> None:
    workspace = initialize_project(tmp_path, "Evolution Reapply")
    _seed_goal(workspace, "goal-0001", "Feature A")
    bundle = {
        "schema": "planledger.evolution_bundle.v1",
        "request": {"title": "Create question"},
        "creates": {
            "questions": [
                {
                    "scope_kind": "goal",
                    "scope_id": "goal-0001",
                    "title": "What changed?",
                }
            ]
        },
    }
    apply_evolution_bundle(workspace, bundle)
    result = apply_evolution_bundle(workspace, bundle)
    assert result.reused == [{"kind": "question", "id": "q-0001"}]
    assert len(list_records(workspace, "question")) == 1
