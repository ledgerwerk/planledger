from __future__ import annotations

from typing import Any

from ledgercore.ids import LedgerIdFormat
from ledgercore.refs import LedgerResourceRef, parse_resource_ref

PLAN_KIND = "plan"
DEFAULT_LEDGER_CODE = "pl"
DEFAULT_LEDGER_NAME = "planledger"
PLAN_ID_FORMAT = LedgerIdFormat(prefix=PLAN_KIND)


def format_plan_id(number: int) -> str:
    return PLAN_ID_FORMAT.format(number)


def parse_plan_number(plan_id: str) -> int:
    return PLAN_ID_FORMAT.parse(plan_id)


def ledger_code_from_config(config: dict[str, Any]) -> str:
    ledger = config.get("ledger", {})
    if isinstance(ledger, dict):
        value = ledger.get("code")
        if isinstance(value, str) and value.strip():
            ref = LedgerResourceRef(ledger=value, kind=PLAN_KIND, number=1)
            if ref.ledger is not None:
                return ref.ledger
    return DEFAULT_LEDGER_CODE


def ledger_name_from_config(config: dict[str, Any]) -> str:
    ledger = config.get("ledger", {})
    if isinstance(ledger, dict):
        value = ledger.get("name")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return DEFAULT_LEDGER_NAME


def plan_ref(plan_id: str, *, ledger_code: str) -> LedgerResourceRef:
    return LedgerResourceRef(
        ledger=ledger_code,
        kind=PLAN_KIND,
        number=parse_plan_number(plan_id),
    )


def normalize_plan_selector(value: str, *, ledger_code: str) -> str:
    ref = parse_resource_ref(
        value,
        default_ledger=ledger_code,
        allowed_ledgers={ledger_code},
        allowed_kinds={PLAN_KIND},
    )
    return ref.local_id
