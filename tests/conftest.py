from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tomlkit import dumps as toml_dumps
from tomlkit import parse as toml_parse
from tomlkit.items import Table
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


def configure_prompt_profile(
    workspace: Path,
    *,
    name: str = "planning_workshop",
    enabled: bool = True,
    activation: str = "always",
    trigger_phrases: list[str] | None = None,
    required_question_topics: list[str] | None = None,
    min_resolved_required_questions_before_done: int | None = None,
    max_required_questions: int | None = None,
    question_policy: str | None = None,
    **extra: Any,
) -> None:
    """Mutate one existing prompt profile while preserving valid TOML."""
    config_path = workspace / ".ledger" / "planledger" / "config.toml"
    document = toml_parse(config_path.read_text(encoding="utf-8"))
    profiles = document.get("prompt_profiles")
    if profiles is None:
        profiles = Table()
        document["prompt_profiles"] = profiles
    profile = profiles.get(name)
    if profile is None or not isinstance(profile, dict):
        profile = Table()
        profiles[name] = profile
    profile["enabled"] = enabled
    profile["activation"] = activation
    if trigger_phrases is not None:
        profile["trigger_phrases"] = trigger_phrases
    if required_question_topics is not None:
        profile["required_question_topics"] = required_question_topics
    if min_resolved_required_questions_before_done is not None:
        profile["min_resolved_required_questions_before_done"] = (
            min_resolved_required_questions_before_done
        )
    if max_required_questions is not None:
        profile["max_required_questions"] = max_required_questions
    if question_policy is not None:
        profile["question_policy"] = question_policy
    for key, value in extra.items():
        profile[key] = value
    config_path.write_text(toml_dumps(document), encoding="utf-8")
