from __future__ import annotations

from pathlib import Path

from planledger.guardrails import (
    count_resolved_required_questions,
    resolved_required_question_topics,
    unresolved_required_question_topics,
    unresolved_required_questions,
    validate_handoff_contents,
)


def _valid_contents() -> dict[str, str]:
    return {
        "summary": "**Ready for implementation.**",
        "context": (
            "| Area | Finding | Evidence |\n|---|---|---|\n"
            "| CLI | Existing CLI. | `planledger/cli.py` |"
        ),
        "approach": "Use storage-level validation and keep rendering deterministic.",
        "todo_items": (
            "### TODO-001: Add guardrails\n\n"
            "**Target files**\n\n"
            "- [`planledger/storage.py`](planledger/storage.py)\n\n"
            "**Acceptance criteria**\n\n"
            "- [ ] Done plans without target files fail.\n"
            "- [ ] Done plans without acceptance criteria fail.\n\n"
            "**Validation**\n\n"
            "- `python -m pytest tests/test_plan_guardrails.py -q`\n"
            "### TODO-002: Wire into bundle\n\n"
            "**Target files**\n\n"
            "- [`planledger/bundle.py`](planledger/bundle.py)\n\n"
            "**Acceptance criteria**\n\n"
            "- [ ] Bundle done validation checks guardrails.\n\n"
            "**Validation**\n\n"
            "- `python -m pytest tests/test_plan_bundle.py -q`"
        ),
        "target_files": (
            "- [`planledger/storage.py`](planledger/storage.py) — validation wiring."
        ),
        "validation": "- `python -m pytest tests/test_plan_guardrails.py -q`",
        "risks": (
            "- Risk: validators become too strict. "
            "Mitigation: validate only done handoffs."
        ),
    }


def test_valid_handoff_passes() -> None:
    errors = validate_handoff_contents(_valid_contents())
    assert errors == []


def test_done_rejects_missing_todo_items() -> None:
    contents = _valid_contents()
    contents["todo_items"] = ""
    errors = validate_handoff_contents(contents)
    assert any("todo_items" in e for e in errors)


def test_done_rejects_todo_without_acceptance_criteria() -> None:
    contents = _valid_contents()
    contents["todo_items"] = (
        "### TODO-001: Add guardrails\n\n"
        "**Target files**\n\n"
        "- [`planledger/storage.py`](planledger/storage.py)\n\n"
        "**Validation**\n\n"
        "- `python -m pytest -q`"
    )
    errors = validate_handoff_contents(contents)
    assert any("Acceptance criteria" in e for e in errors)


def test_done_rejects_todo_without_acceptance_checkboxes() -> None:
    contents = _valid_contents()
    contents["todo_items"] = (
        "### TODO-001: Add guardrails\n\n"
        "**Target files**\n\n"
        "- [`planledger/storage.py`](planledger/storage.py)\n\n"
        "**Acceptance criteria**\n\n"
        "All tests pass.\n\n"
        "**Validation**\n\n"
        "- `python -m pytest -q`"
    )
    errors = validate_handoff_contents(contents)
    assert any("acceptance checkbox" in e for e in errors)


def test_done_rejects_todo_without_target_files() -> None:
    contents = _valid_contents()
    contents["todo_items"] = (
        "### TODO-001: Add guardrails\n\n"
        "**Acceptance criteria**\n\n"
        "- [ ] Guardrails work.\n\n"
        "**Validation**\n\n"
        "- `python -m pytest -q`"
    )
    errors = validate_handoff_contents(contents)
    assert any("Target files" in e for e in errors)


def test_done_rejects_todo_without_file_references() -> None:
    contents = _valid_contents()
    contents["todo_items"] = (
        "### TODO-001: Add guardrails\n\n"
        "**Target files**\n\n"
        "None needed.\n\n"
        "**Acceptance criteria**\n\n"
        "- [ ] Guardrails work.\n\n"
        "**Validation**\n\n"
        "- `python -m pytest -q`"
    )
    errors = validate_handoff_contents(contents)
    assert any("target file" in e for e in errors)


def test_done_rejects_empty_target_files_component() -> None:
    contents = _valid_contents()
    contents["target_files"] = "No files."
    errors = validate_handoff_contents(contents)
    assert any("target_files" in e and "file path" in e for e in errors)


def test_done_rejects_empty_validation_component() -> None:
    contents = _valid_contents()
    contents["validation"] = "Manual inspection."
    errors = validate_handoff_contents(contents)
    assert any("validation" in e and "command" in e for e in errors)


def test_done_rejects_placeholder_content() -> None:
    contents = _valid_contents()
    contents["approach"] = "TBD"
    errors = validate_handoff_contents(contents)
    assert any("placeholder" in e for e in errors)


def test_todo_identifier_not_rejected_as_placeholder() -> None:
    contents = _valid_contents()
    contents["todo_items"] = (
        "### TODO-001: Add guardrails\n\n"
        "**Target files**\n\n"
        "- [`planledger/storage.py`](planledger/storage.py)\n\n"
        "**Acceptance criteria**\n\n"
        "- [ ] Guardrails work.\n\n"
        "**Validation**\n\n"
        "- `python -m pytest -q`"
    )
    errors = validate_handoff_contents(contents)
    assert not any("placeholder" in e for e in errors)


def test_checkbox_only_todos_pass() -> None:
    contents = _valid_contents()
    contents["todo_items"] = (
        "- [ ] Add guardrails to [`planledger/storage.py`](planledger/storage.py)\n"
        "- [ ] Wire validation in [`planledger/bundle.py`](planledger/bundle.py)"
    )
    errors = validate_handoff_contents(contents)
    # Checkbox-only todos do not have structured acceptance criteria sections,
    # so they will produce errors about missing acceptance criteria.
    # This is expected: structured TODO-NNN headings are the primary format.
    assert any("Acceptance criteria" in e for e in errors)


def test_done_rejects_unresolved_required_questions() -> None:
    contents = _valid_contents()
    contents["open_questions"] = (
        "- [ ] REQUIRED: Which API version must remain supported?\n"
        "- [ ] REQUIRED: Should migration be backward-compatible?"
    )
    errors = validate_handoff_contents(contents)
    assert any("unresolved required questions" in e for e in errors)


def test_done_accepts_resolved_required_questions() -> None:
    contents = _valid_contents()
    contents["open_questions"] = (
        "- [x] REQUIRED: Which API version must remain supported? Answer: Python 3.10+."
    )
    errors = validate_handoff_contents(contents)
    assert not any("unresolved required questions" in e for e in errors)


def test_done_accepts_empty_open_questions() -> None:
    contents = _valid_contents()
    contents["open_questions"] = ""
    errors = validate_handoff_contents(contents)
    assert not any("open_questions" in e for e in errors)


def test_done_accepts_non_required_open_questions() -> None:
    contents = _valid_contents()
    contents["open_questions"] = "- [ ] Should we use asyncio?"
    errors = validate_handoff_contents(contents)
    assert not any("unresolved required questions" in e for e in errors)


def test_done_rejects_missing_todo_items_cli(
    initialized_workspace: Path, invoke
) -> None:
    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Add guardrails",
        "--request",
        "Please add planning guardrails.",
    )
    assert create.exit_code == 0, create.stdout

    from tests.test_plan_status import _fill_required_components

    _fill_required_components(initialized_workspace, invoke)

    clear = invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "todo_items",
        "--text",
        "",
    )
    assert clear.exit_code == 0, clear.stdout

    result = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "done",
        "--reason",
        "Ready for handoff.",
    )

    assert result.exit_code != 0
    assert "todo_items" in result.stdout


def test_done_rejects_todo_without_acceptance_criteria_cli(
    initialized_workspace: Path, invoke
) -> None:
    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Add guardrails",
        "--request",
        "Please add planning guardrails.",
    )
    assert create.exit_code == 0, create.stdout

    from tests.test_plan_status import _fill_required_components

    _fill_required_components(initialized_workspace, invoke)
    bad_todo = """### TODO-001: Add guardrails

**Target files**

- [`planledger/storage.py`](planledger/storage.py)

**Validation**

- `python -m pytest tests/test_plan_guardrails.py -q`
"""
    result = invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "todo_items",
        "--text",
        bad_todo,
    )
    assert result.exit_code == 0, result.stdout

    done = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "done",
        "--reason",
        "Ready for handoff.",
    )

    assert done.exit_code != 0
    assert "Acceptance criteria" in done.stdout


def test_done_accepts_complete_handoff_plan_cli(
    initialized_workspace: Path, invoke
) -> None:
    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Add guardrails",
        "--request",
        "Please add planning guardrails.",
    )
    assert create.exit_code == 0, create.stdout

    from tests.test_plan_status import _fill_required_components

    _fill_required_components(initialized_workspace, invoke)
    done = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "done",
        "--reason",
        "Ready for handoff.",
    )

    assert done.exit_code == 0, done.stdout


def test_min_resolved_required_questions_blocks_done_until_resolved(
    initialized_workspace: Path, invoke
) -> None:
    from tests.test_plan_status import _fill_required_components

    config = initialized_workspace / "planledger.toml"
    config.write_text(
        config.read_text(encoding="utf-8")
        + "\n[prompt_profiles.planning_interview]\n"
        + "enabled = true\n"
        + 'activation = "always"\n'
        + "min_resolved_required_questions_before_done = 1\n",
        encoding="utf-8",
    )

    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Feature A",
        "--request",
        "Please plan feature A.",
    )
    _fill_required_components(initialized_workspace, invoke)

    blocked = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "done",
        "--reason",
        "Ready.",
    )
    assert blocked.exit_code != 0
    assert "resolved required question" in blocked.stdout

    invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "open_questions",
        "--text",
        "- [x] REQUIRED: Opt-in first? Answer: yes, opt-in first.",
    )

    allowed = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "done",
        "--reason",
        "Ready.",
    )
    assert allowed.exit_code == 0, allowed.stdout


def test_required_question_regex_accepts_topic_tags() -> None:
    text = (
        "- [ ] REQUIRED(scope): Should we limit scope?\n"
        "- [ ] REQUIRED: Plain unresolved?\n"
        "- [x] REQUIRED(tests): Which tests? Answer: full suite.\n"
        "- [x] REQUIRED: Plain resolved.\n"
    )
    assert unresolved_required_questions(text) == [
        "Should we limit scope?",
        "Plain unresolved?",
    ]
    assert count_resolved_required_questions(text) == 2
    assert unresolved_required_question_topics(text) == {"scope"}
    assert resolved_required_question_topics(text) == {"tests"}


def test_topic_tagged_required_questions_still_block_done() -> None:
    contents = _valid_contents()
    contents["open_questions"] = (
        "- [ ] REQUIRED(scope): Should we limit scope?"
    )
    errors = validate_handoff_contents(contents)
    assert any("unresolved required questions" in e for e in errors)


def test_resolved_topic_tagged_required_questions_pass_done() -> None:
    contents = _valid_contents()
    contents["open_questions"] = (
        "- [x] REQUIRED(scope): Should we limit scope? Answer: minimal only."
    )
    errors = validate_handoff_contents(contents)
    assert not any("unresolved required questions" in e for e in errors)
