from __future__ import annotations

from pathlib import Path


def test_config_discovery_works_from_nested_directories(tmp_path: Path, invoke) -> None:
    root = tmp_path / "repo"
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)

    init = invoke(root, "init", "--project-name", "Nested Project")
    status = invoke(nested, "status")

    assert init.exit_code == 0, init.stdout
    assert status.exit_code == 0, status.stdout
    assert "Planledger status" in status.stdout


def test_hidden_config_is_discovered_from_nested_directories(
    tmp_path: Path, invoke
) -> None:
    root = tmp_path / "repo"
    nested = root / "child"
    nested.mkdir(parents=True)

    init = invoke(root, "init", "--project-name", "Nested Project", "--hidden-config")
    status = invoke(nested, "status")

    assert init.exit_code == 0, init.stdout
    assert (root / ".planledger.toml").exists()
    assert status.exit_code == 0, status.stdout


def test_hidden_config_with_external_planledger_dir_from_nested_directories(
    tmp_path: Path, invoke
) -> None:
    root = tmp_path / "repo"
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)
    external_dir = tmp_path / "planledger-state" / "planledger"

    init = invoke(
        root,
        "init",
        "--project-name",
        "External Project",
        "--hidden-config",
        "--planledger-dir",
        "../planledger-state/planledger",
    )
    status = invoke(nested, "status", "--check")
    create = invoke(nested, "plan", "create", "--title", "External", "--request", "req")

    assert init.exit_code == 0, init.stdout
    assert status.exit_code == 0, status.stdout
    assert create.exit_code == 0, create.stdout
    assert (root / ".planledger.toml").exists()
    assert not (root / ".planledger").exists()
    assert (external_dir / "storage.yaml").exists()
    assert (external_dir / "plans" / "plan-0001" / "plan.yaml").exists()
    assert str(external_dir) in create.stdout
