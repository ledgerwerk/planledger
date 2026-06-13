from __future__ import annotations

from pathlib import Path

import yaml

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib


def test_init_creates_v2_workspace(tmp_path: Path, invoke) -> None:
    result = invoke(tmp_path, "init", "--project-name", "Test Project")

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / "planledger.toml").exists()
    assert (tmp_path / ".planledger" / "storage.yaml").exists()
    assert (tmp_path / ".planledger" / "plans").is_dir()
    assert not (tmp_path / ".planledger" / "ledgers" / "main").exists()

    storage = yaml.safe_load((tmp_path / ".planledger" / "storage.yaml").read_text())
    config = tomllib.loads((tmp_path / "planledger.toml").read_text())
    assert storage["schema_version"] == 2
    assert storage["next_plan_id"] == 1
    assert config["ledger"] == {"code": "pl", "name": "planledger"}


def test_init_supports_hidden_config(tmp_path: Path, invoke) -> None:
    result = invoke(
        tmp_path,
        "init",
        "--project-name",
        "Test Project",
        "--hidden-config",
    )

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / ".planledger.toml").exists()
    assert not (tmp_path / "planledger.toml").exists()


def test_reinit_fails(tmp_path: Path, invoke) -> None:
    first = invoke(tmp_path, "init", "--project-name", "Test Project")
    second = invoke(tmp_path, "init", "--project-name", "Test Project")

    assert first.exit_code == 0, first.stdout
    assert second.exit_code != 0
