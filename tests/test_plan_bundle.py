from __future__ import annotations

import json
from pathlib import Path

from planledger.cli import app
from planledger.storage import initialize_project, load_component_content, load_plan


def test_bundle_dry_run_create_and_single_increment_update(
    tmp_path: Path, invoke
) -> None:
    workspace = initialize_project(
        tmp_path, "Test Project", create_sibling_store=True
    )
    create_bundle = tmp_path / "create.json"
    create_bundle.write_text(
        json.dumps(
            {
                "schema": "planledger.structured_plan.v1",
                "operation": "create",
                "plan": {
                    "title": "Add feature A",
                    "status": "new",
                    "request": "Please review how we can add feature A.",
                    "components": {
                        "summary": "Short summary.",
                        "context": "Repository context.",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    dry_run = invoke(
        tmp_path, "plan", "apply", "--file", str(create_bundle), "--dry-run"
    )

    assert dry_run.exit_code == 0, dry_run.stdout
    assert not (tmp_path / ".planledger" / "plans" / "plan-0001").exists()

    applied = invoke(tmp_path, "plan", "apply", "--file", str(create_bundle))

    assert applied.exit_code == 0, applied.stdout

    update_bundle = tmp_path / "update.json"
    update_bundle.write_text(
        json.dumps(
            {
                "schema": "planledger.structured_plan.v1",
                "operation": "update",
                "plan_id": "plan-0001",
                "reason": "Human requested a refinement.",
                "components": {
                    "summary": "Updated summary.",
                    "todo_items": "1. Update storage.\n2. Update CLI.",
                },
            }
        ),
        encoding="utf-8",
    )
    updated = invoke(tmp_path, "plan", "apply", "--file", str(update_bundle))
    plan = load_plan(workspace, "plan-0001")

    assert updated.exit_code == 0, updated.stdout
    assert plan.version == 2
    assert (
        load_component_content(plan, "request")
        == "Please review how we can add feature A."
    )
    assert load_component_content(plan, "summary") == "Updated summary."


def test_bundle_validation_rejects_unknown_components_and_invalid_statuses(
    initialized_workspace: Path, invoke, tmp_path: Path
) -> None:
    bundle_path = tmp_path / "invalid.json"
    bundle_path.write_text(
        json.dumps(
            {
                "schema": "planledger.structured_plan.v1",
                "operation": "create",
                "plan": {
                    "title": "Add feature A",
                    "status": "invalid",
                    "request": "Please review how we can add feature A.",
                    "components": {
                        "unknown_component": "text",
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    result = invoke(
        initialized_workspace,
        "plan",
        "apply",
        "--file",
        str(bundle_path),
        "--dry-run",
    )

    assert result.exit_code != 0
    assert "invalid" in result.stdout.lower()
    assert "unknown component key" in result.stdout.lower()


def test_plan_apply_reads_bundle_from_stdin(tmp_path: Path, runner) -> None:
    init = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "init", "--project-name", "Bundle Stdin"],
    )
    bundle = {
        "schema": "planledger.structured_plan.v1",
        "operation": "create",
        "plan": {
            "title": "Bundle stdin",
            "request": "Create from stdin.",
            "components": {
                "summary": "Created through stdin bundle.",
            },
        },
    }
    apply = runner.invoke(
        app,
        ["--cwd", str(tmp_path), "plan", "apply", "--file", "-"],
        input=json.dumps(bundle),
    )

    assert init.exit_code == 0, init.stdout
    assert apply.exit_code == 0, apply.stdout
    assert (
        tmp_path
        / ".planledger"
        / "plans"
        / "plan-0001"
        / "components"
        / "10-executive-verdict.md"
    ).read_text() == "Created through stdin bundle."


def test_bundle_update_accepts_global_ref_and_dry_run_returns_derived_ref(
    tmp_path: Path,
    invoke_json,
) -> None:
    workspace = initialize_project(
        tmp_path, "Test Project", create_sibling_store=True
    )
    create_bundle = {
        "schema": "planledger.structured_plan.v1",
        "operation": "create",
        "plan": {"title": "Bundle refs", "request": "Create a plan."},
    }
    create_path = tmp_path / "create-ref.json"
    create_path.write_text(json.dumps(create_bundle), encoding="utf-8")
    created, _ = invoke_json(tmp_path, "plan", "apply", "--file", str(create_path))
    assert created.exit_code == 0, created.stdout

    update_bundle = {
        "schema": "planledger.structured_plan.v1",
        "operation": "update",
        "plan_id": "pl:plan-0001",
        "reason": "Use a global selector.",
        "components": {"summary": "Updated through a global ref."},
    }
    update_path = tmp_path / "update-ref.json"
    update_path.write_text(json.dumps(update_bundle), encoding="utf-8")
    dry_run, payload = invoke_json(
        tmp_path,
        "plan",
        "apply",
        "--file",
        str(update_path),
        "--dry-run",
    )

    assert dry_run.exit_code == 0, dry_run.stdout
    assert payload["result"]["plan_id"] == "plan-0001"
    assert payload["result"]["global_ref"] == "pl:plan-0001"
    assert load_plan(workspace, "plan-0001").version == 1


def test_bundle_update_rejects_foreign_ref(tmp_path: Path, invoke_json) -> None:
    initialize_project(tmp_path, "Test Project", create_sibling_store=True)
    bundle = {
        "schema": "planledger.structured_plan.v1",
        "operation": "update",
        "plan_id": "tl:task-0001",
        "reason": "Invalid foreign ref.",
    }
    path = tmp_path / "foreign-ref.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")

    result, payload = invoke_json(
        tmp_path,
        "plan",
        "apply",
        "--file",
        str(path),
        "--dry-run",
    )

    assert result.exit_code != 0
    assert payload["error"]["code"] == "invalid_bundle"
