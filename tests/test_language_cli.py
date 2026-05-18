from __future__ import annotations

import json
from pathlib import Path

from planledger.storage import list_records, load_workspace_from_root


def test_language_area_create(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    result = invoke(
        workspace,
        "language",
        "area",
        "create",
        "Ordering",
        "--paths",
        "src/ordering",
    )
    assert result.exit_code == 0, result.stdout

    areas = list_records(load_workspace_from_root(workspace), "language_area")
    assert len(areas) == 1
    assert areas[0].front_matter["title"] == "Ordering"


def test_language_term_add(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    invoke(workspace, "language", "area", "create", "Ordering")
    result = invoke(
        workspace,
        "language",
        "term",
        "add",
        "Order",
        "--area",
        "area-0001",
        "--definition",
        "A customer request for goods or services.",
        "--avoid",
        "Purchase",
    )
    assert result.exit_code == 0, result.stdout

    ws = load_workspace_from_root(workspace)
    terms = list_records(ws, "language_term")
    assert len(terms) == 1
    assert terms[0].front_matter["canonical"] == "Order"
    assert terms[0].front_matter["avoid"] == ["Purchase"]


def test_language_term_requires_area_or_default_area(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    result = invoke(
        workspace,
        "language",
        "term",
        "add",
        "Invoice",
        "--definition",
        "A bill issued after fulfillment.",
    )
    assert result.exit_code == 0, result.stdout

    ws = load_workspace_from_root(workspace)
    areas = list_records(ws, "language_area")
    terms = list_records(ws, "language_term")
    assert [area.front_matter["title"] for area in areas] == ["Project"]
    assert terms[0].front_matter["area"] == areas[0].record_id


def test_language_term_idempotent_by_area_canonical(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    invoke(workspace, "language", "area", "create", "Ordering")
    first = invoke(
        workspace,
        "language",
        "term",
        "add",
        "Order",
        "--area",
        "area-0001",
        "--definition",
        "A customer request for goods or services.",
    )
    second = invoke(
        workspace,
        "language",
        "term",
        "add",
        "Order",
        "--area",
        "area-0001",
        "--definition",
        "A customer request for goods or services.",
    )
    assert first.exit_code == 0, first.stdout
    assert second.exit_code == 0, second.stdout

    ws = load_workspace_from_root(workspace)
    terms = list_records(ws, "language_term")
    assert len(terms) == 1


def test_language_export_in_snapshot(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    invoke(workspace, "language", "area", "create", "Ordering")
    invoke(
        workspace,
        "language",
        "term",
        "add",
        "Order",
        "--area",
        "area-0001",
        "--definition",
        "A customer request for goods or services.",
    )
    invoke(
        workspace,
        "language",
        "ambiguity",
        "add",
        "account",
        "--area",
        "area-0001",
        "--meaning",
        "Customer",
        "--meaning",
        "User",
    )
    result = invoke(workspace, "--json", "snapshot", "export", "--include-language")
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["schema"] == "planledger.snapshot.v1"
    assert [item["id"] for item in payload["result"]["language"]["areas"]] == ["area-0001"]
    assert [item["id"] for item in payload["result"]["language"]["terms"]] == ["term-0001"]
    assert [item["id"] for item in payload["result"]["language"]["ambiguities"]] == [
        "amb-0001"
    ]


def test_language_definition_rejects_long_multiline_definitions(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    result = invoke(
        workspace,
        "--json",
        "language",
        "term",
        "add",
        "Order",
        "--definition",
        "Line one.\nLine two.",
    )
    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["error"]["kind"] == "invalid_language_definition"


def test_language_ambiguity_resolve(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    invoke(
        workspace,
        "language",
        "ambiguity",
        "add",
        "account",
        "--meaning",
        "Customer",
        "--meaning",
        "User",
    )
    result = invoke(
        workspace,
        "language",
        "ambiguity",
        "resolve",
        "amb-0001",
        "--resolution",
        "Use Customer for buyers and User for login identities.",
    )
    assert result.exit_code == 0, result.stdout

    ws = load_workspace_from_root(workspace)
    ambiguities = list_records(ws, "language_ambiguity")
    assert ambiguities[0].front_matter["status"] == "resolved"
