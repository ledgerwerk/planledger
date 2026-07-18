"""Tests for the Ledgercore 0.5 adapter contract."""

from __future__ import annotations

from pathlib import Path

from planledger.errors import PlanledgerError
from planledger.ledgercore_backend import (
    DATA_MOUNT,
    TOOL_NAME,
    initialize_planledger_external_store,
    load_planledger_ledger_layout,
    validate_planledger_external_store,
)


def test_tool_name_and_data_mount_are_locked() -> None:
    assert TOOL_NAME == "planledger"
    assert DATA_MOUNT == "data"


def test_initialize_external_store_creates_marker(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    root.mkdir()
    marker = initialize_planledger_external_store(root)
    assert marker.is_file()
    content = marker.read_text(encoding="utf-8")
    assert "schema_version" in content
    assert "ledgerwerk-store" in content


def test_initialize_external_store_rejects_symlink_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        return
    try:
        initialize_planledger_external_store(link)
    except PlanledgerError as exc:
        assert "PLANLEDGER" in exc.code
        return
    raise AssertionError("expected PlanledgerError")


def test_validate_external_store_accepts_legacy_marker(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    root.mkdir()
    legacy = root / ".ledger-store"
    legacy.write_text("legacy", encoding="utf-8")
    marker = validate_planledger_external_store(root, allow_legacy=True)
    assert marker == legacy


def test_validate_external_store_rejects_unknown(tmp_path: Path) -> None:
    root = tmp_path / "ledger"
    root.mkdir()
    try:
        validate_planledger_external_store(root, allow_legacy=False)
    except PlanledgerError as exc:
        assert exc.code.startswith("PLANLEDGER")
        return
    raise AssertionError("expected PlanledgerError")


def test_load_layout_rejects_cache_storage(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    manifest = project / ".ledger" / "ledger.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "schema_version = 3\n"
        '[project]\nuuid = "00000000-0000-4000-8000-000000000001"\nname = "x"\n'
        '[ledgers.planledger.mounts.data]\nstorage = "cache"\n',
        encoding="utf-8",
    )
    try:
        load_planledger_ledger_layout(project, validate_storage=False)
    except PlanledgerError as exc:
        assert exc.code == "PLANLEDGER_STORAGE_TARGET_INVALID"
        return
    raise AssertionError("expected PlanledgerError")


def test_load_layout_rejects_extra_mount(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    manifest = project / ".ledger" / "ledger.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "schema_version = 3\n"
        '[project]\nuuid = "00000000-0000-4000-8000-000000000002"\nname = "x"\n'
        '[ledgers.planledger.mounts.data]\nstorage = "project"\n'
        '[ledgers.planledger.mounts.indexes]\nstorage = "project"\n',
        encoding="utf-8",
    )
    try:
        load_planledger_ledger_layout(project, validate_storage=False)
    except PlanledgerError as exc:
        assert exc.code == "PLANLEDGER_REGISTRATION_INVALID"
        return
    raise AssertionError("expected PlanledgerError")


def test_load_layout_rejects_cache_data_storage(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    manifest = project / ".ledger" / "ledger.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        "schema_version = 3\n"
        '[project]\nuuid = "00000000-0000-4000-8000-000000000003"\nname = "x"\n'
        '[ledgers.planledger.mounts.data]\nstorage = "cache"\n',
        encoding="utf-8",
    )
    try:
        load_planledger_ledger_layout(project, validate_storage=False)
    except PlanledgerError as exc:
        assert "STORAGE_TARGET_INVALID" in exc.code
        return
    raise AssertionError("expected PlanledgerError")
