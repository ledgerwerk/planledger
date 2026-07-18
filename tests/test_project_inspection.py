from __future__ import annotations

from pathlib import Path

from planledger.initialization import initialize_project
from planledger.project_context import inspect_project_context


def test_inspection_reports_uninitialized(tmp_path: Path) -> None:
    inspection = inspect_project_context(tmp_path / "project")
    assert inspection.state.kind == "uninitialized"
    assert inspection.workspace is None


def test_inspection_reports_legacy_configuration(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    config = project / ".planledger.toml"
    config.write_text('[storage]\nplanledger_dir = ".planledger"\n', encoding="utf-8")

    inspection = inspect_project_context(project)

    assert inspection.state.kind == "legacy"
    assert inspection.legacy is not None
    assert inspection.legacy.legacy_config_path == config


def test_inspection_reports_schema_migration_required(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".ledger").mkdir(parents=True)
    (project / ".ledger" / "ledger.toml").write_text(
        "schema_version = 2\n"
        '[project]\nuuid = "00000000-0000-4000-8000-000000000001"\n',
        encoding="utf-8",
    )

    inspection = inspect_project_context(project)

    assert inspection.state.kind == "schema_migration_required"


def test_inspection_reports_invalid_external_marker(tmp_path: Path) -> None:
    project = tmp_path / "project"
    external = tmp_path / "ledger"
    external.mkdir()
    initialize_project(project, "demo", create_external_store=True)
    (external / ".ledger-store.toml").unlink()

    inspection = inspect_project_context(project)

    assert inspection.state.kind == "data_binding_invalid"
    assert inspection.workspace is not None
    assert "PLANLEDGER_DATA_BINDING_INVALID" in inspection.state.reasons
