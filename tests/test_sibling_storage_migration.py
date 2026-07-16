from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from planledger.cli import app
from planledger.id_inventory import scan_plan_allocations, scan_workshop_allocations
from planledger.project_context import load_workspace
from planledger.storage import create_plan, create_workshop, initialize_project


def _invoke(root: Path, *args: str):
    return CliRunner().invoke(app, ["--cwd", str(root), *args])


def test_init_uses_direct_sibling_store_and_schema_four(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()
    (tmp_path / "ledger" / ".ledger-store").touch()

    result = _invoke(project, "init", "--project-name", "demo")
    assert result.exit_code == 0, result.stdout
    workspace = load_workspace(project)
    assert workspace.planledger_dir == tmp_path / "ledger" / "plan" / "planledger"
    assert workspace.workspace_provider == "sibling-ledger"
    assert yaml.safe_load(workspace.storage_path.read_text()) == {
        "schema_version": 4,
        "active_plan_id": None,
        "active_workshop_id": None,
        "created_at": yaml.safe_load(workspace.storage_path.read_text())["created_at"],
        "updated_at": yaml.safe_load(workspace.storage_path.read_text())["updated_at"],
    }
    assert not (project / ".ledger" / "plan" / "local.toml").exists()
    assert not (tmp_path / "ledger" / "projects").exists()


def test_init_requires_explicit_sibling_store_creation(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = _invoke(project, "init")
    assert result.exit_code != 0
    assert "PLANLEDGER_SIBLING_ROOT_MISSING" in result.stdout

    result = _invoke(project, "init", "--create-sibling-store")
    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "ledger" / ".ledger-store").is_file()


def test_allocations_are_derived_without_persisted_counters(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()
    (tmp_path / "ledger" / ".ledger-store").touch()
    workspace = initialize_project(project, "demo")
    create_plan(workspace, "one", "request")
    create_workshop(workspace, "one", "request")
    plan_inventory = scan_plan_allocations(workspace)
    workshop_inventory = scan_workshop_allocations(workspace)
    assert plan_inventory.next_id == "plan-0002"
    assert workshop_inventory.next_id == "workshop-0002"
    state = yaml.safe_load(workspace.storage_path.read_text())
    assert "next_plan_id" not in state
    assert "next_workshop_id" not in state


def test_migration_inspection_is_read_only(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    result = _invoke(project, "migrate")
    assert result.exit_code == 0, result.stdout
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    assert before == after
    assert "uninitialized" in result.stdout


def test_status_reports_canonical_paths(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()
    (tmp_path / "ledger" / ".ledger-store").touch()
    assert _invoke(project, "init").exit_code == 0
    result = _invoke(project, "--json", "status", "--check")
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    status = payload["result"]
    assert status["workspace_provider"] == "sibling-ledger"
    assert status["planledger_dir"].endswith("ledger/plan/planledger")
    assert status["health"]["healthy"] is True
