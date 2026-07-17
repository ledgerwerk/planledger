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


def test_init_uses_uuid_scoped_sibling_store_and_schema_four(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()
    (tmp_path / "ledger" / ".ledger-store").touch()

    result = _invoke(project, "init", "--project-name", "demo")
    assert result.exit_code == 0, result.stdout
    workspace = load_workspace(project)
    expected = tmp_path / "ledger" / "planledger" / workspace.project_uuid
    assert workspace.planledger_dir == expected
    assert workspace.workspace_provider == "sibling-ledger"
    state = yaml.safe_load(workspace.storage_path.read_text())
    assert state == {
        "schema_version": 4,
        "active_plan_id": None,
        "active_workshop_id": None,
        "created_at": state["created_at"],
        "updated_at": state["updated_at"],
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
    assert Path(status["planledger_dir"]).name == status["project_uuid"]
    assert Path(status["planledger_dir"]).parts[-2] == "planledger"
    assert status["health"]["healthy"] is True


def _write_legacy_project(project: Path, source: Path, project_uuid: str) -> None:
    project.mkdir()
    (project / ".ledger").mkdir()
    (project / ".ledger" / "ledger.toml").write_text(
        "schema_version = 2\n"
        "[project]\n"
        f'uuid = "{project_uuid}"\n'
        f'name = "{project.name}"\n',
        encoding="utf-8",
    )
    (project / "planledger.toml").write_text(
        "[project]\n"
        f'uuid = "{project_uuid}"\n'
        "[storage]\n"
        f'planledger_dir = "{source}"\n',
        encoding="utf-8",
    )
    record = source / "plans" / "plan-0001"
    record.mkdir(parents=True)
    (source / "storage.yaml").write_text(
        "schema_version: 3\n"
        "next_plan_id: 2\n"
        "next_workshop_id: 1\n"
        "active_plan_id: plan-0001\n"
        "active_workshop_id: ''\n"
        "created_at: '2026-01-01T00:00:00Z'\n"
        "updated_at: '2026-01-01T00:00:00Z'\n",
        encoding="utf-8",
    )
    (record / "plan.yaml").write_text(
        "schema_version: 2\n"
        "id: plan-0001\n"
        "type: plan\n"
        "title: Legacy plan\n"
        "status: new\n"
        "version: 1\n"
        "components: {}\n",
        encoding="utf-8",
    )



def test_migration_uses_explicit_uuid_scoped_root(tmp_path: Path) -> None:
    project_uuid = "11111111-1111-4111-8111-111111111111"
    project = tmp_path / "project"
    source = tmp_path / "legacy"
    sibling = tmp_path / "shared-ledger"
    _write_legacy_project(project, source, project_uuid)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    dry_run = _invoke(
        project,
        "migrate",
        "apply",
        "--sibling-ledger-root",
        str(sibling),
        "--dry-run",
    )
    assert dry_run.exit_code == 0, dry_run.stdout
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before
    backup = tmp_path / "backup"
    result = _invoke(
        project,
        "migrate",
        "apply",
        "--sibling-ledger-root",
        str(sibling),
        "--create-sibling-store",
        "--backup-dir",
        str(backup),
    )
    assert result.exit_code == 0, result.stdout
    target = sibling / "planledger" / project_uuid
    assert (target / ".ledger-project.toml").is_file()
    state = yaml.safe_load((target / "storage.yaml").read_text())
    assert state["schema_version"] == 4
    assert "next_plan_id" not in state
    assert (target / "migrations").is_dir()
    assert (backup / "backup-manifest.json").is_file()
    assert source.is_dir()
    assert not (sibling / "planledger" / "storage.yaml").exists()



def test_two_projects_share_explicit_sibling_root_without_mixing(
    tmp_path: Path,
    ) -> None:
    first_uuid = "11111111-1111-4111-8111-111111111111"
    second_uuid = "22222222-2222-4222-8222-222222222222"
    sibling = tmp_path / "shared-ledger"
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_legacy_project(first, tmp_path / "first-legacy", first_uuid)
    _write_legacy_project(second, tmp_path / "second-legacy", second_uuid)
    first_result = _invoke(
        first,
        "migrate",
        "apply",
        "--sibling-ledger-root",
        str(sibling),
        "--create-sibling-store",
    )
    assert first_result.exit_code == 0, first_result.stdout
    second_result = _invoke(
        second,
        "migrate",
        "apply",
        "--sibling-ledger-root",
        str(sibling),
    )
    assert second_result.exit_code == 0, second_result.stdout
    first_target = sibling / "planledger" / first_uuid
    second_target = sibling / "planledger" / second_uuid
    assert first_target != second_target
    assert first_uuid in (first_target / ".ledger-project.toml").read_text()
    assert second_uuid in (second_target / ".ledger-project.toml").read_text()
    assert (first_target / "plans" / "plan-0001" / "plan.yaml").is_file()
    assert (second_target / "plans" / "plan-0001" / "plan.yaml").is_file()
