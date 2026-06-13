from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from ledgercore.errors import IdFormatError

from planledger.identity import (
    format_plan_id,
    normalize_plan_selector,
    plan_ref,
)


def test_identity_helpers_preserve_local_ids_and_derive_refs() -> None:
    assert format_plan_id(1) == "plan-0001"
    assert plan_ref("plan-0001", ledger_code="pl").global_ref == "pl:plan-0001"
    assert normalize_plan_selector("plan-0001", ledger_code="pl") == "plan-0001"
    assert normalize_plan_selector("pl:plan-0001", ledger_code="pl") == "plan-0001"
    assert normalize_plan_selector("PL-PLAN-0001", ledger_code="pl") == "plan-0001"


@pytest.mark.parametrize(
    "value",
    ["tl:task-0001", "al:adr-0002", "plan-0000", "plan-x"],
)
def test_identity_helpers_reject_foreign_or_invalid_refs(value: str) -> None:
    with pytest.raises(IdFormatError):
        normalize_plan_selector(value, ledger_code="pl")


@pytest.mark.parametrize(
    "selector",
    ["plan-0001", "pl:plan-0001", "pl-plan-0001", "PL-PLAN-0001"],
)
def test_cli_accepts_equivalent_plan_selectors(
    initialized_workspace: Path,
    invoke_json,
    selector: str,
) -> None:
    create, _ = invoke_json(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Referenced plan",
        "--request",
        "Test references.",
    )
    assert create.exit_code == 0, create.stdout

    result, payload = invoke_json(
        initialized_workspace,
        "plan",
        "show",
        selector,
    )

    assert result.exit_code == 0, result.stdout
    plan = payload["result"]
    assert plan["plan_id"] == "plan-0001"
    assert plan["global_ref"] == "pl:plan-0001"
    assert plan["file_ref"] == "pl-plan-0001"


def test_cli_rejects_foreign_ref_with_planledger_error(
    initialized_workspace: Path,
    invoke_json,
) -> None:
    result, payload = invoke_json(
        initialized_workspace,
        "plan",
        "show",
        "tl:task-0001",
    )

    assert result.exit_code != 0
    assert payload["error"]["code"] == "invalid_plan_ref"


def test_plan_metadata_stores_kind_but_not_derived_identity(
    initialized_workspace: Path,
    invoke,
) -> None:
    result = invoke(
        initialized_workspace,
        "plan",
        "create",
        "--title",
        "Metadata",
        "--request",
        "Test metadata.",
    )
    assert result.exit_code == 0, result.stdout

    metadata = yaml.safe_load(
        (
            initialized_workspace
            / ".planledger"
            / "plans"
            / "plan-0001"
            / "plan.yaml"
        ).read_text()
    )
    assert metadata["kind"] == "plan"
    assert "global_id" not in metadata
    assert "global_ref" not in metadata
