from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from planledger.storage import collect_inventory

pytestmark = pytest.mark.cli


def _create_plan(
    ws: Path, invoke, *, title: str, request: str = "Please plan this."
) -> None:
    result = invoke(ws, "plan", "create", "--title", title, "--request", request)
    assert result.exit_code == 0, result.stdout


def test_info_default_human_lists_plans_and_footprint(
    initialized_workspace: Path, invoke
) -> None:
    _create_plan(initialized_workspace, invoke, title="First plan")
    _create_plan(initialized_workspace, invoke, title="Second plan")

    result = invoke(initialized_workspace, "info")
    assert result.exit_code == 0, result.stdout
    out = result.stdout

    assert out.startswith("Planledger info")
    assert "Config:" in out
    assert "Storage:" in out
    # Fresh init + plan create stays at schema 4; info reports it as-is (read-only).
    assert "Schema: v4" in out
    assert "Plans (2):" in out
    assert "plan-0001" in out and "plan-0002" in out
    assert "First plan" in out and "Second plan" in out
    # a fresh plan has 1/12 components filled; the default table shows the fill column
    assert "1/12" in out
    assert "Workshops (0):" in out
    assert "(none)" in out
    assert "Disk footprint:" in out
    assert "total:" in out
    assert out.rstrip().endswith("Next: planledger next-action")
    for forbidden in (
        "sibling-ledger",
        "workspace_provider",
        "namespace",
        "scope",
        "plan/config.toml",
    ):
        assert forbidden not in out


def test_info_json_envelope_shape(initialized_workspace: Path, invoke_json) -> None:
    invoke_json(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Feature A",
        "--request",
        "Please plan feature A.",
    )

    result, payload = invoke_json(initialized_workspace, "info")
    assert result.exit_code == 0, result.stdout
    assert payload["ok"] is True
    assert payload["command"] == "info"
    assert payload["events"] == []

    r = payload["result"]
    assert r["initialized"] is True
    for key in (
        "root",
        "config_path",
        "planledger_dir",
        "storage_path",
        "project_name",
        "project_uuid",
        "ledger_code",
    ):
        assert key in r["workspace"], key
    assert r["workspace"]["ledger_code"] == "pl"
    # The new generic storage object replaces the old provider vocabulary.
    storage = r["storage"]
    for key in ("mount", "kind", "source", "path", "binding_path", "binding_status"):
        assert key in storage, key
    assert storage["mount"] == "data"
    assert storage["kind"] == "external"
    # The planledger state stays in its own ``state`` object.
    state = r["state"]
    assert state["schema_version"] == 4
    assert state["active_plan_id"] == "plan-0001"
    assert r["plan_count"] == 1
    assert r["workshop_count"] == 0
    assert r["plan_status_counts"] == {"new": 1}
    assert r["workshop_status_counts"] == {}

    entry = r["plans"][0]
    assert entry["plan_id"] == "plan-0001"
    assert entry["id"] == "plan-0001"
    assert entry["global_ref"] == "pl:plan-0001"
    assert entry["file_ref"] == "pl-plan-0001"
    assert entry["status"] == "new"
    assert entry["version"] == 1
    assert entry["path"].endswith("plan-0001")
    assert entry["latest_rendered_exists"] is True
    assert isinstance(entry["components"], dict)
    assert entry["components"]["request"] is True
    assert entry["components"]["summary"] is False  # empty component file
    assert entry["filled_components"] == 1
    assert entry["total_components"] == 12
    assert entry["size_bytes"] > 0
    assert isinstance(entry["versions"], list) and entry["versions"]
    assert r["size_bytes"]["workshops"] == 0
    assert r["size_bytes"]["total"] == r["size_bytes"]["plans"]
    assert r["total_size_bytes"] == r["size_bytes"]["total"]


def test_info_on_empty_initialized_workspace(
    initialized_workspace: Path, invoke, invoke_json
) -> None:
    result = invoke(initialized_workspace, "info")
    assert result.exit_code == 0, result.stdout
    assert "Plans (0):" in result.stdout
    assert "Workshops (0):" in result.stdout
    assert "total:      0 B" in result.stdout

    result2, payload = invoke_json(initialized_workspace, "info")
    r = payload["result"]
    assert r["plan_count"] == 0
    assert r["workshop_count"] == 0
    assert r["plans"] == []
    assert r["workshops"] == []
    assert r["total_size_bytes"] == 0
    assert r["plan_status_counts"] == {}


def test_info_reports_fill_state_and_missing_components(
    initialized_workspace: Path, invoke, invoke_json
) -> None:
    _create_plan(initialized_workspace, invoke, title="Partial")
    invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "summary",
        "--text",
        "A concise summary.",
    )
    invoke(
        initialized_workspace,
        "plan",
        "component",
        "set",
        "approach",
        "--text",
        "Recommended approach.",
    )
    # Simulate a missing component file (e.g. hand-edited storage).
    notes_path = (
        initialized_workspace
        / ".planledger"
        / "plans"
        / "plan-0001"
        / "components"
        / "99-notes.md"
    )
    assert notes_path.exists()
    notes_path.unlink()

    _, payload = invoke_json(initialized_workspace, "info")
    entry = payload["result"]["plans"][0]
    assert entry["components"]["request"] is True
    assert entry["components"]["summary"] is True
    assert entry["components"]["approach"] is True
    assert entry["components"]["notes"] is False  # missing file counts as not filled
    # request + summary + approach = 3 filled
    assert entry["filled_components"] == 3
    assert entry["total_components"] == 12


def test_info_plan_focus_narrows_to_one_record(
    initialized_workspace: Path, invoke, invoke_json
) -> None:
    _create_plan(initialized_workspace, invoke, title="Alpha")
    _create_plan(initialized_workspace, invoke, title="Beta")

    # local id narrowing, human output
    result = invoke(initialized_workspace, "info", "--plan", "plan-0002")
    assert result.exit_code == 0, result.stdout
    assert "Plan: plan-0002" in result.stdout
    assert "Beta" in result.stdout
    assert "Alpha" not in result.stdout
    assert "components (" in result.stdout
    assert "[x] request" in result.stdout

    # global ref narrowing via JSON
    _, payload = invoke_json(initialized_workspace, "info", "--plan", "pl:plan-0001")
    assert payload["result"]["focus"] == "plan"
    assert payload["result"]["plan"]["plan_id"] == "plan-0001"

    # not found
    missing = invoke(initialized_workspace, "info", "--plan", "plan-9999")
    assert missing.exit_code != 0
    assert "No plan matches" in missing.stdout


def test_info_plan_and_workshop_are_mutually_exclusive(
    initialized_workspace: Path, invoke
) -> None:
    _create_plan(initialized_workspace, invoke, title="Alpha")
    result = invoke(
        initialized_workspace,
        "info",
        "--plan",
        "plan-0001",
        "--workshop",
        "workshop-0001",
    )
    assert result.exit_code != 0
    assert "invalid_options" in result.stdout


def test_info_no_components_drops_fill_detail(
    initialized_workspace: Path, invoke, invoke_json
) -> None:
    _create_plan(initialized_workspace, invoke, title="X")

    result = invoke(initialized_workspace, "info", "--no-components")
    assert result.exit_code == 0, result.stdout
    assert "1/12" not in result.stdout  # fill column dropped from the table
    assert "[x]" not in result.stdout

    _, payload = invoke_json(initialized_workspace, "info", "--no-components")
    entry = payload["result"]["plans"][0]
    assert "components" not in entry  # per-component map removed
    assert entry["filled_components"] == 1  # aggregate counts retained
    assert entry["total_components"] == 12


def test_info_paths_only_reduces_output(
    initialized_workspace: Path, invoke, invoke_json
) -> None:
    _create_plan(initialized_workspace, invoke, title="X")

    result = invoke(initialized_workspace, "info", "--paths-only")
    assert result.exit_code == 0, result.stdout
    assert "Planledger info (paths)" in result.stdout
    assert "Disk footprint" not in result.stdout
    assert "Schema:" not in result.stdout
    assert "rendered:" in result.stdout
    assert "latest.md" in result.stdout

    _, payload = invoke_json(initialized_workspace, "info", "--paths-only")
    r = payload["result"]
    entry = r["plans"][0]
    assert set(entry) == {
        "plan_id",
        "path",
        "latest_rendered_path",
        "latest_rendered_exists",
    }
    assert entry["plan_id"] == "plan-0001"


def test_info_includes_workshops_when_present(
    initialized_workspace: Path, invoke, invoke_json
) -> None:
    result = invoke(
        initialized_workspace,
        "workshop",
        "create",
        "--title",
        "Explore feature",
        "--request",
        "Shape this feature.",
    )
    assert result.exit_code == 0, result.stdout

    result = invoke(initialized_workspace, "info")
    assert "Workshops (1):" in result.stdout
    assert "workshop-0001" in result.stdout

    _, payload = invoke_json(initialized_workspace, "info")
    r = payload["result"]
    assert r["workshop_count"] == 1
    entry = r["workshops"][0]
    assert entry["workshop_id"] == "workshop-0001"
    assert entry["global_ref"] == "pl:workshop-0001"
    assert isinstance(entry["components"], dict)
    assert entry["components"]["request"] is True


def test_collect_inventory_is_readonly_and_does_not_migrate_schema(
    initialized_workspace: Path,
) -> None:
    from planledger.project_context import load_workspace as load_canonical

    workspace = load_canonical(initialized_workspace)
    storage_yaml_path = workspace.storage_path
    before = yaml.safe_load(storage_yaml_path.read_text())
    assert before["schema_version"] == 4  # fresh init writes schema_version 4

    inventory = collect_inventory(workspace)

    # Reported as-is, not mutated by the read-only inventory walk.
    assert inventory["state"]["schema_version"] == 4
    assert inventory["plan_count"] == 0
    assert inventory["workshop_count"] == 0

    after = yaml.safe_load(storage_yaml_path.read_text())
    assert after["schema_version"] == 4
    assert after == before  # no write occurred at all


def test_info_command_envelope_parses_as_json(
    initialized_workspace: Path, invoke
) -> None:
    _create_plan(initialized_workspace, invoke, title="X")
    result = invoke(initialized_workspace, "--json", "info")
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "info"
