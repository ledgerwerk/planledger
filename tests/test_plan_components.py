from __future__ import annotations

from pathlib import Path

import yaml

from planledger.cli import app


def test_setting_component_increments_version_and_snapshots(
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
    update = invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "todo_items",
        "--text",
        "1. Split storage work.\n2. Update the CLI.",
    )

    assert create.exit_code == 0, create.stdout
    assert update.exit_code == 0, update.stdout

    plan_dir = initialized_workspace / ".planledger" / "plans" / "plan-0001"
    metadata = yaml.safe_load((plan_dir / "plan.yaml").read_text())
    rendered = (plan_dir / "rendered" / "latest.md").read_text()

    assert metadata["version"] == 2
    assert (plan_dir / "versions" / "v0001").is_dir()
    assert (plan_dir / "versions" / "v0002").is_dir()
    assert "Split storage work" in rendered


def test_unknown_component_fails_and_cancelled_plan_blocks_edits(
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
    unknown = invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "unknown_component",
        "--text",
        "text",
    )
    cancel = invoke(
        initialized_workspace,
        "plan",
        "cancel",
        "plan-0001",
        "--reason",
        "No longer needed.",
    )
    blocked = invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "summary",
        "--text",
        "Updated summary.",
    )

    assert create.exit_code == 0, create.stdout
    assert unknown.exit_code != 0
    assert cancel.exit_code == 0, cancel.stdout
    assert blocked.exit_code != 0
    assert "cancelled" in blocked.stdout


def test_component_set_uses_active_plan(
    initialized_workspace: Path, invoke
) -> None:
    invoke(
        initialized_workspace,
        "plan", "create", "--title", "Active", "--request", "req",
    )
    result = invoke(
        initialized_workspace,
        "plan", "component", "set", "summary", "--text", "Test summary.",
    )
    assert result.exit_code == 0, result.stdout


def test_component_set_plan_option_overrides_active(
    initialized_workspace: Path, invoke
) -> None:
    invoke(
        initialized_workspace,
        "plan", "create", "--title", "First", "--request", "req1",
    )
    invoke(
        initialized_workspace,
        "plan", "create", "--title", "Second", "--request", "req2",
    )
    result = invoke(
        initialized_workspace,
        "plan", "component", "set", "summary",
        "--plan", "plan-0001", "--text", "For first.",
    )
    assert result.exit_code == 0, result.stdout



def test_component_set_reads_from_stdin(initialized_workspace: Path, runner) -> None:
    create = runner.invoke(
        app,
        [
            "--cwd",
            str(initialized_workspace),
            "plan",
            "create",
            "--title",
            "Use stdin",
            "--request",
            "req",
        ],
    )
    update = runner.invoke(
        app,
        [
            "--cwd",
            str(initialized_workspace),
            "plan",
            "component",
            "set",
            "summary",
            "--stdin",
        ],
        input="Summary from stdin.\n",
    )

    assert create.exit_code == 0, create.stdout
    assert update.exit_code == 0, update.stdout
    summary = (
        initialized_workspace
        / ".planledger"
        / "plans"
        / "plan-0001"
        / "components"
        / "10-executive-verdict.md"
    ).read_text()
    assert summary == "Summary from stdin.\n"


def test_component_set_file_dash_reads_from_stdin(
    initialized_workspace: Path, runner
) -> None:
    create = runner.invoke(
        app,
        [
            "--cwd",
            str(initialized_workspace),
            "plan",
            "create",
            "--title",
            "Use dash",
            "--request",
            "req",
        ],
    )
    update = runner.invoke(
        app,
        [
            "--cwd",
            str(initialized_workspace),
            "plan",
            "component",
            "set",
            "context",
            "--file",
            "-",
        ],
        input="Context from stdin via dash.\n",
    )

    assert create.exit_code == 0, create.stdout
    assert update.exit_code == 0, update.stdout
    context = (
        initialized_workspace
        / ".planledger"
        / "plans"
        / "plan-0001"
        / "components"
        / "20-context.md"
    ).read_text()
    assert context == "Context from stdin via dash.\n"

