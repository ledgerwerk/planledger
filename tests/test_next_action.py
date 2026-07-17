from __future__ import annotations

from pathlib import Path

from planledger.storage import compute_next_action, initialize_project


def test_next_action_uninitialized() -> None:
    result = compute_next_action(None)
    assert result["workspace_initialized"] is False
    assert result["next_item"] == "init"
    assert result["plan_id"] is None


def test_next_action_accepts_command_local_json(
    initialized_workspace: Path, invoke
) -> None:
    import json

    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Test",
        "--request",
        "Test request.",
    )
    assert create.exit_code == 0, create.stdout

    # Command-local --json must work the same as root --json.
    result = invoke(initialized_workspace, "next-action", "--json")
    assert result.exit_code == 0, result.stdout

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "next-action"
    assert payload["result"]["next_item"] == "fill_component"


def test_next_action_root_json_still_works(initialized_workspace: Path, invoke) -> None:
    import json

    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Test",
        "--request",
        "Test request.",
    )
    assert create.exit_code == 0, create.stdout

    result = invoke(initialized_workspace, "--json", "next-action")
    assert result.exit_code == 0, result.stdout

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "next-action"


def test_next_action_no_plans(tmp_path: Path) -> None:
    workspace = initialize_project(
        root=tmp_path,
        project_name="test",
        create_sibling_store=True,
    )
    result = compute_next_action(workspace)
    assert result["workspace_initialized"] is True
    assert result["next_item"] == "create_plan"
    assert result["plan_id"] is None


def test_next_action_empty_required_components(
    initialized_workspace: Path, invoke
) -> None:
    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Test",
        "--request",
        "Test request.",
    )
    assert create.exit_code == 0, create.stdout

    result, payload = (
        invoke(initialized_workspace, "--json", "next-action"),
        None,
    )
    import json

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["next_item"] == "fill_component"
    assert payload["result"]["plan_id"] == "plan-0001"


def test_next_action_with_explicit_plan_id(initialized_workspace: Path, invoke) -> None:
    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Test",
        "--request",
        "Test request.",
    )
    assert create.exit_code == 0, create.stdout

    import json

    result = invoke(initialized_workspace, "--json", "next-action", "plan-0001")
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["plan_id"] == "plan-0001"


def test_next_action_with_plan_option(initialized_workspace: Path, invoke) -> None:
    import json

    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Test",
        "--request",
        "Test request.",
    )
    assert create.exit_code == 0, create.stdout

    result = invoke(
        initialized_workspace,
        "--json",
        "next-action",
        "--plan",
        "plan-0001",
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["plan_id"] == "plan-0001"


def test_next_action_done_plan(initialized_workspace: Path, invoke) -> None:
    from tests.test_plan_status import _fill_required_components

    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Test",
        "--request",
        "Test request.",
    )
    assert create.exit_code == 0, create.stdout
    _fill_required_components(initialized_workspace, invoke)

    done = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "done",
        "--reason",
        "Ready.",
    )
    assert done.exit_code == 0, done.stdout

    import json

    result = invoke(initialized_workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["next_item"] == "handoff_ready"
    assert payload["result"]["plan_id"] == "plan-0001"


def test_next_action_prefers_active_plan(initialized_workspace: Path, invoke) -> None:
    for i in range(2):
        create = invoke(
            initialized_workspace,
            "plan",
            "create",
            "--title",
            f"Plan {i}",
            "--request",
            f"Request {i}.",
        )
        assert create.exit_code == 0, create.stdout

    import json

    result = invoke(initialized_workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["plan_id"] == "plan-0002"


def test_next_action_explicit_plan_overrides_active(
    initialized_workspace: Path, invoke
) -> None:
    for i in range(2):
        create = invoke(
            initialized_workspace,
            "plan",
            "create",
            "--title",
            f"Plan {i}",
            "--request",
            f"Request {i}.",
        )
        assert create.exit_code == 0, create.stdout

    import json

    result = invoke(initialized_workspace, "--json", "next-action", "plan-0001")
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["plan_id"] == "plan-0001"


def test_next_action_is_read_only(initialized_workspace: Path, invoke) -> None:
    import json

    # Run twice, confirm no side effects
    result1 = invoke(initialized_workspace, "--json", "next-action")
    result2 = invoke(initialized_workspace, "--json", "next-action")
    p1 = json.loads(result1.stdout)
    p2 = json.loads(result2.stdout)
    assert p1["result"] == p2["result"]


def _enable_planning_interview(
    workspace: Path, *, activation: str = "always", phrases: list[str] | None = None
) -> None:
    config = workspace / ".ledger" / "planledger" / "config.toml"
    block = "\n[prompt_profiles.planning_interview]\nenabled = true\n"
    block += f'activation = "{activation}"\n'
    if phrases is not None:
        joined = ", ".join(f'"{p}"' for p in phrases)
        block += f"trigger_phrases = [{joined}]\n"
    config.write_text(config.read_text(encoding="utf-8") + block, encoding="utf-8")


def test_next_action_ask_plan_question_when_profile_active(
    initialized_workspace: Path, invoke
) -> None:
    import json

    from tests.test_plan_status import _fill_required_components

    _enable_planning_interview(initialized_workspace)
    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Feature A",
        "--request",
        "Please plan feature A.",
    )
    assert create.exit_code == 0, create.stdout
    _fill_required_components(initialized_workspace, invoke)
    progress = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "in_progress",
        "--reason",
        "Planning in progress.",
    )
    assert progress.exit_code == 0, progress.stdout

    result = invoke(initialized_workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    assert payload["result"]["next_item"] == "ask_plan_question"
    assert payload["result"]["plan_id"] == "plan-0001"
    profile = payload["result"]["prompt_profile"]
    assert profile["name"] == "planning_interview"
    assert profile["enabled"] is True
    assert profile["active"] is True
    assert "agent_instruction" in payload["result"]


def test_next_action_answer_required_question_surfaces_first_one(
    initialized_workspace: Path, invoke
) -> None:
    import json

    from tests.test_plan_status import _fill_required_components

    _enable_planning_interview(initialized_workspace)
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
    invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "open_questions",
        "--text",
        "- [ ] REQUIRED: Should the new command preserve the existing output format?\n"
        "- [ ] REQUIRED: Should migration be backward-compatible?",
    )

    result = invoke(initialized_workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    assert payload["result"]["next_item"] == "answer_required_question"
    assert (
        payload["result"]["question"]
        == "Should the new command preserve the existing output format?"
    )
    assert payload["result"]["prompt_profile"]["active"] is True


def test_next_action_triggered_profile_without_trigger_is_normal(
    initialized_workspace: Path, invoke
) -> None:
    import json

    from tests.test_plan_status import _fill_required_components

    _enable_planning_interview(
        initialized_workspace, activation="triggered", phrases=["grill me"]
    )
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Feature A",
        "--request",
        "Please plan feature A normally.",
    )
    _fill_required_components(initialized_workspace, invoke)

    result = invoke(initialized_workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    assert payload["result"]["next_item"] == "mark_done_after_human_approval"
    profile = payload["result"]["prompt_profile"]
    assert profile["enabled"] is True
    assert profile["active"] is False


def test_next_action_fill_component_beats_ask_plan_question(
    initialized_workspace: Path, invoke
) -> None:
    import json

    _enable_planning_interview(initialized_workspace)
    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Feature A",
        "--request",
        "Please plan feature A.",
    )
    assert create.exit_code == 0, create.stdout

    result = invoke(initialized_workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    assert payload["result"]["next_item"] == "fill_component"


def _enable_planning_workshop_with_topics(
    workspace: Path,
    *,
    topics: list[str] | None = None,
    min_resolved: int = 0,
    max_required: int = 20,
) -> None:
    config = workspace / ".ledger" / "planledger" / "config.toml"
    block = (
        "\n[prompt_profiles.planning_workshop]\n"
        "enabled = true\n"
        'activation = "always"\n'
        'question_policy = "ask_one_at_a_time"\n'
        f"min_resolved_required_questions_before_done = {min_resolved}\n"
        f"max_required_questions = {max_required}\n"
    )
    if topics is not None:
        joined = ", ".join(f'"{t}"' for t in topics)
        block += f"required_question_topics = [{joined}]\n"
    config.write_text(config.read_text(encoding="utf-8") + block, encoding="utf-8")


def test_next_action_surfaces_first_required_topic_question(
    initialized_workspace: Path, invoke
) -> None:
    import json

    from tests.test_plan_status import _fill_required_components

    _enable_planning_workshop_with_topics(
        initialized_workspace,
        topics=["scope", "tests"],
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

    result = invoke(initialized_workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    res = payload["result"]
    assert res["next_item"] == "ask_plan_question"
    assert res["topic"] == "scope"
    assert "question" in res and res["question"]
    assert res["questions_remaining_count"] == 2
    assert res["prompt_profile"]["required_question_topics"] == ["scope", "tests"]


def test_next_action_advances_after_topic_resolved(
    initialized_workspace: Path, invoke
) -> None:
    import json

    from tests.test_plan_status import _fill_required_components

    _enable_planning_workshop_with_topics(
        initialized_workspace,
        topics=["scope", "tests"],
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
    # Resolve the first topic.
    invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "open_questions",
        "--text",
        "- [x] REQUIRED(scope): Should we limit scope? Answer: minimal only.",
    )

    result = invoke(initialized_workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    res = payload["result"]
    assert res["next_item"] == "ask_plan_question"
    assert res["topic"] == "tests"
    assert res["questions_remaining_count"] == 1


def test_next_action_stops_asking_once_topics_resolved(
    initialized_workspace: Path, invoke
) -> None:
    import json

    from tests.test_plan_status import _fill_required_components

    _enable_planning_workshop_with_topics(
        initialized_workspace,
        topics=["scope"],
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
    invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "open_questions",
        "--text",
        "- [x] REQUIRED(scope): Should we limit scope? Answer: minimal only.",
    )

    result = invoke(initialized_workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    res = payload["result"]
    # Topic queue exhausted and not in done state -> mark-done readiness.
    assert res["next_item"] in {
        "mark_done_after_human_approval",
        "fix_validation",
        "handoff_ready",
    }
    assert "topic" not in res


def test_next_action_topic_queue_beats_generic_ask(
    initialized_workspace: Path, invoke
) -> None:
    import json

    from tests.test_plan_status import _fill_required_components

    # planning_interview alias with no topics -> generic ask.
    _enable_planning_interview(initialized_workspace)
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

    result = invoke(initialized_workspace, "--json", "next-action")
    payload = json.loads(result.stdout)
    res = payload["result"]
    assert res["next_item"] == "ask_plan_question"
    assert "topic" not in res
