from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from planledger.cli import app
from planledger.project_context import load_workspace


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def invoke(runner: CliRunner):
    def _invoke(workspace: Path, *args: str):
        command = ["--cwd", str(workspace), *args]
        return runner.invoke(app, command)

    return _invoke


@pytest.fixture
def invoke_json(invoke):
    def _invoke_json(workspace: Path, *args: str):
        result = invoke(workspace, "--json", *args)
        payload = json.loads(result.stdout)
        return result, payload

    return _invoke_json


@pytest.fixture
def initialized_workspace(tmp_path: Path, invoke):
    project = tmp_path / "project"
    project.mkdir()
    external = tmp_path / "ledger"
    external.mkdir()
    result = invoke(
        project,
        "init",
        "--project-name",
        "Test Project",
        "--create-external-store",
    )
    assert result.exit_code == 0, result.stdout
    workspace = load_workspace(project)
    legacy = project / ".planledger"
    if not legacy.exists():
        try:
            legacy.symlink_to(workspace.data_root)
        except (OSError, NotImplementedError):
            pass
    return project


@pytest.fixture
def data_dir(initialized_workspace: Path) -> Path:
    """Return the resolved Planledger data root for the initialized project."""
    workspace = load_workspace(initialized_workspace)
    return workspace.data_root

