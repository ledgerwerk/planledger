from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from planledger.bundle import apply_bundle, load_bundle
from planledger.errors import PlanledgerError
from planledger.language import add_language_term, create_language_area
from planledger.models import Workspace
from planledger.storage import (
    allocate_id,
    create_record,
    list_records,
    save_record,
)

BASELINE_SCHEMA = "planledger.baseline.v1"


@dataclass
class BaselineValidationDetails:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_baseline_file(path: Path) -> dict[str, Any]:
    data = load_bundle(path)
    if not isinstance(data, dict):
        raise PlanledgerError("invalid_bundle", "Baseline file must be a JSON object.")
    return data


def validate_baseline_details(bundle: dict[str, Any]) -> BaselineValidationDetails:
    details = BaselineValidationDetails()
    schema = bundle.get("schema")
    if schema != BASELINE_SCHEMA:
        details.errors.append(
            f"Missing or invalid schema: expected {BASELINE_SCHEMA!r}, got {schema!r}."
        )

    for field_name in ("areas", "terms", "rationales"):
        value = bundle.get(field_name, [])
        if not isinstance(value, list):
            details.errors.append(f"{field_name} must be a list.")
            continue
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                details.errors.append(f"{field_name}[{index}] must be an object.")
                continue
            evidence = item.get("evidence") or item.get("source_context") or []
            if item.get("provenance") == "inferred" and not evidence:
                details.errors.append(
                    f"{field_name}[{index}] requires evidence for inferred records."
                )
    return details


def apply_baseline(
    workspace: Workspace,
    bundle_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    bundle = load_baseline_file(bundle_path)
    if bundle.get("schema") == "planledger.plan_bundle.v1":
        result = apply_bundle(
            workspace,
            bundle,
            dry_run=dry_run,
            provenance="inferred",
            evidence=[{"path": str(bundle_path.name), "reason": "Imported baseline bundle."}],
        )
        return {
            "kind": "planledger_baseline_apply",
            "dry_run": dry_run,
            "created": result.created,
            "reused": result.reused,
            "events": result.events,
        }

    details = validate_baseline_details(bundle)
    if details.errors:
        raise PlanledgerError(
            "invalid_baseline",
            "Baseline validation failed.",
            remediation=details.errors,
        )

    created: list[dict[str, Any]] = []
    reused: list[dict[str, Any]] = []
    if dry_run:
        for field_name in ("areas", "terms", "rationales"):
            for item in bundle.get(field_name, []):
                if isinstance(item, dict):
                    created.append({"kind": field_name[:-1], "title": item.get("title") or item.get("canonical") or item.get("phrase")})
        return {
            "kind": "planledger_baseline_apply",
            "dry_run": True,
            "created": created,
            "reused": reused,
            "events": [],
        }

    area_ids_by_title: dict[str, str] = {}
    for area_data in bundle.get("areas", []):
        if not isinstance(area_data, dict):
            continue
        title = str(area_data.get("title", "")).strip()
        existing = next(
            (
                record
                for record in list_records(workspace, "language_area")
                if record.front_matter.get("title") == title
            ),
            None,
        )
        if existing is not None:
            area_ids_by_title[title] = existing.record_id
            reused.append({"kind": "language_area", "id": existing.record_id})
            continue
        record = create_language_area(
            workspace,
            title=title,
            paths=list(area_data.get("paths", []) or []),
            summary=str(area_data.get("summary", "") or ""),
            provenance=str(area_data.get("provenance", "inferred")),
            status=str(area_data.get("status", "candidate") or "candidate"),
            is_default=area_data.get("is_default") is True,
        )
        record.front_matter["confidence"] = area_data.get("confidence", "medium")
        record.front_matter["source_context"] = list(area_data.get("source_context", []) or [])
        save_record(record)
        area_ids_by_title[title] = record.record_id
        created.append({"kind": "language_area", "id": record.record_id})

    for term_data in bundle.get("terms", []):
        if not isinstance(term_data, dict):
            continue
        requested_area = term_data.get("area")
        resolved_area = None
        if isinstance(requested_area, str) and requested_area:
            resolved_area = area_ids_by_title.get(requested_area, requested_area)
        record, was_created = add_language_term(
            workspace,
            canonical=str(term_data.get("canonical", "")),
            area=resolved_area,
            definition=str(term_data.get("definition", "")),
            avoid=list(term_data.get("avoid", []) or []),
            aliases=list(term_data.get("aliases", []) or []),
            provenance=str(term_data.get("provenance", "inferred")),
            confidence=str(term_data.get("confidence", "low")),
            evidence=list(term_data.get("evidence", []) or []),
            status=str(term_data.get("status", "candidate") or "candidate"),
        )
        if was_created:
            created.append({"kind": "language_term", "id": record.record_id})
        else:
            reused.append({"kind": "language_term", "id": record.record_id})

    for rationale_data in bundle.get("rationales", []):
        if not isinstance(rationale_data, dict):
            continue
        title = str(rationale_data.get("title", "")).strip()
        existing = next(
            (
                record
                for record in list_records(workspace, "decision")
                if str(record.front_matter.get("title", "")).strip() == title
                and str(record.front_matter.get("decision_type", "")) in {"rationale", "architecture"}
            ),
            None,
        )
        if existing is not None:
            reused.append({"kind": "decision", "id": existing.record_id})
            continue
        decision_id = allocate_id(workspace, "decision")
        front = {
            "id": decision_id,
            "type": "decision",
            "decision_type": "rationale",
            "initiative": rationale_data.get("initiative"),
            "title": title,
            "status": str(rationale_data.get("status", "open") or "open"),
            "chosen_option": None,
            "accepted_at": None,
            "created_at": rationale_data.get("created_at") or "",
            "updated_at": rationale_data.get("updated_at") or "",
            "provenance": str(rationale_data.get("provenance", "inferred")),
            "confidence": str(rationale_data.get("confidence", "low")),
            "rationale_gate": rationale_data.get("rationale_gate")
            or {
                "hard_to_reverse": True,
                "surprising_without_context": True,
                "real_tradeoff": True,
            },
            "evidence": list(rationale_data.get("evidence", []) or []),
        }
        if not front["created_at"]:
            front["created_at"] = front["updated_at"] = "1970-01-01T00:00:00Z"
        create_record(
            workspace,
            "decision",
            front,
            "# Rationale\n\n"
            + str(rationale_data.get("summary", "Inferred rationale candidate.")).strip()
            + "\n",
        )
        created.append({"kind": "decision", "id": decision_id})

    return {
        "kind": "planledger_baseline_apply",
        "dry_run": False,
        "created": created,
        "reused": reused,
        "events": [],
    }


def review_baseline(workspace: Workspace) -> dict[str, Any]:
    inferred_records: list[dict[str, Any]] = []
    for kind in (
        "goal",
        "initiative",
        "plan",
        "milestone",
        "slice",
        "decision",
        "risk",
        "language_area",
        "language_term",
        "language_ambiguity",
    ):
        for record in list_records(workspace, kind):
            if record.front_matter.get("provenance") != "inferred":
                continue
            inferred_records.append(
                {
                    "id": record.record_id,
                    "kind": record.kind,
                    "title": record.front_matter.get("title")
                    or record.front_matter.get("canonical")
                    or record.front_matter.get("phrase"),
                    "status": record.front_matter.get("status"),
                    "provenance": "inferred",
                }
            )
    return {
        "kind": "planledger_baseline_review",
        "inferred_count": len(inferred_records),
        "records": inferred_records,
    }
