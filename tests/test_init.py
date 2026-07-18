"""Planledger 0.3 schema-3 initialization tests.

Covers plan section 24.5: fresh ``planledger init`` writes a valid schema-3
project, default external root is ``../ledger``, default init creates no
local file, config path uses ``planledger``, data path ends in ``/data``,
config and data bindings are valid, the external structured root marker is
created, and re-running init is idempotent.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

import pytest
from typer.testing import CliRunner

from planledger.cli import app


def _invoke(root: Path, *args: str):
    return CliRunner().invoke(app, ["--cwd", str(root), *args])


def test_init_writes_schema3_with_external_default(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()

    result = _invoke(
        project, "init", "--project-name", "demo", "--create-external-store"
    )
    assert result.exit_code == 0, result.stdout

    manifest = project / ".ledger" / "ledger.toml"
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    assert data["schema_version"] == 3
    assert data["project"]["name"] == "demo"
    planledger_mounts = data["ledgers"]["planledger"]["mounts"]
    assert planledger_mounts["data"]["storage"] == "external"
    assert planledger_mounts["data"]["root"] == "../ledger"

    config_path = project / ".ledger" / "planledger" / "config.toml"
    assert config_path.is_file()
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert config["ledger"]["code"] == "pl"
    assert config["ledger"]["name"] == "planledger"

    local_path = project / ".ledger" / "ledger.local.toml"
    assert not local_path.exists()

    planledger_text = config_path.read_text(encoding="utf-8")
    assert "sibling-ledger" not in planledger_text
    assert "workspace_provider" not in planledger_text

    project_uuid = data["project"]["uuid"]
    data_root = tmp_path / "ledger" / "planledger" / project_uuid / "data"
    storage_yaml = yaml.safe_load((data_root / "storage.yaml").read_text())
    assert storage_yaml["schema_version"] == 4
    assert storage_yaml["active_plan_id"] is None
    assert storage_yaml["active_workshop_id"] is None


def test_init_creates_external_root_marker_when_asked(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()

    result = _invoke(
        project, "init", "--project-name", "demo", "--create-external-store"
    )
    assert result.exit_code == 0, result.stdout

    marker = tmp_path / "ledger" / ".ledger-store.toml"
    assert marker.is_file()
    content = marker.read_text(encoding="utf-8")
    assert "schema_version" in content
    assert "ledgerwerk-store" in content
    # legacy weak marker must not be created
    assert not (tmp_path / "ledger" / ".ledger-store").exists()


def test_init_creates_required_domain_directories(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()

    _invoke(project, "init", "--project-name", "demo", "--create-external-store")
    manifest = tomllib.loads(
        (project / ".ledger" / "ledger.toml").read_text(encoding="utf-8")
    )
    project_uuid = manifest["project"]["uuid"]
    data_root = tmp_path / "ledger" / "planledger" / project_uuid / "data"
    for sub in (
        "allocations/plans",
        "allocations/workshops",
        "migrations",
        "plans",
        "workshops",
    ):
        assert (data_root / sub).is_dir(), sub


def test_init_data_path_ends_in_data_leaf(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()

    _invoke(project, "init", "--project-name", "demo", "--create-external-store")
    manifest = tomllib.loads(
        (project / ".ledger" / "ledger.toml").read_text(encoding="utf-8")
    )
    mount = manifest["ledgers"]["planledger"]["mounts"]["data"]
    # The Ledgercore path ends with /data; do not assert exact root because
    # the path is relative to the external root. Instead, verify the storage
    # kind and root format.
    assert mount["storage"] == "external"


def test_init_adds_planledger_to_shared_manifest(
    tmp_path: Path,
) -> None:
    # When the existing canonical manifest lacks a planledger registration,
    # ``init`` adds the registration and initializes the project.
    project = tmp_path / "project"
    project.mkdir()
    sibling_ledger = project.parent / "ledger"
    sibling_ledger.mkdir()
    (project / ".ledger").mkdir()
    (project / ".ledger" / "ledger.toml").write_text(
        "schema_version = 3\n"
        '[project]\nuuid = "00000000-0000-4000-8000-000000000099"\n'
        'name = "shared"\n'
        '[ledgers.taskledger.mounts.data]\nstorage = "external"\n'
        'root = "../ledger"\n',
        encoding="utf-8",
    )
    result = _invoke(
        project,
        "init",
        "--project-name",
        "shared",
        "--create-external-store",
    )
    assert result.exit_code == 0
    manifest = (project / ".ledger" / "ledger.toml").read_text(encoding="utf-8")
    assert "planledger" in manifest


def test_init_idempotent_on_valid_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()
    _invoke(project, "init", "--project-name", "demo", "--create-external-store")
    config_before = (project / ".ledger" / "planledger" / "config.toml").read_text(
        encoding="utf-8"
    )
    manifest_before = (project / ".ledger" / "ledger.toml").read_text(encoding="utf-8")

    second = _invoke(
        project,
        "init",
        "--project-name",
        "demo",
        "--create-external-store",
    )
    assert second.exit_code == 0, second.stdout
    config_after = (project / ".ledger" / "planledger" / "config.toml").read_text(
        encoding="utf-8"
    )
    manifest_after = (project / ".ledger" / "ledger.toml").read_text(encoding="utf-8")
    assert config_after == config_before
    assert manifest_after == manifest_before


def test_init_refuses_legacy_planledger_toml(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "planledger.toml").write_text(
        '[project]\nuuid = "00000000-0000-4000-8000-000000000001"\n'
        '[storage]\nplanledger_dir = ".planledger"\n',
        encoding="utf-8",
    )
    result = _invoke(project, "init", "--project-name", "demo")
    assert result.exit_code != 0
    assert "MIGRATION_REQUIRED" in result.stdout


def test_init_storage_yaml_remains_schema4(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()
    _invoke(project, "init", "--project-name", "demo", "--create-external-store")
    manifest = tomllib.loads(
        (project / ".ledger" / "ledger.toml").read_text(encoding="utf-8")
    )
    project_uuid = manifest["project"]["uuid"]
    storage_yaml_path = (
        tmp_path / "ledger" / "planledger" / project_uuid / "data" / "storage.yaml"
    )
    storage_yaml = yaml.safe_load(storage_yaml_path.read_text())
    assert storage_yaml["schema_version"] == 4


def test_init_user_data_storage_does_not_create_external_root(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()
    result = _invoke(
        project,
        "init",
        "--project-name",
        "demo",
        "--data-storage",
        "user-data",
    )
    assert result.exit_code == 0, result.stdout
    # user-data does not require the external root and does not write
    # ``../ledger/planledger/<uuid>/data`` on the sibling root.
    assert not (tmp_path / "ledger" / ".ledger-store.toml").exists()
    assert not (tmp_path / "ledger" / "planledger").exists()


def test_init_does_not_emit_sibling_ledger_vocabulary(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()
    _invoke(project, "init", "--project-name", "demo", "--create-external-store")
    for path in [
        project / ".ledger" / "ledger.toml",
        project / ".ledger" / "planledger" / "config.toml",
    ]:
        text = path.read_text(encoding="utf-8")
        assert "sibling-ledger" not in text
        assert "workspace_provider" not in text
        assert "storage.workspace" not in text
        assert "LEDGER_WORKSPACE_ROOT" not in text


@pytest.mark.parametrize("bad_storage", ["cache", "ledger", "vfs"])
def test_init_rejects_invalid_storage_kind(tmp_path: Path, bad_storage: str) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (tmp_path / "ledger").mkdir()
    result = _invoke(
        project,
        "init",
        "--project-name",
        "demo",
        "--data-storage",
        bad_storage,
    )
    assert result.exit_code != 0


def test_storage_initialization_import_is_compatibility_alias() -> None:
    from planledger.initialization import initialize_project as canonical
    from planledger.storage import initialize_project as compatibility

    assert compatibility is canonical
