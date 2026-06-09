from __future__ import annotations

import json
from pathlib import Path

from planledger.storage import initialize_project, load_component_content, load_plan


def test_bundle_dry_run_create_and_single_increment_update(
    tmp_path: Path, invoke
) -> None:
    workspace = initialize_project(tmp_path, "Test Project")
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
