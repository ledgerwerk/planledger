from __future__ import annotations

from typing import Any

from planledger.errors import PlanledgerError
from planledger.models import Record, Workspace
from planledger.storage import (
    LANGUAGE_AMBIGUITY_TEMPLATE,
    LANGUAGE_TERM_TEMPLATE,
    allocate_id,
    create_record,
    ensure_default_language_area,
    find_language_term,
    list_records,
    load_record,
    normalize_language_canonical,
    now_iso,
    save_record,
    update_record_timestamp,
)


def validate_language_definition(definition: str) -> str:
    cleaned = definition.strip()
    if not cleaned:
        raise PlanledgerError(
            "invalid_language_definition",
            "Language definitions must be a non-empty sentence.",
        )
    if "\n" in cleaned:
        raise PlanledgerError(
            "invalid_language_definition",
            "Language definitions must be a single line.",
            remediation=["Rewrite the definition as one concise sentence."],
        )
    return cleaned


def create_language_area(
    workspace: Workspace,
    *,
    title: str,
    paths: list[str] | None = None,
    summary: str | None = None,
    provenance: str = "human",
    status: str = "active",
    is_default: bool = False,
) -> Record:
    area_id = allocate_id(workspace, "language_area")
    timestamp = now_iso()
    front = {
        "id": area_id,
        "type": "language_area",
        "title": title.strip(),
        "status": status,
        "paths": list(paths or []),
        "summary": (summary or "").strip(),
        "parent_area": None,
        "is_default": is_default,
        "created_at": timestamp,
        "updated_at": timestamp,
        "provenance": provenance,
    }
    return create_record(workspace, "language_area", front, "# " + title.strip() + "\n")


def add_language_term(
    workspace: Workspace,
    *,
    canonical: str,
    area: str | None,
    definition: str,
    avoid: list[str] | None = None,
    aliases: list[str] | None = None,
    provenance: str = "human",
    confidence: str = "high",
    evidence: list[dict[str, str]] | None = None,
    status: str = "active",
) -> tuple[Record, bool]:
    resolved_area = area
    if resolved_area is None:
        resolved_area = ensure_default_language_area(workspace).record_id
    else:
        _ = load_record(workspace, "language_area", resolved_area)
    cleaned_definition = validate_language_definition(definition)
    existing = find_language_term(
        workspace,
        area=resolved_area,
        canonical=canonical,
    )
    if existing is not None:
        return existing, False
    term_id = allocate_id(workspace, "language_term")
    timestamp = now_iso()
    front = {
        "id": term_id,
        "type": "language_term",
        "area": resolved_area,
        "canonical": canonical.strip(),
        "status": status,
        "definition": cleaned_definition,
        "avoid": [item.strip() for item in avoid or [] if item.strip()],
        "aliases": [item.strip() for item in aliases or [] if item.strip()],
        "relationships": [],
        "evidence": list(evidence or []),
        "ambiguities": [],
        "created_at": timestamp,
        "updated_at": timestamp,
        "provenance": provenance,
        "confidence": confidence,
        "canonical_key": normalize_language_canonical(canonical),
    }
    record = create_record(workspace, "language_term", front, LANGUAGE_TERM_TEMPLATE)
    return record, True


def update_language_term(
    workspace: Workspace,
    term_ref: str,
    *,
    definition: str | None = None,
    avoid: list[str] | None = None,
    aliases: list[str] | None = None,
) -> Record:
    record = load_record(workspace, "language_term", term_ref)
    if definition is not None:
        record.front_matter["definition"] = validate_language_definition(definition)
    if avoid is not None:
        record.front_matter["avoid"] = [item.strip() for item in avoid if item.strip()]
    if aliases is not None:
        record.front_matter["aliases"] = [item.strip() for item in aliases if item.strip()]
    update_record_timestamp(record)
    save_record(record)
    return record


def deprecate_language_term(workspace: Workspace, term_ref: str, *, reason: str) -> Record:
    record = load_record(workspace, "language_term", term_ref)
    record.front_matter["status"] = "deprecated"
    record.front_matter["deprecation_reason"] = reason.strip()
    update_record_timestamp(record)
    save_record(record)
    return record


def add_language_ambiguity(
    workspace: Workspace,
    *,
    phrase: str,
    area: str | None,
    meanings: list[str],
    question: str | None = None,
) -> Record:
    resolved_area = area
    if resolved_area is None:
        resolved_area = ensure_default_language_area(workspace).record_id
    else:
        _ = load_record(workspace, "language_area", resolved_area)
    ambiguity_id = allocate_id(workspace, "language_ambiguity")
    timestamp = now_iso()
    front = {
        "id": ambiguity_id,
        "type": "language_ambiguity",
        "area": resolved_area,
        "phrase": phrase.strip(),
        "status": "open",
        "meanings": [item.strip() for item in meanings if item.strip()],
        "resolution": None,
        "question": question,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    return create_record(
        workspace, "language_ambiguity", front, LANGUAGE_AMBIGUITY_TEMPLATE
    )


def resolve_language_ambiguity(
    workspace: Workspace,
    ambiguity_ref: str,
    *,
    resolution: str,
) -> Record:
    record = load_record(workspace, "language_ambiguity", ambiguity_ref)
    record.front_matter["status"] = "resolved"
    record.front_matter["resolution"] = resolution.strip()
    update_record_timestamp(record)
    save_record(record)
    return record


def list_language_records(workspace: Workspace) -> dict[str, list[Record]]:
    return {
        "areas": list_records(workspace, "language_area"),
        "terms": list_records(workspace, "language_term"),
        "ambiguities": list_records(workspace, "language_ambiguity"),
    }
