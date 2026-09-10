from __future__ import annotations

from pathlib import Path

import yaml

from planledger.cli import app


def test_plan_create_builds_component_layout_and_rendered_artifact(
    initialized_workspace: Path, invoke
) -> None:
    first = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Add feature A",
        "--request",
        "Please review how we can add feature A.",
    )
    second = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Add feature B",
        "--request",
        "Please review how we can add feature B.",
    )

    assert first.exit_code == 0, first.stdout
    assert second.exit_code == 0, second.stdout

    plan_dir = initialized_workspace / ".planledger" / "plans" / "plan-0001"
    metadata = yaml.safe_load((plan_dir / "plan.yaml").read_text())

    assert metadata["id"] == "plan-0001"
    assert metadata["status"] == "new"
    assert metadata["version"] == 1
    assert (plan_dir / "components").is_dir()
    assert (plan_dir / "rendered" / "latest.md").exists()
    assert (plan_dir / "versions" / "v0001").is_dir()
    assert (initialized_workspace / ".planledger" / "plans" / "plan-0002").is_dir()
    assert not (initialized_workspace / ".planledger" / "ledgers" / "main").exists()


def test_plan_create_sets_active_plan(initialized_workspace: Path, invoke) -> None:
    result = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Add feature A",
        "--request",
        "Please review how we can add feature A.",
    )
    assert result.exit_code == 0, result.stdout

    storage = yaml.safe_load(
        (initialized_workspace / ".planledger" / "storage.yaml").read_text()
    )
    assert storage["active_plan_id"] == "plan-0001"


def test_plan_create_replaces_active_plan(initialized_workspace: Path, invoke) -> None:
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "First",
        "--request",
        "First request.",
    )
    second = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Second",
        "--request",
        "Second request.",
    )
    assert second.exit_code == 0, second.stdout

    storage = yaml.safe_load(
        (initialized_workspace / ".planledger" / "storage.yaml").read_text()
    )
    assert storage["active_plan_id"] == "plan-0002"


def test_plan_create_reads_request_file_and_snapshots_content(
    initialized_workspace: Path, invoke, tmp_path: Path
) -> None:
    request_file = tmp_path / "request.md"
    content = "# Review\n\nUnicode: café \u2603\n\n- preserve this Markdown\n"
    request_file.write_text(content, encoding="utf-8")

    result = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "File request",
        "--request-file",
        str(request_file),
    )

    assert result.exit_code == 0, result.stdout
    stored = (
        initialized_workspace
        / ".planledger"
        / "plans"
        / "plan-0001"
        / "components"
        / "00-request.md"
    )
    assert stored.read_text(encoding="utf-8") == content

    request_file.write_text("changed", encoding="utf-8")
    request_file.unlink()
    assert stored.read_text(encoding="utf-8") == content


def test_plan_create_request_file_dash_reads_stdin(
    initialized_workspace: Path, runner
) -> None:
    result = runner.invoke(
        app,
        [
            "--cwd",
            str(initialized_workspace),
            "plan",
            "create",
            "--title",
            "Stdin request",
            "--request-file",
            "-",
        ],
        input="Request from stdin.\n",
    )

    assert result.exit_code == 0, result.stdout
    stored = (
        initialized_workspace
        / ".planledger"
        / "plans"
        / "plan-0001"
        / "components"
        / "00-request.md"
    )
    assert stored.read_text(encoding="utf-8") == "Request from stdin.\n"


def test_plan_create_request_sources_are_exclusive(
    initialized_workspace: Path, invoke, tmp_path: Path
) -> None:
    request_file = tmp_path / "request.md"
    request_file.write_text("file", encoding="utf-8")
    result = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Invalid sources",
        "--request",
        "inline",
        "--request-file",
        str(request_file),
    )

    assert result.exit_code != 0
    assert "--request, --request-file, or --stdin" in result.stdout


def test_plan_create_request_input_errors_use_public_options(
    initialized_workspace: Path, invoke, tmp_path: Path
) -> None:
    missing = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Missing request",
    )
    assert missing.exit_code != 0
    assert "--request, --request-file, or --stdin" in missing.stdout

    not_found = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Missing file",
        "--request-file",
        str(tmp_path / "missing.md"),
    )
    assert not_found.exit_code != 0
    assert "not_found" in not_found.stdout
    assert "Traceback" not in not_found.stdout


def test_workshop_create_reads_request_file(
    initialized_workspace: Path, invoke, tmp_path: Path
) -> None:
    request_file = tmp_path / "workshop-request.md"
    content = "Shape this feature.\n\n- Given a file\n"
    request_file.write_text(content, encoding="utf-8")

    result = invoke(
        initialized_workspace,
        "workshop",
        "create",
        "--title",
        "File workshop",
        "--request-file",
        str(request_file),
    )

    assert result.exit_code == 0, result.stdout
    stored = (
        initialized_workspace
        / ".planledger"
        / "workshops"
        / "workshop-0001"
        / "components"
        / "request.md"
    )
    assert stored.read_text(encoding="utf-8") == content
