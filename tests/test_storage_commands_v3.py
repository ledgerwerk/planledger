"""Planledger 0.3 ``storage`` command tests.

Covers plan section 24.9: ``storage where``, ``storage validate``,
``storage set external|user-data|project``, ``storage clear-override``,
``storage migration-status``, ``storage recover`` in both human and
JSON form. Asserts that normal output does not contain
``sibling-ledger``, ``workspace_provider``, ``namespace``, ``scope``, or
``plan/config.toml``.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from planledger.cli import app


def _invoke(root: Path, *args: str):
    return CliRunner().invoke(app, ["--cwd", str(root), *args])


def _init_project(project: Path) -> None:
    project.mkdir()
    sibling = project.parent / "ledger"
    sibling.mkdir()
    result = _invoke(
        project, "init", "--project-name", "demo", "--create-external-store"
    )
    assert result.exit_code == 0, result.stdout


def test_storage_where_human(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_project(project)
    result = _invoke(project, "storage", "where")
    assert result.exit_code == 0, result.stdout
    out = result.stdout
    assert "Planledger storage" in out
    assert "Data storage: external" in out
    assert "Data path:" in out
    for forbidden in (
        "sibling-ledger",
        "workspace_provider",
        "namespace",
        "scope",
        "plan/config.toml",
    ):
        assert forbidden not in out


def test_storage_where_json(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_project(project)
    result = _invoke(project, "--json", "storage", "where")
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "storage.where"
    storage = payload["result"]["storage"]
    assert storage["mount"] == "data"
    assert storage["kind"] == "external"
    assert storage["path"].endswith("/data")


def test_storage_validate_json(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_project(project)
    result = _invoke(project, "--json", "storage", "validate")
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["command"] == "storage.validate"
    assert "storage" in payload["result"]
    assert "issues" in payload["result"]


def test_storage_validate_is_read_only(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_project(project)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    _invoke(project, "storage", "validate")
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert before == after


def test_storage_set_external_to_local_override(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_project(project)
    other = tmp_path / "other-ledger"
    other.mkdir()
    result = _invoke(
        project,
        "storage",
        "set",
        "external",
        "--root",
        str(other),
        "--local-storage-override",
    )
    assert result.exit_code == 0, result.stdout
    local_path = project / ".ledger" / "ledger.local.toml"
    assert local_path.is_file()


def test_storage_set_user_data(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_project(project)
    result = _invoke(project, "storage", "set", "user-data", "--local-storage-override")
    assert result.exit_code == 0, result.stdout


def test_storage_set_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_project(project)
    result = _invoke(project, "storage", "set", "project", "--project")
    assert result.exit_code == 0, result.stdout


def test_storage_clear_override(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_project(project)
    _invoke(
        project,
        "storage",
        "set",
        "user-data",
        "--local-storage-override",
    )
    assert (project / ".ledger" / "ledger.local.toml").is_file()
    result = _invoke(project, "storage", "clear-override")
    assert result.exit_code == 0, result.stdout
    # The local override is removed when empty.
    if (project / ".ledger" / "ledger.local.toml").exists():
        text = (project / ".ledger" / "ledger.local.toml").read_text()
        assert "planledger" not in text


def test_storage_migration_status_json(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_project(project)
    result = _invoke(project, "--json", "storage", "migration-status")
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert "exists" in payload["result"]


def test_storage_recover_when_no_journal(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_project(project)
    result = _invoke(project, "--json", "storage", "recover")
    # No journal exists; the command returns a structured error.
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["ok"] is False
    assert payload["result"]["error"]["code"] == "PLANLEDGER_STORAGE_RECOVERY_REQUIRED"


def test_storage_set_emits_no_sibling_ledger_vocabulary(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _init_project(project)
    other = tmp_path / "other-ledger"
    other.mkdir()
    result = _invoke(
        project,
        "storage",
        "set",
        "external",
        "--root",
        str(other),
        "--local-storage-override",
    )
    combined = result.stdout
    for forbidden in (
        "sibling-ledger",
        "workspace_provider",
        "namespace",
        "scope",
        "plan/config.toml",
    ):
        assert forbidden not in combined


def test_storage_commands_are_read_only_when_no_set(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    _init_project(project)
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    _invoke(project, "storage", "where")
    _invoke(project, "storage", "validate")
    _invoke(project, "storage", "migration-status")
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert before == after
