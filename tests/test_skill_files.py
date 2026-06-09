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


def test_config_has_no_taskledger_integration() -> None:
    config = (REPO_ROOT / "planledger.toml").read_text(encoding="utf-8")

    assert "integrations.taskledger" not in config
    assert "ledger_ref" not in config


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
