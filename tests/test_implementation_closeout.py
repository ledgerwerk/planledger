from __future__ import annotations

import json
from pathlib import Path

import pytest

from planledger.errors import PlanledgerError
from planledger.implementation import (
    apply_implementation_report,
    validate_implementation_report,
)
from planledger.storage import create_record, initialize_project, list_records, load_record


def _seed_workspace(tmp_path: Path):
    workspace = initialize_project(tmp_path, "Implementation Closeout")
    create_record(
        workspace,
        "goal",
        {
            "id": "goal-0001",
            "type": "goal",
            "title": "Primary goal",
            "status": "active",
            "horizon": "quarter",
            "priority": "high",
            "success_metrics": [],
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )
    create_record(
        workspace,
        "goal",
        {
            "id": "goal-0002",
            "type": "goal",
            "title": "Secondary goal",
            "status": "active",
            "horizon": "quarter",
            "priority": "high",
            "success_metrics": [],
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )
    create_record(
        workspace,
        "initiative",
        {
            "id": "init-0001",
            "type": "initiative",
            "goal": "goal-0001",
            "title": "Closeout initiative",
            "status": "executing",
            "owner": "agent",
            "priority": "high",
            "active": True,
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )
    create_record(
        workspace,
        "plan",
        {
            "id": "plan-0001",
            "type": "plan",
            "goal": "goal-0001",
            "initiative": "init-0001",
            "version": 1,
            "status": "accepted",
            "supersedes": None,
            "accepted_at": "2025-01-01T00:00:00Z",
            "accepted_by": "agent",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "# Plan\n",
    )
    create_record(
        workspace,
        "slice",
        {
            "id": "slice-0001",
            "type": "slice",
            "initiative": "init-0001",
            "plan": "plan-0001",
            "milestone": "ms-0001",
            "title": "Validation slice",
            "status": "in-execution",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
        },
        "",
    )
    return workspace


def test_validating_slice_requires_evidence(invoke, initialized_workspace: Path) -> None:
    report_path = initialized_workspace / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "schema": "planledger.implementation_report.v1",
                "slice_updates": [{"id": "slice-0001", "action": "validate"}],
            }
        ),
        encoding="utf-8",
    )
    result = invoke(
        initialized_workspace,
        "--json",
        "implementation",
        "report",
        "validate",
        "--file",
        str(report_path),
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["ok"] is False
    assert payload["result"]["errors"]


def test_completing_goal_records_evidence_and_close_metadata(tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path)
    report = {
        "schema": "planledger.implementation_report.v1",
        "goal_updates": [
            {
                "id": "goal-0001",
                "action": "complete",
                "reason": "Primary goal implemented.",
                "evidence": "pytest -q",
            }
        ],
    }
    apply_implementation_report(workspace, report)
    goal = load_record(workspace, "goal", "goal-0001")
    assert goal.front_matter["status"] == "fulfilled"
    assert goal.front_matter["close_reason"] == "Primary goal implemented."
    assert goal.front_matter["evidence"] == ["pytest -q"]


def test_cancelling_related_goal_records_related_goal_link(tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path)
    report = {
        "schema": "planledger.implementation_report.v1",
        "goal_updates": [
            {
                "id": "goal-0002",
                "action": "cancel",
                "reason": "Primary goal made this unnecessary.",
                "evidence": "Implemented goal-0001",
                "related_goal": "goal-0001",
            }
        ],
    }
    apply_implementation_report(workspace, report)
    goal = load_record(workspace, "goal", "goal-0002")
    assert goal.front_matter["status"] == "cancelled"
    assert goal.front_matter["related_goals"] == ["goal-0001"]


def test_closeout_can_create_language_terms_and_rationales(tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path)
    report = {
        "schema": "planledger.implementation_report.v1",
        "language_terms": [
            {
                "canonical": "Invoice",
                "definition": "A bill issued after fulfillment.",
                "evidence": [{"path": "src/billing/invoice.py", "reason": "Created by feature"}],
            }
        ],
        "rationales": [
            {
                "title": "Billing remains asynchronous",
                "initiative": "init-0001",
                "summary": "Asynchronous billing keeps order placement available during billing outages.",
                "evidence": "Validated with task run output.",
            }
        ],
    }
    apply_implementation_report(workspace, report)
    assert [record.front_matter["canonical"] for record in list_records(workspace, "language_term")] == [
        "Invoice"
    ]
    assert [record.front_matter["title"] for record in list_records(workspace, "decision")] == [
        "Billing remains asynchronous"
    ]


def test_closeout_is_idempotent(tmp_path: Path) -> None:
    workspace = _seed_workspace(tmp_path)
    report = {
        "schema": "planledger.implementation_report.v1",
        "goal_updates": [
            {
                "id": "goal-0001",
                "action": "complete",
                "reason": "Primary goal implemented.",
                "evidence": "pytest -q",
            }
        ],
        "language_terms": [
            {
                "canonical": "Invoice",
                "definition": "A bill issued after fulfillment.",
                "evidence": [{"path": "src/billing/invoice.py", "reason": "Created by feature"}],
            }
        ],
        "rationales": [
            {
                "title": "Billing remains asynchronous",
                "initiative": "init-0001",
                "summary": "Asynchronous billing keeps order placement available during billing outages.",
                "evidence": "Validated with task run output.",
            }
        ],
    }
    apply_implementation_report(workspace, report)
    second = apply_implementation_report(workspace, report)
    reused_kinds = {item["kind"] for item in second.reused}
    assert "goal" in reused_kinds
    assert "language_term" in reused_kinds
    assert "decision" in reused_kinds


def test_taskledger_drift_blocks_closeout_when_unresolved(tmp_path: Path, monkeypatch) -> None:
    workspace = _seed_workspace(tmp_path)
    create_record(
        workspace,
        "binding",
        {
            "id": "bind-0001",
            "type": "binding",
            "provider": "taskledger",
            "planledger_ref": "slice-0001",
            "workspace_root": str(workspace.root),
            "taskledger_config": str(workspace.root / "taskledger.toml"),
            "ledger_ref": workspace.ledger_ref,
            "task_ref": "task-9999",
            "task_slug": "missing-task",
            "sync_direction": "pull-status",
            "last_seen_status": None,
            "last_seen_validation": None,
            "last_sync_at": "2025-01-01T00:00:00Z",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2025-01-01T00:00:00Z",
            "integration_command": "taskledger",
        },
        "",
    )

    def _raise(*args, **kwargs):
        raise PlanledgerError("taskledger_error", "missing task")

    monkeypatch.setattr("planledger.taskledger.run_taskledger_json", _raise)

    details = validate_implementation_report(
        {"schema": "planledger.implementation_report.v1"},
        workspace=workspace,
    )
    assert details.ok is False
    assert details.drift
