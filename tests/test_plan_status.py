from __future__ import annotations

from pathlib import Path


def _fill_required_components(workspace: Path, invoke) -> None:
    _todo = (
        "### TODO-001: Implement the feature\n\n"
        "**Target files**\n\n"
        "- `planledger/storage.py`\n\n"
        "**Acceptance criteria**\n\n"
        "- [ ] Feature works.\n\n"
        "**Validation**\n\n"
        "- `python -m pytest -q`"
    )
    _target = "- `planledger/storage.py` \u2014 storage changes."
    _risks = "- Risk: scope creep. Mitigation: keep changes focused."
    component_values = {
        "summary": "Summary text.",
        "context": "Repository context.",
        "approach": "Recommended approach.",
        "todo_items": _todo,
        "target_files": _target,
        "validation": "Run `python -m pytest -q`.",
        "risks": _risks,
    }
    for key, value in component_values.items():
        result = invoke(
            workspace,
            "plan",
            "component",
            "set",
            "plan-0001",
            key,
            "--text",
            value,
        )
        assert result.exit_code == 0, result.stdout


def test_valid_and_invalid_status_transitions(
    initialized_workspace: Path, invoke
) -> None:
    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Add feature A",
        "--request",
        "Please review how we can add feature A.",
    )
    assert create.exit_code == 0, create.stdout
    _fill_required_components(initialized_workspace, invoke)

    in_progress = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "in_progress",
        "--reason",
        "Planning is underway.",
    )
    done = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "done",
        "--reason",
        "Ready for handoff.",
    )
    invalid = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "new",
        "--reason",
        "Try to go backwards.",
    )
    rework = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "rework",
        "--reason",
        "Human requested changes.",
    )

    assert in_progress.exit_code == 0, in_progress.stdout
    assert done.exit_code == 0, done.stdout
    assert invalid.exit_code != 0
    assert rework.exit_code == 0, rework.stdout


def test_done_requires_reason_and_non_empty_required_components(
    initialized_workspace: Path, invoke
) -> None:
    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Add feature A",
        "--request",
        "Please review how we can add feature A.",
    )
    missing_reason = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "done",
    )
    missing_components = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "done",
        "--reason",
        "Ready",
    )

    assert create.exit_code == 0, create.stdout
    assert missing_reason.exit_code != 0
    assert missing_components.exit_code != 0
    assert "Required component" in missing_components.stdout
