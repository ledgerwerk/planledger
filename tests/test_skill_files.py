from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_skill_md_exists():
    skill_path = REPO_ROOT / "skills" / "planledger" / "SKILL.md"
    assert skill_path.exists(), f"Missing skill file: {skill_path}"


def test_skill_md_contains_bundle_reference():
    content = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text()
    assert "planledger.plan_bundle.v1" in content


def test_skill_md_contains_workflow():
    content = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text()
    assert "Default workflow" in content


def test_readme_exists():
    readme_path = REPO_ROOT / "skills" / "planledger" / "README.md"
    assert readme_path.exists(), f"Missing readme: {readme_path}"


def test_readme_mentions_install_path():
    content = (REPO_ROOT / "skills" / "planledger" / "README.md").read_text()
    assert "~/.agents/skills" in content


def test_skill_not_inside_python_package():
    skill_in_pkg = REPO_ROOT / "planledger" / "skill"
    assert not skill_in_pkg.exists(), "Skill should not be inside the Python package"


def test_no_skill_cli_command():
    """The skill is not a Python module inside planledger package."""
    skill_module = REPO_ROOT / "planledger" / "skill.py"
    skill_dir = REPO_ROOT / "planledger" / "skill"
    assert not skill_module.exists()
    assert not skill_dir.exists()


def test_skill_requires_planledger_cli_use():
    content = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text()
    assert "MUST use the planledger CLI" in content
    assert "Reading this skill is not sufficient" in content


def test_skill_requires_dry_run_before_apply():
    content = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text()
    dry_run_pos = content.index("bundle apply --file bundle.json --dry-run")
    apply_pos = content.index("bundle apply --file bundle.json", dry_run_pos + 1)
    assert dry_run_pos < apply_pos


def test_skill_uses_returned_plan_id_for_taskledger():
    content = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text()
    assert "result.plan_id" in content
    assert "Never hardcode `plan-0001`" in content
    assert "taskledger detect" in content
    assert "push-plan <result.plan_id> --create-tasks" in content


def test_skill_mentions_evolving_goal_lifecycle():
    content = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text()
    assert "exploring" in content
    assert "fulfilled" in content
    assert "cancelled" in content


def test_skill_prevents_resurrecting_cancelled_goals():
    content = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text()
    assert "Do not resurrect cancelled goals" in content
    assert "Never treat `cancelled`, `fulfilled`, or `superseded` goals as pending work." in content


def test_skill_blocks_taskledger_handoff_during_shaping():
    content = (REPO_ROOT / "skills" / "planledger" / "SKILL.md").read_text()
    assert "Do not create taskledger tasks." in content
    assert "Do not push to taskledger during shaping." in content
