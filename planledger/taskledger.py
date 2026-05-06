# ruff: noqa: E501
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from planledger.errors import PlanledgerError
from planledger.models import Workspace
from planledger.storage import (
    allocate_id,
    append_event,
    create_record,
    list_records,
    load_record,
    now_iso,
    save_record,
    slugify,
    update_record_timestamp,
)


def taskledger_settings(workspace: Workspace) -> tuple[str, Path]:
    integration = dict(
        workspace.config.get("integrations", {}).get("taskledger", {})  # type: ignore[union-attr]
    )
    command = str(integration.get("command", "taskledger"))
    workspace_root = Path(integration.get("workspace_root", "."))
    if not workspace_root.is_absolute():
        workspace_root = (workspace.root / workspace_root).resolve()
    return command, workspace_root


def run_taskledger_json(
    workspace: Workspace,
    args: list[str],
) -> dict[str, Any]:
    command, workspace_root = taskledger_settings(workspace)
    full_command = [command, "--json", *args]
    proc = subprocess.run(
        full_command,
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise PlanledgerError(
            "taskledger_error",
            f"taskledger command failed: {' '.join(full_command)}",
            remediation=[
                proc.stderr.strip() or proc.stdout.strip() or "Check taskledger setup."
            ],
        )
    stdout = proc.stdout.strip()
    if not stdout:
        return {}
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise PlanledgerError(
            "taskledger_error",
            "taskledger returned non-JSON output.",
            remediation=[f"Output: {stdout[:200]}"],
        ) from error
    if isinstance(data, dict):
        return data
    return {"value": data}


def _unwrap_result(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if isinstance(result, dict):
        return result
    return payload


def detect(workspace: Workspace) -> dict[str, Any]:
    command, workspace_root = taskledger_settings(workspace)
    executable = shutil.which(command)
    config_path = workspace_root / "taskledger.toml"

    detected = executable is not None and config_path.exists()
    ledger_ref = None
    active_task: dict[str, Any] | None = None

    if detected:
        payload = run_taskledger_json(workspace, ["status", "--full"])
        result = _unwrap_result(payload)
        ledger_ref = result.get("ledger_ref") or result.get("ledger")
        task = result.get("active_task")
        if isinstance(task, dict):
            task_ref = task.get("task_ref") or task.get("id")
            slug = task.get("slug")
            if task_ref or slug:
                active_task = {
                    "task_ref": task_ref,
                    "slug": slug,
                }

    return {
        "kind": "planledger_taskledger_detect",
        "detected": detected,
        "workspace_root": str(workspace_root),
        "config_path": str(config_path),
        "ledger_ref": ledger_ref,
        "active_task": active_task,
    }


def _extract_task_ref(
    task_payload: dict[str, Any], fallback_slug: str | None = None
) -> tuple[str, str | None, str | None]:
    payload = _unwrap_result(task_payload)
    task_ref = payload.get("task_ref") or payload.get("id") or payload.get("ref")
    slug = payload.get("slug") or fallback_slug
    status = payload.get("status")
    if not task_ref:
        task_ref = fallback_slug
    if not task_ref:
        raise PlanledgerError("taskledger_error", "Could not determine task reference.")
    return str(task_ref), str(slug) if slug else None, str(status) if status else None


def _update_slice_binding(
    slice_record: Any, binding_id: str, set_in_execution: bool = True
) -> None:
    bindings = list(slice_record.front_matter.get("taskledger_bindings") or [])
    if binding_id not in bindings:
        bindings.append(binding_id)
    slice_record.front_matter["taskledger_bindings"] = bindings
    if set_in_execution:
        current_status = str(slice_record.front_matter.get("status", ""))
        terminal = {"executed", "validated", "dropped", "superseded", "archived"}
        if current_status not in terminal:
            slice_record.front_matter["status"] = "in-execution"
    update_record_timestamp(slice_record)


def _create_binding(
    workspace: Workspace,
    slice_record: Any,
    task_ref: str,
    task_slug: str | None,
    task_status: str | None,
    command_name: str,
) -> Any:
    binding_id = allocate_id(workspace, "binding")
    integration_command, workspace_root = taskledger_settings(workspace)
    binding_front = {
        "id": binding_id,
        "type": "binding",
        "provider": "taskledger",
        "planledger_ref": slice_record.record_id,
        "workspace_root": str(workspace_root),
        "taskledger_config": str(workspace_root / "taskledger.toml"),
        "ledger_ref": workspace.ledger_ref,
        "task_ref": task_ref,
        "task_slug": task_slug,
        "sync_direction": "pull-status",
        "last_seen_status": task_status,
        "last_seen_validation": None,
        "last_sync_at": now_iso(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "integration_command": integration_command,
    }
    binding = create_record(workspace, "binding", binding_front, "")
    _update_slice_binding(slice_record, binding_id, set_in_execution=True)
    save_record(slice_record)
    append_event(
        workspace,
        command=command_name,
        object_type="slice",
        object_id=slice_record.record_id,
        event_type="taskledger_binding_created",
        after={"binding": binding_id, "task_ref": task_ref},
    )
    return binding


def bind_slice(workspace: Workspace, slice_id: str, task_ref: str) -> dict[str, Any]:
    slice_record = load_record(workspace, "slice", slice_id)
    task_payload = run_taskledger_json(workspace, ["task", "show", task_ref])
    confirmed_task_ref, task_slug, task_status = _extract_task_ref(
        task_payload, fallback_slug=task_ref
    )
    binding = _create_binding(
        workspace,
        slice_record,
        task_ref=confirmed_task_ref,
        task_slug=task_slug,
        task_status=task_status,
        command_name=f"planledger taskledger bind {slice_id} --task {task_ref}",
    )
    return {
        "kind": "planledger_taskledger_bind",
        "slice": slice_id,
        "task_ref": confirmed_task_ref,
        "binding": binding.record_id,
    }


def push_slice(
    workspace: Workspace,
    slice_id: str,
    create_task: bool,
    activate: bool,
) -> dict[str, Any]:
    if not create_task:
        raise PlanledgerError(
            "unsupported",
            "Use --create-task for MVP push behavior.",
            remediation=["Run: planledger taskledger push SLICE --create-task"],
        )
    slice_record = load_record(workspace, "slice", slice_id)
    if slice_record.front_matter.get("status") != "ready-for-execution":
        raise PlanledgerError(
            "invalid_state",
            f"Slice {slice_id} must be ready-for-execution before push.",
            remediation=[f"Run: planledger slice ready {slice_id}"],
        )

    title = str(slice_record.front_matter.get("title", "Untitled slice"))
    slug = slugify(title)
    description = f"Generated from planledger {slice_id}."
    create_payload = run_taskledger_json(
        workspace,
        ["task", "create", title, "--slug", slug, "--description", description],
    )
    task_ref, task_slug, task_status = _extract_task_ref(
        create_payload, fallback_slug=slug
    )

    if activate:
        run_taskledger_json(
            workspace,
            [
                "task",
                "activate",
                task_ref,
                "--reason",
                f"Execution started from planledger {slice_id}.",
            ],
        )

    binding = _create_binding(
        workspace,
        slice_record,
        task_ref=task_ref,
        task_slug=task_slug,
        task_status=task_status,
        command_name=(
            f"planledger taskledger push {slice_id} --create-task"
            + (" --activate" if activate else "")
        ),
    )

    return {
        "kind": "planledger_taskledger_push",
        "slice": slice_id,
        "task_ref": task_ref,
        "task_slug": task_slug,
        "binding": binding.record_id,
        "activated": activate,
    }


def _pull_for_binding(workspace: Workspace, binding: Any) -> dict[str, Any]:
    task_ref = str(binding.front_matter.get("task_ref"))
    payload = run_taskledger_json(workspace, ["task", "show", task_ref])
    task_result = _unwrap_result(payload)
    status = str(task_result.get("status", "unknown"))
    next_action: str | None = None
    try:
        next_payload = run_taskledger_json(
            workspace, ["next-action", "--task", task_ref]
        )
        next_result = _unwrap_result(next_payload)
        next_action = (
            next_result.get("action")
            or next_result.get("next_action")
            or next_result.get("kind")
        )
        if next_action is not None:
            next_action = str(next_action)
    except PlanledgerError:
        next_action = None

    progress = task_result.get("progress")
    if not isinstance(progress, dict):
        progress = {}

    binding.front_matter["last_seen_status"] = status
    binding.front_matter["last_seen_next_action"] = next_action
    binding.front_matter["last_seen_progress"] = progress
    binding.front_matter["last_seen_validation"] = task_result.get("validation")
    binding.front_matter["last_sync_at"] = now_iso()
    update_record_timestamp(binding)
    save_record(binding)

    slice_ref = str(binding.front_matter.get("planledger_ref"))
    slice_record = load_record(workspace, "slice", slice_ref)
    slice_record.front_matter["execution_provider"] = "taskledger"
    slice_record.front_matter["execution_status"] = status
    if slice_record.front_matter.get("status") in {
        "ready-for-execution",
        "in-execution",
    }:
        slice_record.front_matter["status"] = "in-execution"
    update_record_timestamp(slice_record)
    save_record(slice_record)

    return {
        "binding": binding.record_id,
        "slice": slice_ref,
        "task_ref": task_ref,
        "status": status,
        "next_action": next_action,
    }


def pull_status(workspace: Workspace, slice_id: str | None = None) -> dict[str, Any]:
    bindings = list_records(workspace, "binding")
    if slice_id is not None:
        bindings = [
            binding
            for binding in bindings
            if binding.front_matter.get("planledger_ref") == slice_id
        ]
    pulled = [_pull_for_binding(workspace, binding) for binding in bindings]
    return {
        "kind": "planledger_taskledger_pull",
        "count": len(pulled),
        "bindings": pulled,
    }


def _missing_task_drift(slice_id: str, task_ref: str) -> dict[str, Any]:
    return {
        "kind": "missing_task",
        "slice": slice_id,
        "task": task_ref,
        "suggested_command": f"planledger taskledger unbind {slice_id} --task {task_ref}",
    }


def reconcile(workspace: Workspace) -> dict[str, Any]:
    drift: list[dict[str, Any]] = []
    bindings = list_records(workspace, "binding")
    by_slice: dict[str, list[Any]] = {}
    for binding in bindings:
        slice_ref = str(binding.front_matter.get("planledger_ref"))
        by_slice.setdefault(slice_ref, []).append(binding)

    for slice_ref, slice_bindings in by_slice.items():
        if len(slice_bindings) > 1:
            drift.append(
                {
                    "kind": "multiple_bindings",
                    "slice": slice_ref,
                    "tasks": [
                        str(item.front_matter.get("task_ref"))
                        for item in slice_bindings
                    ],
                    "suggested_command": f"planledger taskledger pull --slice {slice_ref}",
                }
            )

    for binding in bindings:
        slice_ref = str(binding.front_matter.get("planledger_ref"))
        task_ref = str(binding.front_matter.get("task_ref"))
        try:
            task_payload = run_taskledger_json(workspace, ["task", "show", task_ref])
        except PlanledgerError:
            drift.append(_missing_task_drift(slice_ref, task_ref))
            continue

        task_status = str(_unwrap_result(task_payload).get("status", "unknown"))
        slice_record = load_record(workspace, "slice", slice_ref)
        slice_status = str(slice_record.front_matter.get("status", ""))

        if slice_status == "ready-for-execution" and task_status in {
            "planning",
            "implementation",
            "validation",
            "done",
            "failed",
        }:
            drift.append(
                {
                    "kind": "slice_ready_but_task_active",
                    "slice": slice_ref,
                    "task": task_ref,
                    "suggested_command": f"planledger slice ready {slice_ref}",
                }
            )

        if slice_status == "in-execution" and task_status == "done":
            drift.append(
                {
                    "kind": "slice_done_in_taskledger",
                    "slice": slice_ref,
                    "task": task_ref,
                    "suggested_command": (
                        f"planledger slice done {slice_ref} "
                        f'--evidence "taskledger {task_ref} done"'
                    ),
                }
            )

        if slice_status == "executed" and task_status == "failed":
            drift.append(
                {
                    "kind": "validation_failed",
                    "slice": slice_ref,
                    "task": task_ref,
                    "suggested_command": f"planledger slice ready {slice_ref}",
                }
            )

    return {
        "kind": "planledger_taskledger_reconcile",
        "drift": drift,
    }


def generate_plan_template(
    workspace: Workspace, slice_id: str, output: Path
) -> dict[str, Any]:
    slice_record = load_record(workspace, "slice", slice_id)
    plan_id = str(slice_record.front_matter.get("plan"))
    milestone_id = str(slice_record.front_matter.get("milestone"))
    initiative_id = str(slice_record.front_matter.get("initiative"))

    decisions = [
        decision
        for decision in list_records(workspace, "decision")
        if decision.front_matter.get("initiative") == initiative_id
        and decision.front_matter.get("status") == "accepted"
    ]
    risks = [
        risk
        for risk in list_records(workspace, "risk")
        if risk.front_matter.get("initiative") == initiative_id
    ]

    lines = [
        "# Taskledger plan generated from planledger",
        "",
        "Source:",
        f"- initiative: {initiative_id}",
        f"- plan: {plan_id}",
        f"- milestone: {milestone_id}",
        f"- slice: {slice_id}",
        "",
        "Planning rationale:",
    ]

    if decisions:
        for decision in decisions:
            chosen = decision.front_matter.get("chosen_option")
            lines.append(f"- Decision {decision.record_id} accepted option {chosen}.")
    else:
        lines.append("- No accepted decision recorded.")

    if risks:
        main_risk = risks[0]
        lines.append(f"- Main risk: {main_risk.front_matter.get('title')}")
    else:
        lines.append("- Main risk: not recorded.")

    lines.extend(
        [
            "- Constraint: use taskledger JSON output.",
            "",
            "## Implementation todos",
            "",
            "- Add taskledger detection.",
            "- Add task creation adapter.",
            "- Add status pull/reconcile.",
            "",
            "## Acceptance criteria",
            "",
            "- Can bind a planledger slice to a taskledger task.",
            "- Can pull task status from taskledger.",
            "- Can detect stale or missing bindings.",
            "",
            "## Validation hints",
            "",
            "- Run unit tests for taskledger integration.",
            "- Run CLI smoke tests with a temporary workspace.",
            "",
        ]
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")

    return {
        "kind": "planledger_taskledger_plan_template",
        "slice": slice_id,
        "output": str(output),
    }
