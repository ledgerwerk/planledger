"""Schema-3 read-only context tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    pass
else:  # pragma: no cover
    pass


from planledger.cli import app
from planledger.project_context import classify_project_state, load_workspace


def _write_v3(
    project: Path,
    *,
    storage: str = "external",
    external_root: str = "../ledger",
    registration: bool = True,
) -> str:
    project.mkdir()
    ledger_dir = project / ".ledger"
    ledger_dir.mkdir()
    if registration:
        ledgers = f'[ledgers.planledger.mounts.data]\nstorage = "{storage}"\n'
        if storage == "external":
            ledgers += f'root = "{external_root}"\n'
    else:
        ledgers = '[ledgers.other.mounts.data]\nstorage = "project"\n'
    config_dir = ledger_dir / "planledger"
    config_dir.mkdir()
    manifest_text = (
        "schema_version = 3\n"
        '[project]\nuuid = "00000000-0000-4000-8000-000000000010"\nname = "demo"\n'
        + ledgers
    )
    (ledger_dir / "ledger.toml").write_text(manifest_text, encoding="utf-8")
    (config_dir / "config.toml").write_text(
        '[ledger]\ncode = "pl"\nname = "planledger"\n',
        encoding="utf-8",
    )
    from planledger.ledgercore_backend import (
        initialize_planledger_locations,
        load_planledger_ledger_layout,
    )

    layout = load_planledger_ledger_layout(project, validate_storage=False)
    initialize_planledger_locations(
        layout,
        initialize_config=True,
        initialize_data=False,
    )
    return "00000000-0000-4000-8000-000000000010"


@pytest.fixture
def project_with_external(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    external_root = (project / ".." / "ledger").resolve()
    external_root.mkdir()
    _write_v3(project, storage="external", external_root="../ledger")
    from planledger.ledgercore_backend import initialize_planledger_external_store

    initialize_planledger_external_store(external_root, legacy_compatible=True)
    return project


@pytest.fixture
def project_with_user_data(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    _write_v3(project, storage="user-data")
    return project


@pytest.fixture
def project_with_project_storage(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    _write_v3(project, storage="project")
    return project


def test_external_storage_loads(project_with_external: Path) -> None:
    workspace = load_workspace(project_with_external, require_initialized=False)
    assert workspace.data_storage == "external"
    assert workspace.storage_source == "manifest"
    assert str(workspace.data_root).endswith("/data")


def test_user_data_storage_loads(project_with_user_data: Path) -> None:
    workspace = load_workspace(project_with_user_data, require_initialized=False)
    assert workspace.data_storage == "user-data"


def test_project_storage_loads(project_with_project_storage: Path) -> None:
    workspace = load_workspace(project_with_project_storage, require_initialized=False)
    assert workspace.data_storage == "project"


def test_config_path_uses_planledger_dir(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write_v3(project, storage="project")
    workspace = load_workspace(project, require_initialized=False)
    assert workspace.config_path.name == "config.toml"
    assert workspace.config_path.parent.name == "planledger"


def test_planledger_dir_aliases_data_root(project_with_external: Path) -> None:
    workspace = load_workspace(project_with_external, require_initialized=False)
    assert workspace.planledger_dir == workspace.data_root


def test_status_json_for_schema3(tmp_path: Path, runner=None) -> None:
    from typer.testing import CliRunner

    project = tmp_path / "project"
    external_root = (project / ".." / "ledger").resolve()
    external_root.mkdir()
    from planledger.storage import initialize_project

    initialize_project(
        project,
        "Test Project",
        create_external_store=True,
    )
    runner = runner or CliRunner()
    result = runner.invoke(app, ["--cwd", str(project), "--json", "status"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    storage = payload["result"]["storage"]
    assert storage["kind"] == "external"
    assert storage["mount"] == "data"
    assert storage["source"] == "manifest"
    assert storage["path"].endswith("/data")
    assert storage["binding_status"] in {"valid", "absent"}
    for forbidden in (
        "workspace_provider",
        "store_root",
        "store_marker_path",
        "mount_storage",
        "mount_scope",
        "mount_source",
        "active_mount",
    ):
        assert forbidden not in payload["result"]


def test_classify_canonical_schema3(project_with_external: Path) -> None:
    state = classify_project_state(project_with_external)
    assert state.kind in {"canonical", "partial", "data_missing"}


@pytest.mark.parametrize("root_kind", ["relative", "absolute", "home"])
def test_external_root_is_resolved_from_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    root_kind: str,
) -> None:
    project = tmp_path / "project"
    if root_kind == "relative":
        root_value = "custom-ledger"
        external_root = project / root_value
    elif root_kind == "absolute":
        external_root = tmp_path / "absolute-ledger"
        root_value = "../absolute-ledger"
    else:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        root_value = "~/home-ledger"
        external_root = home / "home-ledger"
    _write_v3(project, storage="external", external_root=root_value)
    external_root.mkdir(parents=True)
    from planledger.ledgercore_backend import (
        initialize_planledger_external_store,
        resolve_planledger_external_root,
    )

    initialize_planledger_external_store(external_root)
    assert (
        resolve_planledger_external_root(external_root, project_root=project)
        == external_root.resolve()
    )

    nested = project / "nested"
    nested.mkdir()
    runner_cwd = tmp_path / "runner"
    runner_cwd.mkdir()
    monkeypatch.chdir(runner_cwd)
    from_project = load_workspace(project, require_initialized=False)
    from_nested = load_workspace(nested, require_initialized=False)

    assert from_project.external_root == external_root.resolve()
    assert from_nested.external_root == from_project.external_root
    assert from_project.external_root.is_absolute()
    assert from_project.store_marker_path is not None
    assert from_project.store_marker_path.is_absolute()
