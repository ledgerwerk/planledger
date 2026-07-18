from __future__ import annotations

from pathlib import Path


def test_doctor_reports_healthy_workspace(
    initialized_workspace: Path, invoke_json
) -> None:
    result, payload = invoke_json(initialized_workspace, "doctor")

    assert result.exit_code == 0, result.stdout
    assert payload["result"]["healthy"] is True


def test_doctor_reports_old_schema_detection(
    initialized_workspace: Path, invoke_json
) -> None:
    legacy_dir = initialized_workspace / ".planledger" / "ledgers" / "main"
    legacy_dir.mkdir(parents=True)

    result, payload = invoke_json(initialized_workspace, "doctor")

    assert result.exit_code == 0, result.stdout
    assert payload["result"]["healthy"] is False
    assert payload["result"]["project_state"] == "canonical"
    assert any(
        "schema detected" in error.lower() for error in payload["result"]["errors"]
    )


def test_status_human_output(initialized_workspace: Path, invoke) -> None:
    result = invoke(initialized_workspace, "status")
    assert result.exit_code == 0, result.stdout
    lines = result.stdout.strip().split("\n")
    assert lines[0] == "Planledger status"
    assert any(line.startswith("Workspace:") for line in lines)
    assert any(line.startswith("Config:") for line in lines)
    assert any(line.startswith("Project:") for line in lines)
    assert any(line.startswith("Counts:") for line in lines)
    assert any("Health: not checked" in line for line in lines)
    assert any(line.startswith("Next:") for line in lines)


def test_status_no_check_does_not_run_doctor(
    initialized_workspace: Path, invoke
) -> None:
    result = invoke(initialized_workspace, "status")
    assert result.exit_code == 0, result.stdout
    assert "Health: not checked (use --check)" in result.stdout


def test_status_check_runs_doctor(initialized_workspace: Path, invoke) -> None:
    result = invoke(initialized_workspace, "status", "--check")
    assert result.exit_code == 0, result.stdout
    assert "Health: healthy" in result.stdout


def test_status_shows_active_plan(initialized_workspace: Path, invoke) -> None:
    invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Active Plan",
        "--request",
        "req",
    )
    result = invoke(initialized_workspace, "status")
    assert result.exit_code == 0, result.stdout
    assert "Active plan: plan-0001 Active Plan (new)" in result.stdout


def test_doctor_reports_configured_external_paths_when_storage_missing(
    tmp_path: Path, invoke_json
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config_path = root / ".planledger.toml"
    config_path.write_text(
        "[project]\n"
        'name = "External Project"\n'
        'uuid = "test-uuid"\n\n'
        "[storage]\n"
        'planledger_dir = "../planledger-state/planledger"\n',
        encoding="utf-8",
    )

    result, payload = invoke_json(root, "doctor")

    errors = payload["result"]["errors"]
    assert result.exit_code == 0, result.stdout
    assert payload["result"]["healthy"] is False
    assert payload["result"]["project_state"] == "legacy"
    assert payload["result"]["migration_required"] is True
    assert payload["result"]["legacy_config_path"] == str(config_path)
    assert any("legacy_config_found" in error for error in errors)
    assert payload["result"]["remediation"] == ["planledger migrate"]


def test_status_reports_configured_external_paths_when_storage_missing(
    tmp_path: Path, invoke_json
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    config_path = root / ".planledger.toml"
    config_path.write_text(
        "[project]\n"
        'name = "External Project"\n'
        'uuid = "test-uuid"\n\n'
        "[storage]\n"
        'planledger_dir = "../planledger-state/planledger"\n',
        encoding="utf-8",
    )

    result, payload = invoke_json(root, "status")

    assert result.exit_code == 0, result.stdout
    assert payload["result"]["initialized"] is False
    assert payload["result"]["project_state"] == "legacy"
    assert payload["result"]["migration_required"] is True
    assert payload["result"]["legacy_config_path"] == str(config_path)
    assert payload["result"]["next_command"] == "planledger migrate"
