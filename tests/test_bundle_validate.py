from __future__ import annotations

from pathlib import Path

from planledger.bundle import load_bundle, validate_bundle, validate_bundle_details


def test_valid_bundle_passes():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "Test"},
        "plan": {"title": "Test plan", "objectives": ["Do thing"]},
        "milestones": [{"title": "M1", "slices": [{"title": "S1"}]}],
        "decisions": [{"title": "D1", "status": "open"}],
        "risks": [{"title": "R1", "impact": "high", "mitigation": "Track size"}],
    }
    errors = validate_bundle(bundle)
    assert errors == []


def test_missing_schema():
    bundle = {"plan": {"title": "T", "objectives": ["O"]}}
    errors = validate_bundle(bundle)
    assert any("schema" in e for e in errors)


def test_wrong_schema():
    bundle = {
        "schema": "wrong",
        "request": {"title": "T"},
        "plan": {"title": "T", "objectives": ["O"]},
    }
    errors = validate_bundle(bundle)
    assert any("schema" in e for e in errors)


def test_missing_plan():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
    }
    errors = validate_bundle(bundle)
    assert any("plan" in e for e in errors)


def test_missing_plan_title():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"objectives": ["O"]},
    }
    errors = validate_bundle(bundle)
    assert any("title" in e.lower() for e in errors)


def test_missing_plan_objectives():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"title": "T"},
    }
    errors = validate_bundle(bundle)
    assert any("objectives" in e.lower() for e in errors)


def test_missing_request():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "plan": {"title": "T", "objectives": ["O"]},
    }
    errors = validate_bundle(bundle)
    assert any("request" in e for e in errors)


def test_missing_request_title():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {},
        "plan": {"title": "T", "objectives": ["O"]},
    }
    errors = validate_bundle(bundle)
    assert any("request.title" in e for e in errors)


def test_milestone_missing_title():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"title": "T", "objectives": ["O"]},
        "milestones": [{"slices": []}],
    }
    errors = validate_bundle(bundle)
    assert any("title" in e.lower() for e in errors)


def test_milestone_slice_missing_title():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"title": "T", "objectives": ["O"]},
        "milestones": [{"title": "M", "slices": [{}]}],
    }
    errors = validate_bundle(bundle)
    assert any("slice" in e.lower() and "title" in e.lower() for e in errors)


def test_decisions_not_list():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"title": "T", "objectives": ["O"]},
        "decisions": "not a list",
    }
    errors = validate_bundle(bundle)
    assert any("decisions" in e for e in errors)


def test_risks_not_list():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"title": "T", "objectives": ["O"]},
        "risks": "not a list",
    }
    errors = validate_bundle(bundle)
    assert any("risks" in e for e in errors)


def test_ready_slice_requires_fields():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"title": "T", "objectives": ["O"]},
        "milestones": [
            {
                "title": "M",
                "slices": [{"title": "S", "ready_for_taskledger": True}],
            }
        ],
    }
    errors = validate_bundle(bundle)
    assert any("ready_for_taskledger=true" in e for e in errors)


def test_duplicate_slice_keys_are_rejected():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"title": "T", "objectives": ["O"]},
        "milestones": [
            {
                "title": "M",
                "slices": [
                    {"title": "S1", "key": "dup"},
                    {"title": "S2", "key": "dup"},
                ],
            }
        ],
    }
    errors = validate_bundle(bundle)
    assert any("Duplicate slice key" in e for e in errors)


def test_accepted_decision_requires_one_accepted_option():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"title": "T", "objectives": ["O"]},
        "decisions": [
            {
                "title": "D1",
                "status": "accepted",
                "options": [
                    {"title": "A", "status": "accepted"},
                    {"title": "B", "status": "accepted"},
                ],
            }
        ],
    }
    errors = validate_bundle(bundle)
    assert any("exactly one is required" in e for e in errors)


def test_high_impact_risk_requires_mitigation():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"title": "T", "objectives": ["O"]},
        "risks": [{"title": "R1", "impact": "high", "likelihood": "medium"}],
    }
    errors = validate_bundle(bundle)
    assert any("requires a mitigation" in e for e in errors)


def test_unknown_top_level_field_warns_or_errors():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"title": "T", "objectives": ["O"]},
        "extra_field": 1,
    }
    non_strict = validate_bundle_details(bundle, strict_unknown_fields=False)
    strict = validate_bundle_details(bundle, strict_unknown_fields=True)
    assert any("Unknown top-level field" in w for w in non_strict.warnings)
    assert any("Unknown top-level field" in e for e in strict.errors)


def test_language_section_validates():
    bundle = {
        "schema": "planledger.plan_bundle.v1",
        "request": {"title": "T"},
        "plan": {"title": "T", "objectives": ["O"]},
        "language": {
            "areas": [{"title": "Ordering"}],
            "terms": [
                {
                    "canonical": "Order",
                    "definition": "A customer request for goods or services.",
                }
            ],
            "ambiguities": [{"phrase": "account"}],
        },
    }
    errors = validate_bundle(bundle)
    assert errors == []


def test_example_bundle_validates():
    bundle = load_bundle(
        Path(__file__).resolve().parent.parent / "examples" / "harness_bundle_v1.json"
    )
    errors = validate_bundle(bundle)
    assert errors == []
