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


def test_plan_activate_switches_active_plan(
    initialized_workspace: Path, invoke
) -> None:
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "First",
        "--request",
        "req1",
    )
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Second",
        "--request",
        "req2",
    )
    result = invoke(
        initialized_workspace,
        "plan",
        "activate",
        "plan-0001",
    )
    assert result.exit_code == 0, result.stdout
    assert "Activated plan-0001" in result.stdout


def test_plan_show_uses_active_plan(initialized_workspace: Path, invoke) -> None:
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Active",
        "--request",
        "req",
    )
    result = invoke(
        initialized_workspace,
        "plan",
        "show",
    )
    assert result.exit_code == 0, result.stdout
    assert "plan-0001" in result.stdout


def test_plan_show_plan_option_overrides_active(
    initialized_workspace: Path, invoke
) -> None:
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "First",
        "--request",
        "req1",
    )
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Second",
        "--request",
        "req2",
    )
    result = invoke(
        initialized_workspace,
        "plan",
        "show",
        "--plan",
        "plan-0001",
    )
    assert result.exit_code == 0, result.stdout
    assert "First" in result.stdout


def test_plan_show_positional_overrides_active(
    initialized_workspace: Path, invoke
) -> None:
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "First",
        "--request",
        "req1",
    )
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Second",
        "--request",
        "req2",
    )
    result = invoke(
        initialized_workspace,
        "plan",
        "show",
        "plan-0001",
    )
    assert result.exit_code == 0, result.stdout
    assert "First" in result.stdout


def test_plan_no_active_plan_no_selector_fails(
    initialized_workspace: Path, invoke
) -> None:
    result = invoke(
        initialized_workspace,
        "plan",
        "show",
    )
    assert result.exit_code != 0
    assert (
        "no active plan" in result.stdout.lower() or "no_active_plan" in result.stdout
    )


def _create_and_fill_plan(workspace: Path, invoke) -> str:
    create = invoke(
        workspace,
        "plan",
        "create",
        "--title",
        "Add feature",
        "--request",
        "Request.",
    )
    assert create.exit_code == 0, create.stdout
    _fill_required_components(workspace, invoke)
    return "plan-0001"


def test_status_accepts_active_plan_status_first(
    initialized_workspace: Path, invoke
) -> None:
    _create_and_fill_plan(initialized_workspace, invoke)

    result = invoke(
        initialized_workspace,
        "plan",
        "status",
        "done",
        "--reason",
        "Ready.",
    )
    assert result.exit_code == 0, result.stdout
    assert "Updated plan-0001 (done" in result.stdout


def test_status_accepts_status_first_with_plan_option(
    initialized_workspace: Path, invoke
) -> None:
    _create_and_fill_plan(initialized_workspace, invoke)

    result = invoke(
        initialized_workspace,
        "plan",
        "status",
        "done",
        "--plan",
        "plan-0001",
        "--reason",
        "Ready.",
    )
    assert result.exit_code == 0, result.stdout
    assert "Updated plan-0001 (done" in result.stdout


def test_status_accepts_status_first_with_plan_positional(
    initialized_workspace: Path, invoke
) -> None:
    _create_and_fill_plan(initialized_workspace, invoke)

    result = invoke(
        initialized_workspace,
        "plan",
        "status",
        "done",
        "plan-0001",
        "--reason",
        "Ready.",
    )
    assert result.exit_code == 0, result.stdout
    assert "Updated plan-0001 (done" in result.stdout


def test_status_keeps_legacy_plan_first_form(
    initialized_workspace: Path, invoke
) -> None:
    _create_and_fill_plan(initialized_workspace, invoke)

    result = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "done",
        "--reason",
        "Ready.",
    )
    assert result.exit_code == 0, result.stdout
    assert "Updated plan-0001 (done" in result.stdout


def test_status_invalid_args_produce_clear_remediation(
    initialized_workspace: Path, invoke
) -> None:
    _create_and_fill_plan(initialized_workspace, invoke)

    # Two plan ids, no status.
    result = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "plan-0002",
        "--reason",
        "Ready.",
    )
    assert result.exit_code == 2
    assert "invalid_status_args" in result.stdout
    assert "planledger plan status done" in result.stdout


def test_status_missing_status_arg_produces_clear_remediation(
    initialized_workspace: Path, invoke
) -> None:
    _create_and_fill_plan(initialized_workspace, invoke)

    # One positional that is not a status (looks like a plan id only).
    result = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "--reason",
        "Ready.",
    )
    assert result.exit_code == 2
    assert "invalid_status_args" in result.stdout
