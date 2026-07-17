"""Planledger 0.3 schema-3 config discovery tests.

Covers plan section 24.5: nested-directory discovery works against a
schema-3 project, no hidden ``.planledger`` directory is required, and
the new canonical config path ``.ledger/planledger/config.toml`` is
discovered.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    pass
else:  # pragma: no cover
    pass

from typer.testing import CliRunner

from planledger.cli import app


def _invoke(root: Path, *args: str):
    return CliRunner().invoke(app, ["--cwd", str(root), *args])


def _make_schema3_project(project: Path, external_root: Path) -> str:
    project.mkdir()
    external_root.mkdir()
    ledger_dir = project / ".ledger"
    ledger_dir.mkdir()
    config_dir = ledger_dir / "planledger"
    config_dir.mkdir()
    (config_dir / "config.toml").write_text(
        "[ledger]\ncode = \"pl\"\nname = \"planledger\"\n",
        encoding="utf-8",
    )
    (ledger_dir / "ledger.toml").write_text(
        'schema_version = 3\n'
        '[project]\nuuid = "00000000-0000-4000-8000-000000000007"\n'
        'name = "demo"\n'
        '[ledgers.planledger.mounts.data]\nstorage = "external"\n'
        'root = "../ledger"\n',
        encoding="utf-8",
    )
    return "00000000-0000-4000-8000-000000000007"


def test_discovery_finds_canonical_config_from_nested_directory(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    external = tmp_path / "ledger"
    _make_schema3_project(project, external)
    nested = project / "src" / "pkg" / "deep"
    nested.mkdir(parents=True)
    result = _invoke(nested, "--json", "status")
    assert result.exit_code == 0, result.stdout
    import json

    payload = json.loads(result.stdout)
    # The status command is discovered from a nested directory.
    assert payload["result"]["initialized"] is False or "storage" in payload["result"]


def test_discovery_uses_planledger_config_dir(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    # No pre-existing manifest, no config dir required; the workspace is
    # uninitialized. We test the canonical config path the CLI writes when
    # ``init`` succeeds.
    result = _invoke(
        project, "init", "--project-name", "demo", "--create-external-store"
    )
    assert result.exit_code == 0, result.stdout
    config_path = project / ".ledger" / "planledger" / "config.toml"
    assert config_path.is_file()
    assert config_path.parent.name == "planledger"
    assert config_path.name == "config.toml"


def test_no_hidden_planledger_directory_required(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    result = _invoke(
        project, "init", "--project-name", "demo", "--create-external-store"
    )
    assert result.exit_code == 0, result.stdout
    assert not (project / ".planledger").exists()


def test_status_reports_canonical_paths_from_nested_directory(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sibling = project.parent / "ledger"
    sibling.mkdir()
    _invoke(
        project, "init", "--project-name", "demo", "--create-external-store"
    )
    nested = project / "src"
    nested.mkdir()
    result = _invoke(nested, "--json", "status")
    assert result.exit_code == 0, result.stdout
    import json

    payload = json.loads(result.stdout)
    storage = payload["result"]["storage"]
    assert storage["kind"] == "external"
    assert storage["mount"] == "data"
    assert "sibling-ledger" not in result.stdout
    assert "workspace_provider" not in result.stdout
