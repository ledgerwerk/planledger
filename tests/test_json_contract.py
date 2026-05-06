from __future__ import annotations

import json
from pathlib import Path


def test_success_envelope_contains_standard_fields(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    result = invoke(workspace, "--json", "goal", "create", "Test goal")
    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["ok"] is True
    assert payload["command"] == "goal.create"
    assert "result" in payload
    assert "events" in payload


def test_error_envelope_contains_remediation(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    result = invoke(workspace, "--json", "goal", "show", "goal-9999")
    payload = json.loads(result.stdout)
    assert result.exit_code != 0
    assert payload["ok"] is False
    assert payload["command"] == "goal.show"
    assert payload["error"]["kind"] == "not_found"
    assert payload["error"].get("remediation")
