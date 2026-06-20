from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_readme_describes_plan_only_product() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "structured, versioned implementation plans" in readme
    assert "not a task manager" in readme
    assert "rendered Markdown" in readme
    assert "goal create" not in readme
    assert "taskledger push-plan" not in readme


def test_skill_describes_plan_only_workflow() -> None:
    skill = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "create a new independent plan" in skill.lower()
    assert "external task records" in skill.lower()
    assert "rendered Markdown path" in skill
    assert "todo_items" in skill
    assert "implementation_steps" not in skill
    assert "snapshot export" not in skill
    assert "taskledger tasks" not in skill
    assert "pl:plan-000X" in skill
    assert "global_id" in skill
    assert "Do not store or recommend a `global_id`" in skill


def test_config_has_no_taskledger_integration() -> None:
    config = (REPO_ROOT / "planledger.toml").read_text(encoding="utf-8")

    assert "integrations.taskledger" not in config
    assert "ledger_ref" not in config
    assert 'code = "pl"' in config


def test_examples_use_current_schema() -> None:
    import json

    examples_dir = REPO_ROOT / "examples"
    for path in sorted(examples_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema"] == "planledger.structured_plan.v1", (
            f"{path.name} uses stale schema"
        )
        for stale in (
            "goal",
            "initiative",
            "milestone",
            "slice",
            "ready_for_taskledger",
        ):
            assert stale not in json.dumps(data), (
                f"{path.name} contains stale key {stale!r}"
            )


def test_no_stale_references_in_product_files() -> None:
    import subprocess

    result = subprocess.run(
        [
            "grep",
            "-R",
            "-n",
            "-E",
            "integrations\\.taskledger|ready_for_taskledger|taskledger push-plan",
            "--include=*.py",
            "--include=*.md",
            "--include=*.toml",
            "--include=*.json",
            "--exclude-dir=.git",
            "--exclude-dir=__pycache__",
            "--exclude-dir=.planledger",
            "--exclude-dir=.taskledger",
            "--exclude=context_planledger.md",
            "--exclude=todo.md",
            "--exclude=plan.md",
            "--exclude=test_skill_files.py",
            str(REPO_ROOT),
        ],
        capture_output=True,
        text=True,
    )
    # grep exits 1 when no matches found, which is what we want
    matches = result.stdout.strip()
    assert not matches, f"Stale references found:\n{matches}"


def test_skill_has_taskledger_style_agent_protocol_without_taskledger_scope() -> None:
    skill = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    required_sections = (
        "## When to use this skill",
        "## Never do these things",
        "## Core agent command path",
        "## Fresh context entry protocol",
        "## Planning protocol",
        "## Question protocol",
        "## Done-gate protocol",
        "## CLI failure protocol",
        "## Final response contract",
    )
    for section in required_sections:
        assert section in skill, f"Missing section: {section}"

    required_phrases = (
        "planledger --json status",
        "planledger init",
        "create a new independent plan",
        "do not invent",
        "open_questions",
        "planledger plan build",
        "planledger plan validate",
        "rendered Markdown",
        ".planledger.toml",
        "storage.planledger_dir",
        "configured Planledger storage directory",
    )
    for phrase in required_phrases:
        assert phrase.lower() in skill.lower(), f"Missing phrase: {phrase}"

    # Phrases that must not appear in the skill, even in the "Never do" section.
    # Use phrases that imply active usage rather than prohibition.
    forbidden_phrases = (
        "taskledger ",
        "lock show",
        "branch-scoped ledger",
        "plan accept",
        "todo done",
    )
    skill_lower = skill.lower()
    for phrase in forbidden_phrases:
        assert phrase.lower() not in skill_lower, f"Forbidden phrase found: {phrase}"

    # implementation run / implementation runs are allowed only in the
    # "Never do these things" section where they are explicitly forbidden.
    never_do_section = skill_lower.split("## never do these things", 1)
    assert len(never_do_section) > 1, "Missing Never do these things section"
    after_never_do = never_do_section[1]
    next_section_split = after_never_do.split("\n## ", 1)
    rest_of_skill = never_do_section[0] + (
        next_section_split[1] if len(next_section_split) > 1 else ""
    )
    assert "implementation run" not in rest_of_skill, (
        "'implementation run' must only appear in the Never do section"
    )


def test_skill_has_read_command_table() -> None:
    skill = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text(
        encoding="utf-8"
    )

    assert "## Which read command to use" in skill
    assert "planledger --json status" in skill
    assert "planledger --json doctor" in skill
    assert "planledger --json plan list" in skill
    assert "planledger --json plan show" in skill
    assert "planledger --json plan show --plan PLAN_ID" in skill
    assert "planledger plan show --rendered" in skill
    assert "planledger --json plan component list" in skill
    assert "planledger plan component show COMPONENT" in skill
    assert "planledger --json plan versions" in skill
    assert "planledger plan diff --from" in skill
    assert "planledger next-action" in skill


def test_skill_documents_planning_interview_profile() -> None:
    skill = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    skill_lower = skill.lower()

    assert "## Planning interview profile protocol" in skill
    assert 'prompt_profile.name == "planning_interview"' in skill
    assert "ask exactly one question" in skill_lower
    assert "include a recommended answer" in skill_lower
    assert "inspect repository files" in skill_lower or (
        "inspect the repository" in skill_lower
    )
    assert "stop and wait for the user" in skill_lower
    assert "- [ ] REQUIRED:" in skill
    assert "- [x] REQUIRED:" in skill
    # No separate grilling / planning-interview skill is introduced.
    assert "skills/grilling" not in skill_lower
    assert "skills/planning-interview" not in skill_lower
    assert "skills/design-review" not in skill_lower


def test_no_separate_planning_interview_skill_directory() -> None:
    skills_dir = REPO_ROOT / "skills"
    for name in ("grilling", "planning-interview", "design-review"):
        assert not (skills_dir / name).exists(), f"Unexpected skill dir: {name}"


def test_skill_documents_next_action_checkpoint_loop() -> None:
    skill = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    skill_lower = skill.lower()

    assert "## next-action checkpoint protocol" in skill
    assert "planledger --json next-action --plan PLAN_ID" in skill
    assert "fill_component" in skill
    assert "answer_required_question" in skill
    assert "ask_plan_question" in skill
    assert "fix_validation" in skill
    assert "mark_done_after_human_approval" in skill
    assert "handoff_ready" in skill
    assert "do not mark a plan `done` until `next-action`" in skill_lower
    assert "planledger next-action --json" not in skill


def test_skill_documents_workshop_vs_plan_routing() -> None:
    skill = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    skill_lower = skill.lower()

    assert "## Routing protocol: workshop vs plan" in skill
    assert "Use a workshop first" in skill
    assert "Use a plan directly" in skill
    assert "planledger workshop create" in skill
    assert "planledger plan create --from-workshop" in skill
    assert "coding-agent handoff" in skill_lower
    assert "Do not ask the user which mode" in skill
    assert "Prefer workshop-first" in skill


def test_skill_documents_plan_apply_dry_run_policy() -> None:
    skill = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    skill_lower = skill.lower()

    assert "planledger plan apply --file - --dry-run" in skill
    assert "large multi-component updates" in skill_lower
    assert "json is hand-written" in skill_lower
    assert "small targeted updates" in skill_lower
    assert "direct `planledger plan apply --file -` is acceptable" in skill
    assert "Do not force temporary files" in skill
