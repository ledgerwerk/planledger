"""Planledger-specific domain migration tests."""

from __future__ import annotations

from pathlib import Path

from planledger.domain_migration import (
    apply_domain_migration,
    plan_domain_migration,
)
from planledger.legacy_layout import read_legacy_state


def _make_legacy_project(
    source: Path,
    *,
    next_plan_id: int | None = 4,
    next_workshop_id: int | None = 2,
    active_plan_id: str | None = "plan-0001",
    active_workshop_id: str | None = None,
    existing_plans: tuple[str, ...] = ("plan-0001", "plan-0003"),
    existing_workshops: tuple[str, ...] = ("workshop-0001",),
    project_uuid: str | None = None,
) -> Path:
    import yaml

    source.mkdir(parents=True, exist_ok=True)
    plans_dir = source / "plans"
    workshops_dir = source / "workshops"
    plans_dir.mkdir(exist_ok=True)
    workshops_dir.mkdir(exist_ok=True)
    state: dict[str, object] = {
        "schema_version": 3,
        "created_at": "2026-01-01T00:00:00Z",
    }
    if project_uuid is not None:
        state["project_uuid"] = project_uuid
    if next_plan_id is not None:
        state["next_plan_id"] = next_plan_id
    if next_workshop_id is not None:
        state["next_workshop_id"] = next_workshop_id
    if active_plan_id is not None:
        state["active_plan_id"] = active_plan_id
    if active_workshop_id is not None:
        state["active_workshop_id"] = active_workshop_id
    (source / "storage.yaml").write_text(
        yaml.safe_dump(state, sort_keys=False), encoding="utf-8"
    )
    for plan in existing_plans:
        (plans_dir / plan).mkdir(exist_ok=True)
        (plans_dir / plan / "plan.yaml").write_text(
            f"id: {plan}\n", encoding="utf-8"
        )
    for workshop in existing_workshops:
        (workshops_dir / workshop).mkdir(exist_ok=True)
        (workshops_dir / workshop / "workshop.yaml").write_text(
            f"id: {workshop}\n", encoding="utf-8"
        )
    return source


def test_plan_creates_counter_gap_tombstones(tmp_path: Path) -> None:
    source = _make_legacy_project(
        tmp_path / "src",
        next_plan_id=6,
        next_workshop_id=2,
        existing_plans=("plan-0001", "plan-0004"),
        existing_workshops=("workshop-0001",),
    )
    receipt = plan_domain_migration(source, target_state_schema=4)
    assert receipt.plan_tombstones == ("plan-0002", "plan-0003", "plan-0005")
    assert receipt.workshop_tombstones == ()


def test_plan_preserves_active_plan_id(tmp_path: Path) -> None:
    source = _make_legacy_project(
        tmp_path / "src",
        active_plan_id="plan-0001",
    )
    receipt = plan_domain_migration(source, target_state_schema=4)
    assert receipt.preserve_active_plan_id is True


def test_plan_drops_legacy_project_uuid(tmp_path: Path) -> None:
    source = _make_legacy_project(
        tmp_path / "src",
        project_uuid="00000000-0000-4000-8000-000000000001",
    )
    receipt = plan_domain_migration(source, target_state_schema=4)
    staged = tmp_path / "staged"
    apply_domain_migration(source, staged, receipt)
    target_state = read_legacy_state(staged / "storage.yaml")
    assert "project_uuid" not in target_state
    assert "next_plan_id" not in target_state
    assert "next_workshop_id" not in target_state
    assert target_state["schema_version"] == 4


def test_apply_writes_tombstone_files(tmp_path: Path) -> None:
    source = _make_legacy_project(
        tmp_path / "src",
        next_plan_id=3,
    )
    receipt = plan_domain_migration(source, target_state_schema=4)
    staged = tmp_path / "staged"
    apply_domain_migration(source, staged, receipt)
    tombstone = staged / "allocations" / "plans" / "plan-0002.toml"
    assert tombstone.is_file()
    content = tombstone.read_text(encoding="utf-8")
    assert "legacy_counter_gap" in content
    assert "ledgercore-0.5.0" in content
