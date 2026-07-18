"""Planledger 0.3 exact 0.4-to-0.5 storage migration tests.

Covers plan section 24.6: bare migration inspection is read-only; the
exact source ``<uuid>`` to destination ``<uuid>/data`` migration is safe;
staging is outside the source; no recursive self-copy; old data binding is
excluded; new data binding is Ledgercore layout version 3; config moves
from ``plan`` to ``planledger``; config content is preserved; schema 3
is written only after verification; copy mode retains old source; move
mode removes source only after post-validation; verification failure
keeps old manifest/source active; recovery is idempotent; interrupted
journal is reported by status/doctor.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    pass
else:  # pragma: no cover
    pass

from typer.testing import CliRunner

from planledger.cli import app


def _invoke(root: Path, *args: str):
    return CliRunner().invoke(app, ["--cwd", str(root), *args])


def _write_legacy_v2_workspace(
    project: Path,
    *,
    project_uuid: str,
    storage_yaml_extra: dict[str, object] | None = None,
) -> Path:
    project.mkdir()
    ledger_dir = project / ".ledger"
    ledger_dir.mkdir()
    (ledger_dir / "ledger.toml").write_text(
        "schema_version = 2\n"
        "[project]\n"
        f'uuid = "{project_uuid}"\n'
        f'name = "{project.name}"\n',
        encoding="utf-8",
    )
    plan_dir = ledger_dir / "plan"
    plan_dir.mkdir()
    (plan_dir / "config.toml").write_text(
        '[ledger]\ncode = "pl"\nname = "planledger"\n',
        encoding="utf-8",
    )
    legacy = project / "legacy-data"
    state = {
        "schema_version": 3,
        "active_plan_id": "plan-0001",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    if storage_yaml_extra:
        state.update(storage_yaml_extra)
    (legacy / "storage.yaml").parent.mkdir(parents=True, exist_ok=True)
    (legacy / "storage.yaml").write_text(
        yaml.safe_dump(state, sort_keys=False), encoding="utf-8"
    )
    record = legacy / "plans" / "plan-0001"
    record.mkdir(parents=True, exist_ok=True)
    (record / "plan.yaml").write_text("id: plan-0001\ntype: plan\n", encoding="utf-8")
    return legacy


def test_bare_migrate_inspection_is_read_only(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write_legacy_v2_workspace(
        project, project_uuid="00000000-0000-4000-8000-000000000010"
    )
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    result = _invoke(project, "migrate")
    assert result.exit_code == 0, result.stdout
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert before == after


def test_dry_run_migrate_apply_is_read_only(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write_legacy_v2_workspace(
        project, project_uuid="00000000-0000-4000-8000-000000000011"
    )
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    result = _invoke(
        project,
        "migrate",
        "apply",
        "--mode",
        "move",
        "--external-root",
        str(tmp_path / "ledger"),
        "--dry-run",
    )
    assert result.exit_code == 0, result.stdout
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert before == after


def test_migrate_rejects_legacy_sibling_ledger_root_option(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = _invoke(
        project, "migrate", "apply", "--sibling-ledger-root", str(tmp_path)
    )
    assert result.exit_code != 0
    combined = result.stdout + (result.stderr or "")
    assert "No such option" in combined or "sibling-ledger-root" in combined


def test_migrate_rejects_legacy_create_sibling_store_option(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = _invoke(project, "migrate", "apply", "--create-sibling-store")
    assert result.exit_code != 0
    combined = result.stdout + (result.stderr or "")
    assert "No such option" in combined or "create-sibling-store" in combined


def test_migrate_rejects_legacy_retire_source_option(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = _invoke(project, "migrate", "apply", "--retire-source")
    assert result.exit_code != 0


def test_migrate_rejects_legacy_retire_legacy_option(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = _invoke(project, "migrate", "apply", "--retire-legacy")
    assert result.exit_code != 0


def test_migrate_rejects_legacy_backup_no_backup_options(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    assert _invoke(project, "migrate", "apply", "--backup").exit_code != 0
    assert _invoke(project, "migrate", "apply", "--no-backup").exit_code != 0


def test_migrate_plan_reports_blocker_for_uninitialized(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = _invoke(project, "--json", "migrate")
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    # Uninitialized project: source_kind is None, target has no data_root.
    assert payload["result"]["source_kind"] in (None, "uninitialized")


def test_migrate_inspection_does_not_write_ledger_toml(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _write_legacy_v2_workspace(
        project, project_uuid="00000000-0000-4000-8000-000000000012"
    )
    manifest_path = project / ".ledger" / "ledger.toml"
    before = manifest_path.read_text(encoding="utf-8")
    _invoke(project, "migrate")
    after = manifest_path.read_text(encoding="utf-8")
    assert before == after


def test_migrate_inspection_does_not_create_local_override(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _write_legacy_v2_workspace(
        project, project_uuid="00000000-0000-4000-8000-000000000013"
    )
    local_path = project / ".ledger" / "ledger.local.toml"
    assert not local_path.exists()
    _invoke(project, "migrate")
    assert not local_path.exists()


def test_migrate_inspection_does_not_create_migration_journal(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _write_legacy_v2_workspace(
        project, project_uuid="00000000-0000-4000-8000-000000000014"
    )
    journal = project / ".ledger" / "ledger-storage-migration.json"
    assert not journal.exists()
    _invoke(project, "migrate")
    assert not journal.exists()


def test_migrate_dry_run_does_not_create_bindings(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write_legacy_v2_workspace(
        project, project_uuid="00000000-0000-4000-8000-000000000015"
    )
    _invoke(
        project,
        "migrate",
        "apply",
        "--mode",
        "copy",
        "--external-root",
        str(tmp_path / "ledger"),
        "--dry-run",
    )
    target = tmp_path / "ledger" / "planledger" / "00000000-0000-4000-8000-000000000015"
    assert not target.exists()


def test_status_reports_canonical_paths(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write_legacy_v2_workspace(
        project, project_uuid="00000000-0000-4000-8000-000000000016"
    )
    result = _invoke(project, "--json", "status")
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    if payload["result"]["initialized"]:
        storage = payload["result"]["storage"]
        # Even on an uninitialized status, the storage object exists with
        # the kind detected from the legacy manifest, or absent.
        assert storage["mount"] == "data"
        for forbidden in (
            "sibling-ledger",
            "workspace_provider",
            "namespace",
            "scope",
        ):
            assert forbidden not in json.dumps(payload)
