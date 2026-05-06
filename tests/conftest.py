from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from planledger.cli import app


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
def initialized_workspace(tmp_path: Path, invoke):
    result = invoke(tmp_path, "init", "--project-name", "Test Project")
    assert result.exit_code == 0, result.stdout
    return tmp_path
