"""Tests for the supported Ledgercore adapter contract."""

from __future__ import annotations

from pathlib import Path

from ledgercore.errors import StorageMigrationError
from ledgercore.migration import StorageMigrationHooks

import planledger.ledgercore_backend as backend
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


def test_execute_uses_copy_mode_and_hooks(monkeypatch, tmp_path: Path) -> None:
    observed: dict[str, object] = {}
    callback = lambda: None

    def fake_execute(plan: object, **kwargs: object) -> object:
        observed.update(kwargs)
        return object()

    monkeypatch.setattr(backend, "execute_storage_migration", fake_execute)
    backend.execute_planledger_layout_migration(
        object(), quiescence_check=callback, project_root=tmp_path
    )

    assert observed["mode"] == "copy"
    hooks = observed["hooks"]
    assert isinstance(hooks, StorageMigrationHooks)
    assert hooks.quiescence_check is callback
    assert observed["project_root"] == tmp_path


def test_validation_and_assessment_delegate_to_ledgercore(
    monkeypatch, tmp_path: Path
) -> None:
    validation = object()
    assessment = object()
    monkeypatch.setattr(
        backend,
        "validate_storage_migration_plan",
        lambda plan, *, project_root: validation,
    )
    monkeypatch.setattr(
        backend,
        "assess_storage_migration",
        lambda path, *, project_root: assessment,
    )

    assert (
        backend.validate_planledger_layout_migration(object(), project_root=tmp_path)
        is validation
    )
    assert (
        backend.assess_planledger_storage_migration(
            tmp_path / "journal.toml", project_root=tmp_path
        )
        is assessment
    )


def test_recovery_delegates_policy_and_hooks(monkeypatch, tmp_path: Path) -> None:
    observed: dict[str, object] = {}
    callback = lambda: None
    result = object()

    def fake_recover(path: Path, **kwargs: object) -> object:
        observed.update(kwargs)
        return result

    monkeypatch.setattr(backend, "recover_storage_migration", fake_recover)
    assert (
        backend.recover_planledger_storage_migration(
            tmp_path / "journal.toml",
            policy="rollback",
            dry_run=True,
            quiescence_check=callback,
            project_root=tmp_path,
        )
        is result
    )
    assert observed["policy"] == "rollback"
    assert observed["dry_run"] is True
    assert observed["project_root"] == tmp_path
    hooks = observed["hooks"]
    assert isinstance(hooks, StorageMigrationHooks)
    assert hooks.quiescence_check is callback


def test_adapter_preserves_ledgercore_error_code(monkeypatch, tmp_path: Path) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise StorageMigrationError("blocked", code="STORAGE_MIGRATION_TEST_BLOCKED")

    monkeypatch.setattr(backend, "validate_storage_migration_plan", fail)
    try:
        backend.validate_planledger_layout_migration(object(), project_root=tmp_path)
    except PlanledgerError as exc:
        assert exc.details["ledgercore_code"] == "STORAGE_MIGRATION_TEST_BLOCKED"
        assert exc.details["ledgercore_error_type"] == "StorageMigrationError"
    else:
        raise AssertionError("expected PlanledgerError")
