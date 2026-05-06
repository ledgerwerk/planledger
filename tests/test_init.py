from __future__ import annotations

import json
from pathlib import Path


def test_init_and_status_json(invoke, tmp_path: Path) -> None:
    init_result = invoke(tmp_path, "init", "--project-name", "Test Project")
    assert init_result.exit_code == 0
    assert (tmp_path / "planledger.toml").exists()
    assert (tmp_path / ".planledger" / "storage.yaml").exists()
    assert (tmp_path / ".planledger" / "ledgers" / "main").exists()

    status_result = invoke(tmp_path, "status")
    assert status_result.exit_code == 0
    assert "Test Project" in status_result.stdout

    json_result = invoke(tmp_path, "--json", "status")
    payload = json.loads(json_result.stdout)
    assert json_result.exit_code == 0
    assert payload["ok"] is True
    assert payload["command"] == "project.status"
