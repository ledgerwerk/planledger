from __future__ import annotations

from pathlib import Path

import yaml

from tests.test_plan_status import _fill_required_components


def test_build_is_deterministic_and_standalone(
    initialized_workspace: Path, invoke, tmp_path: Path
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

    before_version = yaml.safe_load(
        (
            initialized_workspace / ".planledger" / "plans" / "plan-0001" / "plan.yaml"
        ).read_text()
    )["version"]
    first = invoke(initialized_workspace, "plan", "build", "plan-0001", "--print")
    second = invoke(initialized_workspace, "plan", "build", "plan-0001", "--print")
    out_path = tmp_path / "handoff.md"
    out_build = invoke(
        initialized_workspace,
        "plan",
        "build",
        "plan-0001",
        "--out",
        str(out_path),
    )
    after_version = yaml.safe_load(
        (
            initialized_workspace / ".planledger" / "plans" / "plan-0001" / "plan.yaml"
        ).read_text()
    )["version"]

    assert first.exit_code == 0, first.stdout
    assert second.exit_code == 0, second.stdout
    assert out_build.exit_code == 0, out_build.stdout
    assert first.stdout == second.stdout
    assert "## Proposed approach" in first.stdout
    assert "## Risks and mitigations" in first.stdout
    assert ".planledger/plans/" not in first.stdout
    assert (
        out_path.read_text()
        == (
            initialized_workspace
            / ".planledger"
            / "plans"
            / "plan-0001"
            / "rendered"
            / "latest.md"
        ).read_text()
    )
    assert before_version == after_version


def test_build_uses_active_plan(initialized_workspace: Path, invoke) -> None:
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Active",
        "--request",
        "req",
    )
    _fill_required_components(initialized_workspace, invoke)
    result = invoke(
        initialized_workspace,
        "plan",
        "build",
        "--print",
    )
    assert result.exit_code == 0, result.stdout
    assert "## Proposed approach" in result.stdout


def test_export_writes_active_plan_to_workspace_root(
    initialized_workspace: Path, invoke
) -> None:
    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Export me",
        "--request",
        "Need a readable handoff.",
    )
    assert create.exit_code == 0, create.stdout
    _fill_required_components(initialized_workspace, invoke)

    before_metadata = yaml.safe_load(
        (
            initialized_workspace / ".planledger" / "plans" / "plan-0001" / "plan.yaml"
        ).read_text()
    )
    result = invoke(initialized_workspace, "plan", "export")
    after_metadata = yaml.safe_load(
        (
            initialized_workspace / ".planledger" / "plans" / "plan-0001" / "plan.yaml"
        ).read_text()
    )

    exported = initialized_workspace / "plan-0001.md"
    latest = (
        initialized_workspace
        / ".planledger"
        / "plans"
        / "plan-0001"
        / "rendered"
        / "latest.md"
    )

    assert result.exit_code == 0, result.stdout
    assert "Exported plan-0001" in result.stdout
    assert exported.exists()
    assert exported.read_text() == latest.read_text()
    assert before_metadata["version"] == after_metadata["version"]


def test_export_relative_out_is_workspace_relative(
    initialized_workspace: Path, invoke
) -> None:
    create = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Export relative",
        "--request",
        "Need a readable handoff.",
    )
    assert create.exit_code == 0, create.stdout
    _fill_required_components(initialized_workspace, invoke)

    result = invoke(
        initialized_workspace,
        "plan",
        "export",
        "--out",
        "handoffs/current-plan.md",
    )

    exported = initialized_workspace / "handoffs" / "current-plan.md"
    assert result.exit_code == 0, result.stdout
    assert exported.exists()
    assert str(exported) in result.stdout


def test_self_heading_components_render_without_wrapper_heading(
    initialized_workspace: Path, invoke
) -> None:
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Implementation brief",
        "--request",
        "Original request",
    )
    _fill_required_components(initialized_workspace, invoke)
    summary = invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "summary",
        "--text",
        "## Purpose\n\nExplain the change.",
    )
    assert summary.exit_code == 0, summary.stdout

    result = invoke(
        initialized_workspace,
        "plan",
        "build",
        "plan-0001",
        "--print",
    )
    assert result.exit_code == 0, result.stdout
    assert "## Purpose\n\nExplain the change." in result.stdout
    assert "## Executive verdict\n\n## Purpose" not in result.stdout


def test_default_handoff_uses_v2_frontmatter_without_noise(
    initialized_workspace: Path, invoke
) -> None:
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Clean handoff",
        "--request",
        "Do not repeat me.",
    )
    _fill_required_components(initialized_workspace, invoke)

    result = invoke(
        initialized_workspace,
        "plan",
        "build",
        "plan-0001",
        "--print",
    )

    assert result.exit_code == 0, result.stdout
    assert "planledger_schema: planledger.rendered_plan.v2" in result.stdout
    assert "# Clean handoff" in result.stdout
    assert "Do not repeat me." not in result.stdout
    assert "Plan: `plan-0001`" not in result.stdout
    assert "## Change history" not in result.stdout


def test_render_compatibility_flags_include_request_and_history(
    initialized_workspace: Path, invoke
) -> None:
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Compatible handoff",
        "--request",
        "Include this.",
    )
    _fill_required_components(initialized_workspace, invoke)

    result = invoke(
        initialized_workspace,
        "plan",
        "build",
        "plan-0001",
        "--print",
        "--include-request",
        "--include-history",
    )

    assert result.exit_code == 0, result.stdout
    assert "## Original request" in result.stdout
    assert "Include this." in result.stdout
    assert "## Change history" in result.stdout


def test_implementation_brief_workflow_exports_standalone_sections(
    initialized_workspace: Path, invoke, tmp_path: Path
) -> None:
    created = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "File-driven recovery brief",
        "--request",
        "Review the dependency upgrade.",
    )
    assert created.exit_code == 0, created.stdout

    components = {
        "summary": (
            "## Purpose\n\nRecover the repository after the dependency upgrade.\n\n"
            "## Executive verdict\n\nFix the primary regression first."
        ),
        "context": (
            "## Root cause analysis\n\nObserved baseline: one integration failure."
        ),
        "approach": (
            "## Required correction\n\nMake the ownership fix, then run the suite."
        ),
        "todo_items": (
            "## Detailed implementation sequence\n\n"
            "### TODO-001: Fix the integration boundary\n\n"
            "**Target files**\n\n"
            "- [`planledger/cli.py`](planledger/cli.py)\n\n"
            "**Acceptance criteria**\n\n"
            "- [ ] The upgraded dependency path works.\n\n"
            "**Validation**\n\n"
            "- `python -m pytest tests/test_plan_build.py -q`"
        ),
        "target_files": "- [`planledger/cli.py`](planledger/cli.py)",
        "validation": (
            "## Full acceptance checklist\n\n"
            "- [ ] Focused regression passes.\n\n"
            "- `python -m pytest tests/test_plan_build.py -q`"
        ),
        "risks": "- Risk: scope creep. Mitigation: keep the correction bounded.",
        "notes": (
            "## Non-goals\n\nNo unrelated refactor.\n\n"
            "## Final recommendation\n\nImplement the correction and verify the suite."
        ),
    }
    for component, content in components.items():
        result = invoke(
            initialized_workspace,
            "plan",
            "component",
            "set",
            component,
            "--text",
            content,
        )
        assert result.exit_code == 0, result.stdout

    build = invoke(initialized_workspace, "plan", "build", "plan-0001")
    validate = invoke(initialized_workspace, "plan", "validate", "plan-0001")
    done = invoke(
        initialized_workspace,
        "plan",
        "status",
        "plan-0001",
        "done",
        "--reason",
        "Implementation brief is ready for handoff.",
    )
    output = tmp_path / "file_driven_implementation_brief.md"
    exported = invoke(
        initialized_workspace,
        "plan",
        "export",
        "plan-0001",
        "--out",
        str(output),
    )

    assert build.exit_code == 0, build.stdout
    assert validate.exit_code == 0, validate.stdout
    assert done.exit_code == 0, done.stdout
    assert exported.exit_code == 0, exported.stdout
    text = output.read_text(encoding="utf-8")
    for section in (
        "# File-driven recovery brief",
        "## Purpose",
        "## Executive verdict",
        "## Detailed implementation sequence",
        "## Full acceptance checklist",
        "## Non-goals",
        "## Final recommendation",
        "planledger_schema: planledger.rendered_plan.v2",
        "planledger/cli.py",
        "python -m pytest tests/test_plan_build.py -q",
    ):
        assert section in text
