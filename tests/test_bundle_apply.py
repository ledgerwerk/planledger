from __future__ import annotations

from pathlib import Path

import pytest

from planledger.bundle import apply_bundle, load_bundle
from planledger.storage import initialize_project, list_records

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "harness_bundle_v1.json"


@pytest.fixture
def workspace(tmp_path: Path):
    return initialize_project(tmp_path, "Bundle Test")


def test_apply_creates_all_records(workspace):
    bundle = load_bundle(FIXTURE)
    result = apply_bundle(workspace, bundle)

    kinds = [r["kind"] for r in result.created]
    assert "run" in kinds
    assert "goal" in kinds
    assert "initiative" in kinds
    assert "plan" in kinds
    assert "milestone" in kinds
    assert "slice" in kinds
    assert "decision" in kinds
    assert "option" in kinds
    assert "risk" in kinds


def test_apply_creates_one_goal(workspace):
    bundle = load_bundle(FIXTURE)
    apply_bundle(workspace, bundle)
    goals = list_records(workspace, "goal")
    assert len(goals) == 1
    assert goals[0].front_matter.get("title") == "Make planledger harness-ready"


def test_apply_creates_one_initiative(workspace):
    bundle = load_bundle(FIXTURE)
    apply_bundle(workspace, bundle)
    inits = list_records(workspace, "initiative")
    assert len(inits) == 1
    assert inits[0].front_matter.get("title") == "Machine-first context export"


def test_apply_creates_one_plan(workspace):
    bundle = load_bundle(FIXTURE)
    result = apply_bundle(workspace, bundle)
    assert result.plan_id is not None
    plans = list_records(workspace, "plan")
    assert len(plans) == 1


def test_apply_creates_milestone_with_slice(workspace):
    bundle = load_bundle(FIXTURE)
    apply_bundle(workspace, bundle)
    milestones = list_records(workspace, "milestone")
    assert len(milestones) == 1
    slices = list_records(workspace, "slice")
    assert len(slices) == 1
    assert slices[0].front_matter.get("objective") is not None
    assert slices[0].front_matter.get("target_files") is not None
    assert slices[0].front_matter.get("acceptance_criteria") is not None


def test_ready_for_taskledger_slice_status(workspace):
    bundle = load_bundle(FIXTURE)
    apply_bundle(workspace, bundle)
    slices = list_records(workspace, "slice")
    assert slices[0].front_matter.get("status") == "ready-for-execution"
    assert slices[0].front_matter.get("ready_for_taskledger") is True


def test_apply_creates_accepted_architecture_decision(workspace):
    bundle = load_bundle(FIXTURE)
    apply_bundle(workspace, bundle)
    decisions = list_records(workspace, "decision")
    assert len(decisions) == 1
    dec = decisions[0]
    assert dec.front_matter.get("decision_type") == "architecture"
    assert dec.front_matter.get("status") == "accepted"

    options = list_records(workspace, "option")
    assert len(options) == 2
    statuses = [o.front_matter.get("status") for o in options]
    assert "accepted" in statuses
    assert "rejected" in statuses


def test_apply_creates_risk(workspace):
    bundle = load_bundle(FIXTURE)
    apply_bundle(workspace, bundle)
    risks = list_records(workspace, "risk")
    assert len(risks) == 1
    assert risks[0].front_matter.get("title") == "Context export may become too large"


def test_apply_creates_run_record(workspace):
    bundle = load_bundle(FIXTURE)
    apply_bundle(workspace, bundle)
    runs = list_records(workspace, "run")
    assert len(runs) == 1
    run = runs[0]
    assert run.front_matter.get("provenance") == "agent-generated"
    created = run.front_matter.get("created_records", [])
    assert len(created) > 0


def test_apply_emits_event(workspace):
    bundle = load_bundle(FIXTURE)
    result = apply_bundle(workspace, bundle)
    assert len(result.events) == 1
    assert result.events[0].get("event_type") == "bundle_applied"


def test_apply_invalid_bundle_raises(workspace):
    bundle = {"schema": "wrong"}
    with pytest.raises(Exception, match="invalid_bundle"):
        apply_bundle(workspace, bundle)


def test_apply_creates_language_records(workspace):
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "Add language"},
        "plan": {"title": "Language plan", "objectives": ["Track project terms"]},
        "language": {
            "areas": [{"title": "Ordering", "paths": ["src/ordering"]}],
            "terms": [
                {
                    "canonical": "Order",
                    "area": "Ordering",
                    "definition": "A customer request for goods or services.",
                }
            ],
            "ambiguities": [
                {
                    "phrase": "account",
                    "area": "Ordering",
                    "meanings": ["Customer", "User"],
                }
            ],
        },
    }

    apply_bundle(workspace, bundle)

    assert [record.front_matter.get("title") for record in list_records(workspace, "language_area")] == [
        "Ordering"
    ]
    assert [record.front_matter.get("canonical") for record in list_records(workspace, "language_term")] == [
        "Order"
    ]
    assert [record.front_matter.get("phrase") for record in list_records(workspace, "language_ambiguity")] == [
        "account"
    ]
