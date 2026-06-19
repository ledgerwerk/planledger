from __future__ import annotations

from pathlib import Path


def test_json_success_envelope(initialized_workspace: Path, invoke_json) -> None:
    result, payload = invoke_json(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Add feature A",
        "--request",
        "Please review how we can add feature A.",
    )

    assert result.exit_code == 0, result.stdout
    assert payload["ok"] is True
    assert payload["command"] == "plan.create"
    assert "result" in payload
    assert payload["events"] == []


def test_json_error_envelope(initialized_workspace: Path, invoke_json) -> None:
    create_result, _ = invoke_json(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Add feature A",
        "--request",
        "Please review how we can add feature A.",
    )
    result, payload = invoke_json(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "unknown_component",
        "--text",
        "text",
    )

    assert create_result.exit_code == 0, create_result.stdout
    assert result.exit_code != 0
    assert payload["ok"] is False
    assert payload["command"] == "plan.component.set"
    assert set(payload["error"]) >= {"code", "message", "remediation"}


def test_status_json_envelope(initialized_workspace: Path, invoke_json) -> None:
    result, payload = invoke_json(initialized_workspace, "status")
    assert result.exit_code == 0, result.stdout
    assert payload["ok"] is True
    assert payload["command"] == "status"
    r = payload["result"]
    assert r["initialized"] is True
    assert "root" in r
    assert "config_path" in r
    assert "project_name" in r
    assert "project_uuid" in r
    assert "plan_count" in r
    assert "status_counts" in r
    assert "active_plan" in r
    assert isinstance(r["health"], dict)
    assert r["health"]["checked"] is False


def test_status_json_exposes_prompt_profiles(
    initialized_workspace: Path, invoke_json
) -> None:
    result, payload = invoke_json(initialized_workspace, "status")
    assert result.exit_code == 0, result.stdout
    r = payload["result"]
    assert "prompt_profiles" in r
    assert r["prompt_profiles"] == []

    config = initialized_workspace / "planledger.toml"
    config.write_text(
        config.read_text(encoding="utf-8")
        + "\n[prompt_profiles.planning_interview]\nenabled = true\n"
        + 'activation = "always"\n',
        encoding="utf-8",
    )

    result, payload = invoke_json(initialized_workspace, "status")
    assert result.exit_code == 0, result.stdout
    profiles = payload["result"]["prompt_profiles"]
    assert len(profiles) == 1
    assert profiles[0]["name"] == "planning_interview"
    assert profiles[0]["enabled"] is True
    assert profiles[0]["activation"] == "always"
