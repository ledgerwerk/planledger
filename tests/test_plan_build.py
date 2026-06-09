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
