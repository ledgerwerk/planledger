from __future__ import annotations

import json
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
def invoke_json(invoke):
    def _invoke_json(workspace: Path, *args: str):
        result = invoke(workspace, "--json", *args)
        payload = json.loads(result.stdout)
        return result, payload

    return _invoke_json


@pytest.fixture
def initialized_workspace(tmp_path: Path, invoke):
    result = invoke(
        tmp_path,
        "init",
        "--project-name",
        "Test Project",
        "--create-sibling-store",
    )
    assert result.exit_code == 0, result.stdout
    return tmp_path
