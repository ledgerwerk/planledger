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
    # Default canonical config ships the planning_workshop profile enabled.
    profiles = r["prompt_profiles"]
    assert any(
        profile["name"] == "planning_workshop" for profile in profiles
    )
    # Status must not emit the deprecated storage vocabulary at the top level.
    for forbidden in (
        "workspace_provider",
        "store_root",
        "store_marker_path",
        "mount_storage",
        "mount_scope",
        "mount_source",
    ):
        assert forbidden not in r


def test_info_json_envelope_contract(initialized_workspace: Path, invoke_json) -> None:
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

    result, payload = invoke_json(initialized_workspace, "info")
    assert result.exit_code == 0, result.stdout
    assert payload["ok"] is True
    assert payload["command"] == "info"
    assert payload["events"] == []
    r = payload["result"]
    # Stable inventory contract surface that agents may parse.
    for key in (
        "initialized",
        "workspace",
        "storage",
        "plan_status_counts",
        "workshop_status_counts",
        "plan_count",
        "workshop_count",
        "plans",
        "workshops",
        "size_bytes",
        "total_size_bytes",
    ):
        assert key in r, key
    for key in ("plans", "workshops", "total"):
        assert key in r["size_bytes"], key
    plan_entry = r["plans"][0]
    for key in (
        "plan_id",
        "global_ref",
        "file_ref",
        "title",
        "status",
        "version",
        "path",
        "latest_rendered_path",
        "latest_rendered_exists",
        "components",
        "filled_components",
        "total_components",
        "versions",
        "size_bytes",
    ):
        assert key in plan_entry, key
