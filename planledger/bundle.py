# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ledgercore.errors import IdFormatError

from planledger.errors import PlanledgerError
from planledger.guardrails import validate_handoff_contents
from planledger.identity import normalize_plan_selector, plan_ref
from planledger.render import build_plan
from planledger.storage import (
    VALID_STATUSES,
    Workspace,
    apply_plan_mutations,
    component_spec,
    create_plan,
    load_component_contents,
    load_plan,
    preview_plan_id,
    validate_plan,
)

STRUCTURED_PLAN_SCHEMA = "planledger.structured_plan.v1"


def load_bundle(path: Path) -> dict[str, Any]:
    if path.as_posix() == "-":
        content = sys.stdin.read()
    else:
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PlanledgerError(
                "not_found",
                f"Bundle file does not exist: {path}",
            ) from exc
    try:
        loaded = json.loads(content)
    except json.JSONDecodeError as exc:
        raise PlanledgerError(
            "invalid_bundle",
            f"Bundle is not valid JSON: {exc}",
        ) from exc
    if not isinstance(loaded, dict):
        raise PlanledgerError(
            "invalid_bundle",
            "Bundle must be a JSON object.",
        )
    return loaded


def _validate_components(
    components: Any,
    *,
    section_name: str,
    errors: list[str],
) -> dict[str, str]:
    if components is None:
        return {}
    if not isinstance(components, dict):
        errors.append(f"{section_name} must be an object.")
        return {}
    validated: dict[str, str] = {}
    for key, value in components.items():
        try:
            component_spec(key)
        except PlanledgerError as exc:
            errors.append(exc.message)
            continue
        if not isinstance(value, str):
            errors.append(f"Component {key!r} must be a string.")
            continue
        validated[key] = value
    return validated


def _validate_bundle_status(
    status: Any,
    *,
    label: str,
    errors: list[str],
) -> None:
    if status is not None and status not in VALID_STATUSES:
        errors.append(f"{label} status is invalid.")


def _validate_create_bundle(bundle: dict[str, Any], errors: list[str]) -> None:
    plan = bundle.get("plan")
    if not isinstance(plan, dict):
        errors.append("Create bundles require a 'plan' object.")
        return
    title = plan.get("title")
    if not isinstance(title, str) or not title.strip():
        errors.append("Create bundles require plan.title.")
    request = plan.get("request")
    if not isinstance(request, str) or not request.strip():
        errors.append("Create bundles require plan.request.")
    _validate_bundle_status(plan.get("status"), label="Create bundle", errors=errors)
    components = _validate_components(
        plan.get("components"),
        section_name="plan.components",
        errors=errors,
    )
    if plan.get("status") == "done":
        errors.extend(validate_handoff_contents(components))


def _validate_done_update(
    workspace: Workspace,
    plan_id: str,
    components: dict[str, str],
    errors: list[str],
) -> None:
    plan = load_plan(workspace, plan_id)
    current_contents = load_component_contents(plan)
    current_contents.update(components)
    for key, spec in plan.components.items():
        if spec.required and not current_contents.get(key, "").strip():
            errors.append(
                f"Required component {key!r} would be empty "
                "when setting status to done."
            )
    errors.extend(validate_handoff_contents(current_contents))


def _validate_update_bundle(
    bundle: dict[str, Any],
    workspace: Workspace | None,
    errors: list[str],
) -> None:
    plan_id = bundle.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id.strip():
        errors.append("Update bundles require plan_id.")
        return
    reason = bundle.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        errors.append("Update bundles require reason.")
    status = bundle.get("status")
    _validate_bundle_status(status, label="Update bundle", errors=errors)
    components = _validate_components(
        bundle.get("components"),
        section_name="Update bundle components",
        errors=errors,
    )
    if workspace is None or errors:
        return
    try:
        plan_id = normalize_plan_selector(plan_id, ledger_code=workspace.ledger_code)
    except IdFormatError:
        errors.append(f"Invalid plan reference {plan_id!r}.")
        return
    plan = load_plan(workspace, plan_id)
    if plan.status == "cancelled" and bundle.get("force") is not True:
        errors.append("Update targets a cancelled plan without --force.")
    if status == "done":
        _validate_done_update(workspace, plan_id, components, errors)


def validate_structured_plan_bundle(
    bundle: dict[str, Any],
    workspace: Workspace | None = None,
) -> list[str]:
    errors: list[str] = []
    schema = bundle.get("schema")
    if schema != STRUCTURED_PLAN_SCHEMA:
        errors.append(
            "Missing or invalid schema: expected 'planledger.structured_plan.v1'."
        )
    operation = bundle.get("operation")
    if operation not in {"create", "update"}:
        errors.append("Operation must be 'create' or 'update'.")
        return errors
    if operation == "create":
        _validate_create_bundle(bundle, errors)
    else:
        _validate_update_bundle(bundle, workspace, errors)
    return errors


def apply_structured_plan_bundle(
    workspace: Workspace,
    bundle: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    errors = validate_structured_plan_bundle(bundle, workspace)
    if errors:
        raise PlanledgerError(
            "invalid_bundle",
            "Structured plan bundle validation failed.",
            remediation=errors,
        )
    operation = str(bundle["operation"])
    if operation == "create":
        plan_section = bundle["plan"]
        assert isinstance(plan_section, dict)
        components = plan_section.get("components", {})
        assert isinstance(components, dict)
        if dry_run:
            plan_id = preview_plan_id(workspace)
            ref = plan_ref(plan_id, ledger_code=workspace.ledger_code)
            return {
                "operation": "create",
                "dry_run": True,
                "plan_id": plan_id,
                "global_ref": ref.global_ref,
                "file_ref": ref.file_ref,
                "title": str(plan_section["title"]),
                "status": str(plan_section.get("status", "new")),
                "component_keys": sorted(components),
            }
        created = create_plan(
            workspace,
            title=str(plan_section["title"]),
            request=str(plan_section["request"]),
            status=str(plan_section.get("status", "new")),
            components={key: str(value) for key, value in components.items()},
        )
        built = build_plan(workspace, created.plan_id)
        return {
            "operation": "create",
            "dry_run": False,
            "plan": built,
        }
    plan_id = normalize_plan_selector(
        str(bundle["plan_id"]),
        ledger_code=workspace.ledger_code,
    )
    reason = str(bundle["reason"])
    components = bundle.get("components", {})
    assert isinstance(components, dict)
    plan_before = load_plan(workspace, plan_id)
    if dry_run:
        ref = plan_ref(plan_id, ledger_code=workspace.ledger_code)
        return {
            "operation": "update",
            "dry_run": True,
            "plan_id": plan_id,
            "global_ref": ref.global_ref,
            "file_ref": ref.file_ref,
            "current_version": plan_before.version,
            "next_version": plan_before.version + 1,
            "status": bundle.get("status", plan_before.status),
            "component_keys": sorted(components),
        }
    updated = apply_plan_mutations(
        workspace,
        plan_id,
        component_updates={key: str(value) for key, value in components.items()},
        status=str(bundle["status"]) if "status" in bundle else None,
        reason=reason,
        force=bool(bundle.get("force", False)),
    )
    validation_errors = validate_plan(updated, for_done=updated.status == "done")
    if validation_errors:
        raise PlanledgerError(
            "invalid_plan",
            "Updated plan failed validation.",
            remediation=validation_errors,
        )
    built = build_plan(workspace, plan_id)
    return {
        "operation": "update",
        "dry_run": False,
        "plan": built,
    }


from planledger.guardrails import validate_workshop_contents
from planledger.identity import normalize_workshop_selector, workshop_ref
from planledger.render import build_workshop
from planledger.storage import (
    apply_workshop_mutations,
    create_workshop,
    load_workshop,
    preview_workshop_id,
    validate_workshop,
    workshop_component_spec,
)

STRUCTURED_WORKSHOP_SCHEMA = "planledger.structured_workshop.v1"


def _validate_workshop_components(
    components: Any, *, section_name: str, errors: list[str]
) -> dict[str, str]:
    if components is None:
        return {}
    if not isinstance(components, dict):
        errors.append(f"{section_name} must be an object.")
        return {}
    out: dict[str, str] = {}
    for key, value in components.items():
        try:
            workshop_component_spec(key)
        except PlanledgerError as exc:
            errors.append(exc.message)
            continue
        if not isinstance(value, str):
            errors.append(f"Component {key!r} must be a string.")
            continue
        out[key] = value
    return out


def validate_structured_workshop_bundle(
    bundle: dict[str, Any], workspace: Workspace | None = None
) -> list[str]:
    errors: list[str] = []
    if bundle.get("schema") != STRUCTURED_WORKSHOP_SCHEMA:
        errors.append(
            "Missing or invalid schema: expected 'planledger.structured_workshop.v1'."
        )
    op = bundle.get("operation")
    if op not in {"create", "update"}:
        errors.append("Operation must be 'create' or 'update'.")
        return errors
    if op == "create":
        workshop = bundle.get("workshop")
        if not isinstance(workshop, dict):
            errors.append("Create bundles require a 'workshop' object.")
            return errors
        if (
            not isinstance(workshop.get("title"), str)
            or not workshop.get("title", "").strip()
        ):
            errors.append("Create bundles require workshop.title.")
        if (
            not isinstance(workshop.get("request"), str)
            or not workshop.get("request", "").strip()
        ):
            errors.append("Create bundles require workshop.request.")
        comps = _validate_workshop_components(
            workshop.get("components"),
            section_name="workshop.components",
            errors=errors,
        )
        status = workshop.get("status", "new")
        if status == "shaped":
            contents = {**comps, "request": str(workshop.get("request", ""))}
            errors.extend(validate_workshop_contents(contents))
    else:
        wid = bundle.get("workshop_id")
        if not isinstance(wid, str) or not wid.strip():
            errors.append("Update bundles require workshop_id.")
            return errors
        if (
            not isinstance(bundle.get("reason"), str)
            or not bundle.get("reason", "").strip()
        ):
            errors.append("Update bundles require reason.")
        _validate_workshop_components(
            bundle.get("components"),
            section_name="Update bundle components",
            errors=errors,
        )
        if workspace is not None and not errors:
            try:
                normalize_workshop_selector(wid, ledger_code=workspace.ledger_code)
            except IdFormatError:
                errors.append(f"Invalid workshop reference {wid!r}.")
    return errors


def apply_structured_workshop_bundle(
    workspace: Workspace, bundle: dict[str, Any], *, dry_run: bool = False
) -> dict[str, Any]:
    errors = validate_structured_workshop_bundle(bundle, workspace)
    if errors:
        raise PlanledgerError(
            "invalid_bundle",
            "Structured workshop bundle validation failed.",
            remediation=errors,
        )
    if bundle["operation"] == "create":
        sec = bundle["workshop"]
        assert isinstance(sec, dict)
        comps = sec.get("components", {})
        assert isinstance(comps, dict)
        if dry_run:
            wid = preview_workshop_id(workspace)
            ref = workshop_ref(wid, ledger_code=workspace.ledger_code)
            return {
                "operation": "create",
                "dry_run": True,
                "workshop_id": wid,
                "global_ref": ref.global_ref,
                "file_ref": ref.file_ref,
                "title": str(sec["title"]),
                "status": str(sec.get("status", "new")),
                "component_keys": sorted(comps),
            }
        created = create_workshop(
            workspace,
            str(sec["title"]),
            str(sec["request"]),
            str(sec.get("status", "new")),
            components={k: str(v) for k, v in comps.items()},
        )
        return {
            "operation": "create",
            "dry_run": False,
            "workshop": build_workshop(workspace, created.workshop_id),
        }
    wid = normalize_workshop_selector(
        str(bundle["workshop_id"]), ledger_code=workspace.ledger_code
    )
    comps = bundle.get("components", {})
    assert isinstance(comps, dict)
    before = load_workshop(workspace, wid)
    if dry_run:
        ref = workshop_ref(wid, ledger_code=workspace.ledger_code)
        return {
            "operation": "update",
            "dry_run": True,
            "workshop_id": wid,
            "global_ref": ref.global_ref,
            "file_ref": ref.file_ref,
            "current_version": before.version,
            "next_version": before.version + 1,
            "status": bundle.get("status", before.status),
            "component_keys": sorted(comps),
        }
    updated = apply_workshop_mutations(
        workspace,
        wid,
        component_updates={k: str(v) for k, v in comps.items()},
        status=str(bundle["status"]) if "status" in bundle else None,
        reason=str(bundle["reason"]),
        force=bool(bundle.get("force", False)),
    )
    errs = validate_workshop(updated, for_shaped=updated.status == "shaped")
    if errs:
        raise PlanledgerError(
            "invalid_workshop", "Updated workshop failed validation.", remediation=errs
        )
    return {
        "operation": "update",
        "dry_run": False,
        "workshop": build_workshop(workspace, wid),
    }
