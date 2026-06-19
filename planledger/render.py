# ruff: noqa: E402,E501
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from planledger.errors import PlanledgerError
from planledger.identity import DEFAULT_LEDGER_CODE, PLAN_KIND, plan_ref
from planledger.models import Plan
from planledger.storage import (
    Workspace,
    latest_rendered_path,
    load_component_content,
    load_plan,
    now_iso,
    ordered_component_keys,
    plan_to_dict,
    save_plan_metadata,
    validate_plan,
    version_label,
    versioned_rendered_path,
)

RENDERED_PLAN_SCHEMA = "planledger.rendered_plan.v1"


def render_plan_markdown(
    plan: Plan,
    *,
    include_empty: bool = False,
    generated_at: str | None = None,
    ledger_code: str = DEFAULT_LEDGER_CODE,
) -> str:
    timestamp = generated_at or now_iso()
    ref = plan_ref(plan.plan_id, ledger_code=ledger_code)
    header = {
        "planledger_schema": RENDERED_PLAN_SCHEMA,
        "plan_id": plan.plan_id,
        "id": plan.plan_id,
        "kind": PLAN_KIND,
        "ledger_code": ref.ledger,
        "global_ref": ref.global_ref,
        "file_ref": ref.file_ref,
        "title": plan.title,
        "status": plan.status,
        "version": plan.version,
        "generated_at": timestamp,
    }
    yaml_header = yaml.safe_dump(
        header,
        sort_keys=False,
        allow_unicode=True,
    ).rstrip("\n")
    lines = [
        "---",
        yaml_header,
        "---",
        "",
        f"# {plan.title}",
        "",
        f"Plan: `{plan.plan_id}`  ",
        f"Ref: `{ref.global_ref}`  ",
        f"Version: `{version_label(plan.version)}`  ",
        f"Status: `{plan.status}`",
        "",
    ]
    for key in ordered_component_keys(plan.components):
        spec = plan.components[key]
        content = load_component_content(plan, key)
        if not content.strip() and not include_empty and not spec.required:
            continue
        lines.append(f"## {spec.title}")
        lines.append("")
        if content:
            lines.append(content.rstrip("\n"))
        lines.append("")
    history = plan.metadata.get("history", [])
    lines.append("## Change history")
    lines.append("")
    if isinstance(history, list) and history:
        for entry in history:
            if not isinstance(entry, dict):
                continue
            version = version_label(int(entry.get("version", 0)))
            status = str(entry.get("status") or "")
            reason = str(entry.get("reason") or "").strip()
            suffix = f" — {reason}" if reason else ""
            lines.append(f"- {version} — {status}{suffix}")
    else:
        lines.append("- No recorded changes.")
    lines.append("")
    return "\n".join(lines)


def build_plan(
    workspace: Workspace,
    plan_id: str,
    *,
    out: Path | None = None,
    include_empty: bool = False,
) -> dict[str, Any]:
    plan = load_plan(workspace, plan_id)
    errors = validate_plan(plan, for_done=plan.status == "done")
    if errors:
        raise PlanledgerError(
            "invalid_plan",
            f"Plan {plan_id} is invalid.",
            remediation=errors,
        )
    last_rendered = plan.metadata.get("last_rendered")
    if (
        isinstance(last_rendered, dict)
        and int(last_rendered.get("version", 0)) == plan.version
        and versioned_rendered_path(plan).exists()
        and isinstance(last_rendered.get("generated_at"), str)
    ):
        generated_at = str(last_rendered["generated_at"])
    else:
        generated_at = now_iso()
    markdown = render_plan_markdown(
        plan,
        include_empty=include_empty,
        generated_at=generated_at,
        ledger_code=workspace.ledger_code,
    )
    rendered_path = versioned_rendered_path(plan)
    rendered_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_path.write_text(markdown, encoding="utf-8")
    latest_path = latest_rendered_path(plan)
    latest_path.write_text(markdown, encoding="utf-8")
    output_path = None
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        output_path = str(out)
    plan.metadata["last_rendered"] = {
        "version": plan.version,
        "path": rendered_path.relative_to(plan.path).as_posix(),
        "generated_at": generated_at,
    }
    save_plan_metadata(plan)
    result = plan_to_dict(
        load_plan(workspace, plan_id),
        ledger_code=workspace.ledger_code,
    )
    result.update(
        {
            "generated_at": generated_at,
            "rendered_path": str(rendered_path),
            "latest_rendered_path": str(latest_path),
            "output_path": output_path,
            "markdown": markdown,
        }
    )
    return result


from planledger.identity import WORKSHOP_KIND, workshop_ref
from planledger.models import Workshop
from planledger.storage import (
    latest_rendered_workshop_path,
    load_workshop,
    load_workshop_component_content,
    save_workshop_metadata,
    validate_workshop,
    versioned_rendered_workshop_path,
    workshop_to_dict,
)

RENDERED_WORKSHOP_SCHEMA = "planledger.rendered_workshop.v1"


def render_workshop_markdown(
    workshop: Workshop,
    *,
    include_empty: bool = False,
    generated_at: str | None = None,
    ledger_code: str = DEFAULT_LEDGER_CODE,
) -> str:
    timestamp = generated_at or now_iso()
    ref = workshop_ref(workshop.workshop_id, ledger_code=ledger_code)
    header = {
        "planledger_schema": RENDERED_WORKSHOP_SCHEMA,
        "workshop_id": workshop.workshop_id,
        "id": workshop.workshop_id,
        "kind": WORKSHOP_KIND,
        "ledger_code": ref.ledger,
        "global_ref": ref.global_ref,
        "file_ref": ref.file_ref,
        "title": workshop.title,
        "status": workshop.status,
        "version": workshop.version,
        "generated_at": timestamp,
        "linked_plans": workshop.metadata.get("linked_plans", []),
    }
    yaml_header = yaml.safe_dump(header, sort_keys=False, allow_unicode=True).rstrip(
        "\n"
    )
    lines = [
        "---",
        yaml_header,
        "---",
        "",
        f"# {workshop.title}",
        "",
        f"Workshop: `{workshop.workshop_id}`  ",
        f"Ref: `{ref.global_ref}`  ",
        f"Version: `{version_label(workshop.version)}`  ",
        f"Status: `{workshop.status}`",
        "",
    ]
    for key in ordered_component_keys(workshop.components):
        spec = workshop.components[key]
        content = load_workshop_component_content(workshop, key)
        if not content.strip() and not include_empty and not spec.required:
            continue
        lines += [f"## {spec.title}", ""]
        if content:
            lines.append(content.rstrip("\n"))
        lines.append("")
    lines += ["## Change history", ""]
    history = workshop.metadata.get("history", [])
    if isinstance(history, list) and history:
        for entry in history:
            if isinstance(entry, dict):
                reason = str(entry.get("reason") or "").strip()
                suffix = f" — {reason}" if reason else ""
                lines.append(
                    f"- {version_label(int(entry.get('version', 0)))} — {entry.get('status', '')}{suffix}"
                )
    else:
        lines.append("- No recorded changes.")
    lines.append("")
    return "\n".join(lines)


def build_workshop(
    workspace: Workspace,
    workshop_id: str,
    *,
    out: Path | None = None,
    include_empty: bool = False,
) -> dict[str, Any]:
    workshop = load_workshop(workspace, workshop_id)
    errors = validate_workshop(workshop, for_shaped=workshop.status == "shaped")
    if errors:
        raise PlanledgerError(
            "invalid_workshop",
            f"Workshop {workshop_id} is invalid.",
            remediation=errors,
        )
    last = workshop.metadata.get("last_rendered")
    if (
        isinstance(last, dict)
        and int(last.get("version", 0)) == workshop.version
        and versioned_rendered_workshop_path(workshop).exists()
        and isinstance(last.get("generated_at"), str)
    ):
        generated_at = str(last["generated_at"])
    else:
        generated_at = now_iso()
    markdown = render_workshop_markdown(
        workshop,
        include_empty=include_empty,
        generated_at=generated_at,
        ledger_code=workspace.ledger_code,
    )
    rendered_path = versioned_rendered_workshop_path(workshop)
    rendered_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_path.write_text(markdown, encoding="utf-8")
    latest = latest_rendered_workshop_path(workshop)
    latest.write_text(markdown, encoding="utf-8")
    output_path = None
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        output_path = str(out)
    workshop.metadata["last_rendered"] = {
        "version": workshop.version,
        "path": rendered_path.relative_to(workshop.path).as_posix(),
        "generated_at": generated_at,
    }
    save_workshop_metadata(workshop)
    result = workshop_to_dict(
        load_workshop(workspace, workshop_id), ledger_code=workspace.ledger_code
    )
    result.update(
        {
            "generated_at": generated_at,
            "rendered_path": str(rendered_path),
            "latest_rendered_path": str(latest),
            "output_path": output_path,
            "markdown": markdown,
        }
    )
    return result
