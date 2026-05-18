from __future__ import annotations

import json
from pathlib import Path

import pytest

from planledger.storage import list_records, load_workspace_from_root


@pytest.fixture
def brownfield_repo(tmp_path: Path, invoke):
    invoke(tmp_path, "init", "--project-name", "Brownfield App")
    (tmp_path / "README.md").write_text("# Brownfield App\n", encoding="utf-8")
    (tmp_path / "src" / "ordering").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "billing").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "adr").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "ordering" / "models.py").write_text(
        "class Order:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "billing" / "invoice.py").write_text(
        "class Invoice:\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "adr" / "async-billing.md").write_text(
        "# Billing consumes order events asynchronously\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_ordering.py").write_text(
        "def test_ordering():\n    assert True\n",
        encoding="utf-8",
    )
    return tmp_path


def test_discovery_emits_areas_and_evidence(invoke, brownfield_repo: Path) -> None:
    result = invoke(brownfield_repo, "--json", "discover", "repo")
    assert result.exit_code == 0, result.stdout

    payload = json.loads(result.stdout)
    areas = payload["result"]["areas"]
    assert {area["title"] for area in areas} >= {"Ordering", "Billing"}
    assert all(area["source_context"] for area in areas)


def test_baseline_requires_evidence_for_inferred_records(
    invoke, brownfield_repo: Path
) -> None:
    invalid = brownfield_repo / "baseline-invalid.json"
    invalid.write_text(
        json.dumps(
            {
                "schema": "planledger.baseline.v1",
                "areas": [{"title": "Ordering", "provenance": "inferred"}],
                "terms": [],
                "rationales": [],
            }
        ),
        encoding="utf-8",
    )
    result = invoke(
        brownfield_repo,
        "--json",
        "baseline",
        "validate",
        "--file",
        str(invalid),
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["ok"] is False
    assert payload["result"]["errors"]


def test_baseline_dry_run_writes_nothing(invoke, brownfield_repo: Path) -> None:
    discovery_path = brownfield_repo / "baseline.json"
    discover = invoke(
        brownfield_repo,
        "discover",
        "repo",
        "--out",
        str(discovery_path),
    )
    assert discover.exit_code == 0, discover.stdout

    result = invoke(
        brownfield_repo,
        "baseline",
        "apply",
        "--file",
        str(discovery_path),
        "--dry-run",
    )
    assert result.exit_code == 0, result.stdout

    ws = load_workspace_from_root(brownfield_repo)
    assert list_records(ws, "language_area") == []
    assert list_records(ws, "language_term") == []
    assert list_records(ws, "decision") == []


def test_baseline_review_lists_inferred_language_and_rationale_records(
    invoke, brownfield_repo: Path
) -> None:
    discovery_path = brownfield_repo / "baseline.json"
    invoke(brownfield_repo, "discover", "repo", "--out", str(discovery_path))
    apply = invoke(
        brownfield_repo,
        "baseline",
        "apply",
        "--file",
        str(discovery_path),
    )
    assert apply.exit_code == 0, apply.stdout

    review = invoke(brownfield_repo, "--json", "baseline", "review")
    assert review.exit_code == 0, review.stdout
    payload = json.loads(review.stdout)
    kinds = {record["kind"] for record in payload["result"]["records"]}
    assert "language_area" in kinds
    assert "language_term" in kinds
    assert "decision" in kinds


def test_inferred_records_are_not_marked_accepted_or_active(
    invoke, brownfield_repo: Path
) -> None:
    discovery_path = brownfield_repo / "baseline.json"
    invoke(brownfield_repo, "discover", "repo", "--out", str(discovery_path))
    invoke(brownfield_repo, "baseline", "apply", "--file", str(discovery_path))

    ws = load_workspace_from_root(brownfield_repo)
    areas = list_records(ws, "language_area")
    terms = list_records(ws, "language_term")
    decisions = list_records(ws, "decision")
    assert areas and all(record.front_matter["status"] == "candidate" for record in areas)
    assert terms and all(record.front_matter["status"] == "candidate" for record in terms)
    assert decisions and all(record.front_matter["status"] == "open" for record in decisions)
