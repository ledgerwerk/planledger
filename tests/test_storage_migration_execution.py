"""Real Ledgercore schema-3 storage migration execution coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from planledger.cli import app
from planledger.errors import PlanledgerError
from planledger.ledgercore_backend import execute_planledger_layout_migration
from planledger.migration import plan_migration
from planledger.project_context import load_workspace


def _invoke(root: Path, *args: str):
    return CliRunner().invoke(app, ["--cwd", str(root), *args])


def _init_external(project: Path) -> None:
    project.mkdir()
    (project.parent / "ledger").mkdir()
    result = _invoke(
        project, "init", "--project-name", "demo", "--create-external-store"
    )
    assert result.exit_code == 0, result.stdout


def _write_record(root: Path, record_id: str = "plan-0001") -> bytes:
    record = root / "plans" / record_id
    record.mkdir(parents=True)
    content = f"id: {record_id}\ntype: plan\n"
    (record / "plan.yaml").write_text(content, encoding="utf-8")
    return content.encode()


def test_canonical_external_to_project_is_real_copy_transaction(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_external(project)
    workspace = load_workspace(project)
    source = workspace.data_root
    record = _write_record(source)
    result = _invoke(project, "--json", "migrate", "apply", "--data-storage", "project")

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)["result"]
    target = Path(payload["plan"]["target"]["data_root"])
    assert target != source
    assert (target / "plans" / "plan-0001" / "plan.yaml").read_bytes() == record
    assert source.exists()
    assert (source / "plans" / "plan-0001" / "plan.yaml").read_bytes() == record
    assert Path(payload["domain_receipt"]["ledgercore_journal_path"]).is_file()
    assert payload["domain_receipt"]["ledgercore_phase"] == "complete"
    receipt = Path(payload["receipt_path"])
    assert receipt.is_file()
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt_payload["ledgercore_migration_id"]
    assert receipt_payload["ledgercore_journal_path"].endswith(".toml")
    assert receipt_payload["ledgercore_phase"] == "complete"
    assert receipt_payload["ledgercore_source_removed"] is False
    assert list((project / ".ledger" / "migrations").glob("*.toml"))
    assert not list(target.parent.glob("*.staged"))


def test_canonical_noop_does_not_create_transaction(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = _invoke(
        project, "init", "--project-name", "demo", "--data-storage", "project"
    )
    assert result.exit_code == 0, result.stdout
    before = sorted(path.relative_to(project) for path in project.rglob("*"))

    result = _invoke(project, "--json", "migrate", "apply", "--data-storage", "project")

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)["result"]
    assert payload["receipt_path"] is None
    assert payload["plan"]["migration_required"] is False
    assert sorted(path.relative_to(project) for path in project.rglob("*")) == before
    assert not (project / ".ledger" / "migrations").exists()


def test_schema2_legacy_migration_preserves_source_and_activates_schema3(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    ledger = project / ".ledger"
    (ledger / "plan").mkdir(parents=True)
    project_uuid = "00000000-0000-4000-8000-000000000201"
    (ledger / "ledger.toml").write_text(
        f'schema_version = 2\n[project]\nuuid = "{project_uuid}"\nname = "legacy"\n',
        encoding="utf-8",
    )
    (ledger / "plan" / "config.toml").write_text(
        '[ledger]\ncode = "pl"\nname = "planledger"\n', encoding="utf-8"
    )
    source = ledger / "plan" / "data"
    source.mkdir()
    (source / "storage.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "next_plan_id": 3,
                "active_plan_id": "plan-0001",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    record = _write_record(source)
    source_before = sorted(
        (path.relative_to(source), path.read_bytes())
        for path in source.rglob("*")
        if path.is_file()
    )

    result = _invoke(
        project,
        "--json",
        "migrate",
        "apply",
        "--external-root",
        str(tmp_path / "ledger"),
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)["result"]
    target = Path(payload["plan"]["target"]["data_root"])
    assert target.exists()
    assert (target / "plans" / "plan-0001" / "plan.yaml").read_bytes() == record
    assert (target / "allocations" / "plans" / "plan-0002.toml").is_file()
    assert (
        (project / ".ledger" / "ledger.toml")
        .read_text(encoding="utf-8")
        .startswith("schema_version = 3")
    )
    assert source.exists()
    assert (
        sorted(
            (path.relative_to(source), path.read_bytes())
            for path in source.rglob("*")
            if path.is_file()
        )
        == source_before
    )
    assert payload["source_preserved"] is True
    assert Path(payload["domain_receipt"]["ledgercore_journal_path"]).is_file()


def test_move_is_rejected_before_mutation(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_external(project)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    result = _invoke(project, "migrate", "apply", "--mode", "move", "--dry-run")

    assert result.exit_code != 0
    assert "PLANLEDGER_MIGRATION_MOVE_UNSUPPORTED" in result.stdout
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before
    assert not (project / ".ledger" / "migrations").exists()


def test_journal_status_and_recovery_dry_run_are_assessments(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_external(project)
    result = _invoke(project, "migrate", "apply", "--data-storage", "project")
    assert result.exit_code == 0, result.stdout
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    status = _invoke(project, "--json", "storage", "migration-status")
    recovery = _invoke(project, "--json", "storage", "recover", "--dry-run")

    assert status.exit_code == 0, status.stdout
    assert recovery.exit_code == 0, recovery.stdout
    status_payload = json.loads(status.stdout)["result"]
    recovery_payload = json.loads(recovery.stdout)["result"]
    for payload in (status_payload, recovery_payload):
        assert payload["journal_path"].endswith(".toml")
        assert payload["phase"] == "complete"
        assert payload["recommendation"] == "complete"
        assert payload["complete"] is True
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before


def test_storage_set_blocks_populated_redirect(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = _invoke(
        project, "init", "--project-name", "demo", "--data-storage", "project"
    )
    assert result.exit_code == 0, result.stdout
    workspace = load_workspace(project)
    _write_record(workspace.data_root)
    target_root = tmp_path / "other-ledger"
    target_root.mkdir()

    result = _invoke(
        project,
        "--json",
        "storage",
        "set",
        "external",
        "--root",
        str(target_root),
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["ok"] is False
    assert payload["result"]["error"]["code"] == "PLANLEDGER_STORAGE_MIGRATION_REQUIRED"


def test_source_fingerprint_mismatch_fails_before_activation(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_external(project)
    workspace = load_workspace(project)
    source = workspace.data_root
    _write_record(source)
    plan = plan_migration(project, target_data_storage="project")
    assert plan.ledgercore_plan is not None
    (source / "unexpected.txt").write_text("changed", encoding="utf-8")

    with pytest.raises(PlanledgerError):
        execute_planledger_layout_migration(plan.ledgercore_plan, project_root=project)

    assert source.joinpath("unexpected.txt").read_text(encoding="utf-8") == "changed"
    assert not (project / ".ledger" / "ledger.local.toml").exists()
    assert not (project / ".ledger" / "planledger" / "data").exists()
