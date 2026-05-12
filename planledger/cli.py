# ruff: noqa: B008, E501
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from planledger import __version__
from planledger.backfill import backfill_apply, backfill_review
from planledger.bundle import (
    apply_bundle,
    apply_evolution_bundle,
    load_bundle,
    validate_bundle_details,
    validate_evolution_details,
)
from planledger.context import export_context
from planledger.errors import PlanledgerError
from planledger.lifecycle import (
    ACTIVE_GOAL_STATUSES,
    EXECUTION_BLOCKING_GOAL_STATUSES,
    EXECUTION_BLOCKING_INITIATIVE_STATUSES,
    TERMINAL_GOAL_STATUSES,
    TERMINAL_INITIATIVE_STATUSES,
    TERMINAL_PLAN_STATUSES,
    blocks_execution,
    is_terminal,
    link_records,
    require_not_terminal,
    transition_record,
)
from planledger.models import AppContext, Record
from planledger.next_action import suggest_next_action
from planledger.storage import (
    ADR_TEMPLATE,
    DECISION_TEMPLATE,
    OPTION_TEMPLATE,
    active_initiative,
    allocate_id,
    append_event,
    create_record,
    doctor,
    initialize_project,
    latest_plan_for_initiative,
    lint_plan,
    list_records,
    load_record,
    load_workspace,
    now_iso,
    parse_ref_numeric,
    record_counts,
    reindex,
    render_plan_template,
    save_record,
    set_active_initiative,
    update_record_timestamp,
    workspace_root_from_context,
)
from planledger.taskledger import (
    bind_slice,
    detect,
    generate_plan_template,
    pull_status,
    push_plan,
    push_slice,
    reconcile,
)

app = typer.Typer(help="Durable planning ledger")
goal_app = typer.Typer(help="Goal commands")
initiative_app = typer.Typer(help="Initiative commands")
plan_app = typer.Typer(help="Plan commands")
milestone_app = typer.Typer(help="Milestone commands")
slice_app = typer.Typer(help="Slice commands")
decision_app = typer.Typer(help="Decision commands")
option_app = typer.Typer(help="Option commands")
risk_app = typer.Typer(help="Risk commands")
question_app = typer.Typer(help="Question commands")
assumption_app = typer.Typer(help="Assumption commands")
constraint_app = typer.Typer(help="Constraint commands")
review_app = typer.Typer(help="Review commands")
taskledger_app = typer.Typer(help="taskledger integration")
bundle_app = typer.Typer(help="Bundle import")
evolution_app = typer.Typer(help="Evolution bundle commands")
context_app = typer.Typer(help="Context export")
adr_app = typer.Typer(help="Architectural Decision Records")
backfill_app = typer.Typer(help="Existing project backfill")
app.add_typer(goal_app, name="goal")
app.add_typer(initiative_app, name="initiative")
app.add_typer(plan_app, name="plan")
app.add_typer(milestone_app, name="milestone")
app.add_typer(slice_app, name="slice")
app.add_typer(decision_app, name="decision")
app.add_typer(option_app, name="option")
app.add_typer(risk_app, name="risk")
app.add_typer(question_app, name="question")
app.add_typer(assumption_app, name="assumption")
app.add_typer(constraint_app, name="constraint")
app.add_typer(review_app, name="review")
app.add_typer(taskledger_app, name="taskledger")
app.add_typer(bundle_app, name="bundle")
app.add_typer(evolution_app, name="evolution")
app.add_typer(context_app, name="context")
app.add_typer(adr_app, name="adr")
app.add_typer(backfill_app, name="backfill")

PRIORITY_LEVELS = {"low", "medium", "high"}
GOAL_HORIZONS = {"now", "week", "month", "quarter", "later"}
ACTIVE_PLAN_STATUSES = {"draft", "accepted"}
QUESTION_TEMPLATE = "# Question\n\n## Context\n\n## Answer\n"
ASSUMPTION_TEMPLATE = "# Assumption\n\n## Basis\n\n## Evidence\n"
CONSTRAINT_TEMPLATE = "# Constraint\n\n## Rationale\n"
REVIEW_TEMPLATE = (
    "# Review\n\n## Findings\n\n## Recommendations\n"
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    root: Path | None = typer.Option(None, "--root", help="Project root override"),
    cwd: Path | None = typer.Option(
        None, "--cwd", help="Current workspace for discovery"
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON envelope"),
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version",
    ),
) -> None:
    _ = version
    ctx.obj = AppContext(root=root, cwd=cwd, json_output=json_output)


def _context(ctx: typer.Context) -> AppContext:
    app_ctx = ctx.obj
    if not isinstance(app_ctx, AppContext):
        raise PlanledgerError("internal_error", "Missing application context")
    return app_ctx


def _emit_success(
    app_ctx: AppContext,
    command: str,
    result: dict[str, Any],
    events: list[dict[str, Any]],
    message: str,
) -> None:
    if app_ctx.json_output:
        payload = {
            "ok": True,
            "command": command,
            "result": result,
            "events": events,
        }
        typer.echo(json.dumps(payload, indent=2, default=str))
        return
    typer.echo(message)


def _emit_error(app_ctx: AppContext, command: str, error: PlanledgerError) -> None:
    if app_ctx.json_output:
        payload = {
            "ok": False,
            "command": command,
            "error": error.to_dict(),
        }
        typer.echo(json.dumps(payload, indent=2, default=str))
    else:
        typer.echo(f"Error [{error.kind}]: {error.message}")
        for item in error.remediation:
            typer.echo(f"- {item}")


def _run_command(
    ctx: typer.Context,
    command: str,
    fn: Callable[[], tuple[dict[str, Any], str, list[dict[str, Any]]]],
) -> None:
    app_ctx = _context(ctx)
    try:
        result, message, events = fn()
    except PlanledgerError as error:
        _emit_error(app_ctx, command, error)
        raise typer.Exit(code=error.exit_code) from error
    except Exception as error:  # pragma: no cover
        wrapped = PlanledgerError("internal_error", str(error))
        _emit_error(app_ctx, command, wrapped)
        raise typer.Exit(code=1) from error
    _emit_success(app_ctx, command, result, events, message)


def _resolve_workspace(ctx: typer.Context) -> Any:
    app_ctx = _context(ctx)
    return load_workspace(app_ctx)


def _record_human(record: Record) -> str:
    title = record.front_matter.get("title")
    status = record.front_matter.get("status")
    lines = [f"{record.record_id} ({record.kind})"]
    if title:
        lines.append(f"title: {title}")
    if status:
        lines.append(f"status: {status}")
    lines.append(f"path: {record.path}")
    if record.body.strip():
        lines.append("")
        lines.append(record.body.strip())
    return "\n".join(lines)


def _validate_choice(field_name: str, value: str, allowed: set[str]) -> str:
    if value not in allowed:
        raise PlanledgerError(
            "invalid_option",
            f"Invalid {field_name} {value!r}. Allowed: {sorted(allowed)}.",
        )
    return value


def _sort_records(records: list[Record]) -> list[Record]:
    return sorted(records, key=lambda item: parse_ref_numeric(item.record_id))


def _filter_records(
    records: list[Record],
    *,
    status: str | None,
    active: bool,
    closed: bool,
    all_records: bool,
    active_statuses: set[str],
    terminal_statuses: set[str],
) -> list[Record]:
    selected_flags = sum(
        (
            1 if status is not None else 0,
            1 if active else 0,
            1 if closed else 0,
            1 if all_records else 0,
        )
    )
    if selected_flags > 1:
        raise PlanledgerError(
            "invalid_options",
            "Use at most one of --status, --active, --closed, or --all.",
        )
    if status is not None:
        return [item for item in records if item.front_matter.get("status") == status]
    if active:
        return [
            item for item in records if item.front_matter.get("status") in active_statuses
        ]
    if closed:
        return [
            item
            for item in records
            if item.front_matter.get("status") in terminal_statuses
        ]
    return records


def _format_record_line(record: Record, *, active_marker: bool = False) -> str:
    title = str(record.front_matter.get("title") or "")
    status = str(record.front_matter.get("status") or "unknown")
    line = f"{record.record_id} {title} [{status}]".strip()
    close_reason = record.front_matter.get("close_reason")
    if close_reason:
        line += f" — {close_reason}"
    if active_marker:
        return f"* {line}"
    return line


def _goal_for_initiative(workspace: Any, initiative_record: Record) -> Record | None:
    goal_ref = initiative_record.front_matter.get("goal")
    if goal_ref is None:
        return None
    return load_record(workspace, "goal", str(goal_ref))


def _initiative_for_plan(workspace: Any, plan_record: Record) -> Record:
    initiative_ref = plan_record.front_matter.get("initiative")
    if initiative_ref is None:
        raise PlanledgerError(
            "invalid_record",
            f"Plan {plan_record.record_id} has no initiative reference.",
        )
    return load_record(workspace, "initiative", str(initiative_ref))


def _goal_for_plan(workspace: Any, plan_record: Record) -> Record | None:
    initiative_record = _initiative_for_plan(workspace, plan_record)
    return _goal_for_initiative(workspace, initiative_record)


def _plan_for_slice(workspace: Any, slice_record: Record) -> Record:
    plan_ref = slice_record.front_matter.get("plan")
    if plan_ref is None:
        raise PlanledgerError(
            "invalid_record",
            f"Slice {slice_record.record_id} has no plan reference.",
        )
    return load_record(workspace, "plan", str(plan_ref))


def _require_parent_available(parent: Record, action: str) -> None:
    status_value = parent.front_matter.get("status")
    status = str(status_value) if status_value is not None else None
    if not blocks_execution(parent.kind, status):
        return
    error_kind = "terminal_parent" if is_terminal(parent.kind, status) else "inactive_parent"
    raise PlanledgerError(
        error_kind,
        f"Cannot {action} because parent {parent.kind} {parent.record_id} is {status}.",
        remediation=[
            f"Inspect: planledger {parent.kind} show {parent.record_id}",
            "Use planledger view to inspect current goals and initiatives.",
        ],
    )


def _cascade_initiative_cancellations(
    workspace: Any,
    goal_record: Record,
    *,
    command: str,
    reason: str,
    ) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for initiative in list_records(workspace, "initiative"):
        if initiative.front_matter.get("goal") != goal_record.record_id:
            continue
        initiative_status = initiative.front_matter.get("status")
        status = str(initiative_status) if initiative_status is not None else None
        if is_terminal("initiative", status):
            continue
        child_reason = (
            f"Parent goal {goal_record.record_id} changed direction: {reason}"
        )
        events.append(
            transition_record(
                workspace,
                initiative,
                new_status="cancelled",
                command=command,
                reason=child_reason,
            )
        )
        _clear_active_initiative_if_needed(workspace, initiative.record_id)
    return events


def _clear_active_initiative_if_needed(workspace: Any, initiative_id: str) -> None:
    if active_initiative(workspace) == initiative_id:
        set_active_initiative(workspace, None)


def _require_plan_lineage_available(
    workspace: Any,
    plan_record: Record,
    action: str,
    *,
    include_plan: bool = False,
) -> None:
    initiative = _initiative_for_plan(workspace, plan_record)
    _require_parent_available(initiative, action)
    goal = _goal_for_initiative(workspace, initiative)
    if goal is not None:
        _require_parent_available(goal, action)
    if include_plan:
        _require_parent_available(plan_record, action)


def _resolve_scope_from_refs(
    workspace: Any,
    *,
    goal_ref: str | None,
    initiative_ref: str | None,
    allow_project: bool = True,
) -> tuple[str, str | None]:
    if goal_ref is not None and initiative_ref is not None:
        raise PlanledgerError(
            "invalid_options",
            "Use only one of --goal or --initiative.",
        )
    if goal_ref is not None:
        _ = load_record(workspace, "goal", goal_ref)
        return "goal", goal_ref
    if initiative_ref is not None:
        _ = load_record(workspace, "initiative", initiative_ref)
        return "initiative", initiative_ref
    if allow_project:
        return "project", None
    raise PlanledgerError(
        "invalid_options",
        "A scope is required.",
    )


def _resolve_scope_selector(scope_ref: str) -> tuple[str, str]:
    if scope_ref.startswith("goal-"):
        return "goal", scope_ref
    if scope_ref.startswith("init-"):
        return "initiative", scope_ref
    if scope_ref.startswith("plan-"):
        return "plan", scope_ref
    raise PlanledgerError(
        "invalid_options",
        f"Unsupported scope selector {scope_ref!r}.",
    )


@app.command("init")
def project_init(
    ctx: typer.Context,
    project_name: str = typer.Option("Planledger", "--project-name"),
    planledger_dir: str = typer.Option(".planledger", "--planledger-dir"),
    hidden_config: bool = typer.Option(False, "--hidden-config"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        app_ctx = _context(ctx)
        root = workspace_root_from_context(app_ctx, init_mode=True)
        config_filename = ".planledger.toml" if hidden_config else "planledger.toml"
        workspace = initialize_project(
            root,
            project_name,
            planledger_dir=planledger_dir,
            config_filename=config_filename,
        )
        result = {
            "kind": "planledger_project_init",
            "project_name": project_name,
            "project_root": str(workspace.root),
            "config": str(workspace.config_path),
            "ledger": workspace.ledger_ref,
        }
        message = (
            f"Initialized planledger at {workspace.root}\n"
            f"Config: {workspace.config_path}\n"
            f"Ledger: {workspace.ledger_ref}"
        )
        return result, message, []

    _run_command(ctx, "project.init", execute)


@app.command("status")
def project_status(
    ctx: typer.Context, full: bool = typer.Option(False, "--full")
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        counts = record_counts(workspace)
        active = active_initiative(workspace)
        result: dict[str, Any] = {
            "kind": "planledger_project_status",
            "project": workspace.config.get("project", {}).get("name", "Planledger"),
            "root": str(workspace.root),
            "ledger_ref": workspace.ledger_ref,
            "active_initiative": active,
            "counts": counts,
        }
        if full:
            result["goals"] = [
                goal.record_id for goal in list_records(workspace, "goal")
            ]
            result["initiatives"] = [
                initiative.record_id
                for initiative in list_records(workspace, "initiative")
            ]
        message = (
            f"Project: {result['project']}\n"
            f"Root: {workspace.root}\n"
            f"Ledger: {workspace.ledger_ref}\n"
            f"Active initiative: {active or 'none'}\n"
            f"Counts: {counts}"
        )
        return result, message, []

    _run_command(ctx, "project.status", execute)


@app.command("tree")
def project_tree(ctx: typer.Context) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        goals = list_records(workspace, "goal")
        initiatives = list_records(workspace, "initiative")
        plans = list_records(workspace, "plan")
        milestones = list_records(workspace, "milestone")
        slices = list_records(workspace, "slice")

        lines = [
            f"project: {workspace.config.get('project', {}).get('name', 'Planledger')}"
        ]
        lines.append(f"active initiative: {active_initiative(workspace) or 'none'}")
        lines.append(f"goals ({len(goals)})")
        for goal in goals:
            lines.append(f"  - {goal.record_id}: {goal.front_matter.get('title', '')}")
        lines.append(f"initiatives ({len(initiatives)})")
        for initiative in initiatives:
            lines.append(
                f"  - {initiative.record_id}: {initiative.front_matter.get('title', '')}"
            )
        lines.append(
            f"plans ({len(plans)}), milestones ({len(milestones)}), slices ({len(slices)})"
        )

        result = {
            "kind": "planledger_tree",
            "lines": lines,
        }
        return result, "\n".join(lines), []

    _run_command(ctx, "project.tree", execute)


@app.command("doctor")
def project_doctor(ctx: typer.Context) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        result = doctor(workspace)
        issues = list(result.get("issues", []))
        message = (
            "Doctor: healthy"
            if not issues
            else "Doctor found issues:\n- " + "\n- ".join(issues)
        )
        return result, message, []

    _run_command(ctx, "project.doctor", execute)


@app.command("reindex")
def project_reindex(ctx: typer.Context) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        result = reindex(workspace)
        message = f"Reindexed project. Active initiative: {result['active_initiative'] or 'none'}"
        return (
            {
                "kind": "planledger_reindex",
                **result,
            },
            message,
            [],
        )

    _run_command(ctx, "project.reindex", execute)


@app.command("view")
def project_view(ctx: typer.Context) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        project_name = workspace.config.get("project", {}).get("name", "Planledger")
        counts = record_counts(workspace)
        active_init_id = active_initiative(workspace)
        context_result = export_context(
            workspace,
            max_events=5,
            allow_external=True,
        )
        next_action = context_result["next_action"]
        doctor_result = doctor(workspace)

        result: dict[str, Any] = {
            "kind": "planledger_view",
            "project": {
                "name": project_name,
                "root": str(workspace.root),
                "ledger_ref": workspace.ledger_ref,
            },
            "counts": counts,
            "active_initiative": active_init_id,
            "doctor_issues": doctor_result.get("issues", []),
            "next_action": next_action,
            "goals": context_result["goals"],
            "questions": context_result["questions"],
            "assumptions": context_result["assumptions"],
            "constraints": context_result["constraints"],
            "handoff": context_result["handoff"],
        }

        lines: list[str] = []
        lines.append(f"Project: {project_name}")
        lines.append(f"Root: {workspace.root}")
        lines.append(f"Ledger: {workspace.ledger_ref}")
        lines.append(f"Counts: {counts}")

        goal_summary: dict[str, Any] | None = None
        initiative_summary: dict[str, Any] | None = None
        if active_init_id is not None:
            try:
                init_record = load_record(workspace, "initiative", active_init_id)
                init_title = init_record.front_matter.get("title", "")
                init_status = init_record.front_matter.get("status", "")
                initiative_summary = {
                    "id": active_init_id,
                    "title": init_title,
                    "status": init_status,
                }
                lines.append("")
                lines.append(
                    f"Active initiative: {active_init_id} — {init_title} [{init_status}]"
                )
                goal_ref = init_record.front_matter.get("goal")
                if goal_ref is not None:
                    try:
                        goal_record = load_record(workspace, "goal", str(goal_ref))
                        goal_title = goal_record.front_matter.get("title", "")
                        goal_status = goal_record.front_matter.get("status", "")
                        goal_summary = {
                            "id": str(goal_ref),
                            "title": goal_title,
                            "status": goal_status,
                        }
                        lines.append(f"Goal: {goal_ref} — {goal_title} [{goal_status}]")
                    except PlanledgerError:
                        goal_summary = {"id": str(goal_ref), "error": "not_found"}
                        lines.append(f"Goal: {goal_ref} (not found)")
            except PlanledgerError:
                initiative_summary = {"id": active_init_id, "error": "not_found"}
                lines.append("")
                lines.append(f"Active initiative: {active_init_id} (not found)")
        else:
            lines.append("")
            lines.append("Active initiative: none")

        result["goal"] = goal_summary
        result["initiative"] = initiative_summary

        plan_summary: dict[str, Any] | None = None
        if active_init_id is not None:
            latest_plan = latest_plan_for_initiative(workspace, active_init_id)
            if latest_plan is not None:
                plan_id = latest_plan.record_id
                plan_version = latest_plan.front_matter.get("version")
                plan_status = latest_plan.front_matter.get("status")
                plan_summary = {
                    "id": plan_id,
                    "version": plan_version,
                    "status": plan_status,
                }
                lines.append("")
                lines.append(f"Plan: {plan_id} v{plan_version} [{plan_status}]")

                # Milestones for this plan
                milestones = sorted(
                    [
                        ms
                        for ms in list_records(workspace, "milestone")
                        if ms.front_matter.get("plan") == plan_id
                    ],
                    key=lambda m: int(m.front_matter.get("order", 0)),
                )
                ms_statuses: dict[str, int] = {}
                ms_items = []
                for ms in milestones:
                    st = ms.front_matter.get("status", "unknown")
                    ms_statuses[st] = ms_statuses.get(st, 0) + 1
                    ms_items.append(
                        {
                            "id": ms.record_id,
                            "title": ms.front_matter.get("title", ""),
                            "status": st,
                            "order": ms.front_matter.get("order"),
                        }
                    )
                plan_summary["milestones"] = ms_items
                lines.append(f"Milestones ({len(milestones)}): {ms_statuses or 'none'}")
                for ms in milestones:
                    ms_title = ms.front_matter.get("title", "")
                    ms_status = ms.front_matter.get("status", "")
                    lines.append(f"  {ms.record_id} {ms_title} [{ms_status}]")

                # Slices for this plan
                slices = [
                    s
                    for s in list_records(workspace, "slice")
                    if s.front_matter.get("plan") == plan_id
                ]
                slice_statuses: dict[str, int] = {}
                slice_items = []
                for s in slices:
                    st = s.front_matter.get("status", "unknown")
                    slice_statuses[st] = slice_statuses.get(st, 0) + 1
                    slice_items.append(
                        {
                            "id": s.record_id,
                            "title": s.front_matter.get("title", ""),
                            "status": st,
                            "milestone": s.front_matter.get("milestone"),
                        }
                    )
                plan_summary["slices"] = slice_items
                lines.append(f"Slices ({len(slices)}): {slice_statuses or 'none'}")
                for s in slices:
                    s_title = s.front_matter.get("title", "")
                    s_status = s.front_matter.get("status", "")
                    lines.append(f"  {s.record_id} {s_title} [{s_status}]")
            else:
                lines.append("")
                lines.append("Plan: none")
        else:
            lines.append("")
            lines.append("Plan: none")

        result["plan"] = plan_summary

        lines.append("")
        lines.append("Goals:")
        for label, key in (
            ("Active", "active"),
            ("Exploring", "exploring"),
            ("Parked", "parked"),
            ("Recently closed", "closed_recent"),
        ):
            items = result["goals"][key]
            lines.append(f"  {label} ({len(items)})")
            for item in items:
                front = item["front_matter"]
                title = front.get("title", "")
                status = front.get("status", "")
                close_reason = front.get("close_reason")
                line = f"    {item['id']} {title} [{status}]"
                if close_reason:
                    line += f" — {close_reason}"
                lines.append(line)

        open_questions = result["questions"]["open"]
        lines.append("")
        lines.append(f"Open questions ({len(open_questions)}):")
        for item in open_questions:
            front = item["front_matter"]
            lines.append(
                f"  {item['id']} {front.get('title', '')} [{front.get('scope_id') or front.get('scope_kind')}]"
            )

        unverified_assumptions = result["assumptions"]["unverified"]
        lines.append("")
        lines.append(f"Unverified assumptions ({len(unverified_assumptions)}):")
        for item in unverified_assumptions:
            front = item["front_matter"]
            lines.append(
                f"  {item['id']} {front.get('title', '')} [{front.get('confidence', '')}]"
            )

        active_constraints = result["constraints"]["active"]
        if active_constraints:
            lines.append("")
            lines.append(f"Active constraints ({len(active_constraints)}):")
            for item in active_constraints:
                front = item["front_matter"]
                lines.append(
                    f"  {item['id']} {front.get('title', '')} [{front.get('scope_kind', '')}]"
                )

        lines.append("")
        lines.append("Current execution:")
        lines.append(
            f"  Ready slices: {len(result['handoff']['ready_for_taskledger'])}"
        )
        lines.append(
            f"  In execution: {len(context_result['current']['executing_slices'])}"
        )
        if result["handoff"]["blocked_from_taskledger"]:
            lines.append(
                f"  Blocked from taskledger: {len(result['handoff']['blocked_from_taskledger'])}"
            )

        open_decisions = context_result["blocked"]["open_decisions"]
        decision_items = [
            {"id": item["id"], "title": item["front_matter"].get("title")}
            for item in open_decisions
        ]
        if open_decisions:
            lines.append("")
            lines.append(f"Open decisions ({len(open_decisions)}):")
            for item in open_decisions:
                lines.append(f"  {item['id']} {item['front_matter'].get('title', '')}")
        result["open_decisions"] = decision_items

        open_risks = context_result["blocked"]["open_risks"]
        risk_items = [
            {
                "id": item["id"],
                "title": item["front_matter"].get("title"),
                "impact": item["front_matter"].get("impact"),
            }
            for item in open_risks
        ]
        if open_risks:
            lines.append("")
            lines.append(f"Open risks ({len(open_risks)}):")
            for item in open_risks:
                lines.append(
                    f"  {item['id']} {item['front_matter'].get('title', '')} (impact: {item['front_matter'].get('impact', '')})"
                )
        result["open_risks"] = risk_items

        action = next_action.get("action", "")
        next_cmd = next_action.get("next_command", "")
        lines.append("")
        lines.append(f"Next action: {action}")
        if next_cmd:
            lines.append(f"  Command: {next_cmd}")
        blocking = next_action.get("blocking", [])
        if blocking:
            for b in blocking:
                reason = b.get("reason", "")
                if reason:
                    lines.append(f"  Blocking: {reason}")

        issues = doctor_result.get("issues", [])
        if issues:
            lines.append("")
            lines.append(f"Doctor issues ({len(issues)}):")
            for issue in issues:
                lines.append(f"  - {issue}")

        return result, "\n".join(lines), []

    _run_command(ctx, "project.view", execute)


@context_app.command("export")
def context_export(
    ctx: typer.Context,
    include_taskledger: bool = typer.Option(
        False, "--include-taskledger", "--include", help="Include taskledger status"
    ),
    include_bodies: bool = typer.Option(
        False, "--include-bodies", help="Include record bodies"
    ),
    max_body_chars: int = typer.Option(
        4000, "--max-body-chars", help="Max body chars per record"
    ),
    max_events: int = typer.Option(
        0, "--max-events", help="Include last N events (0 = none)"
    ),
    allow_external_next_action: bool = typer.Option(
        False,
        "--allow-external-next-action",
        help="Allow context export to call external integrations for next action.",
    ),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        result = export_context(
            workspace,
            include_taskledger=include_taskledger,
            include_bodies=include_bodies,
            max_body_chars=max_body_chars,
            max_events=max_events,
            allow_external=allow_external_next_action,
        )
        active_init = result.get("active", {}).get("initiative")
        counts = result.get("counts", {})
        message = (
            f"Context export: schema={result['schema']} "
            f"active_initiative={active_init or 'none'} "
            f"counts={counts}"
        )
        return result, message, []

    _run_command(ctx, "context.export", execute)


@goal_app.command("create")
def goal_create(
    ctx: typer.Context,
    title: str,
    status: str = typer.Option("active", "--status"),
    priority: str = typer.Option("high", "--priority"),
    horizon: str = typer.Option("quarter", "--horizon"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        resolved_status = _validate_choice("status", status, {"exploring", "active"})
        resolved_priority = _validate_choice("priority", priority, PRIORITY_LEVELS)
        resolved_horizon = _validate_choice("horizon", horizon, GOAL_HORIZONS)
        goal_id = allocate_id(workspace, "goal")
        timestamp = now_iso()
        front = {
            "id": goal_id,
            "type": "goal",
            "title": title,
            "status": resolved_status,
            "horizon": resolved_horizon,
            "priority": resolved_priority,
            "confidence": "medium",
            "success_metrics": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        create_record(workspace, "goal", front, "")
        event = append_event(
            workspace,
            command=(
                f"planledger goal create {title} --status {resolved_status} "
                f"--priority {resolved_priority} --horizon {resolved_horizon}"
            ),
            object_type="goal",
            object_id=goal_id,
            event_type="created",
            after={
                "title": title,
                "status": resolved_status,
                "priority": resolved_priority,
                "horizon": resolved_horizon,
            },
        )
        return (
            {
                "kind": "planledger_goal",
                "id": goal_id,
                "title": title,
                "status": resolved_status,
            },
            f"Created goal {goal_id}: {title}",
            [event],
        )

    _run_command(ctx, "goal.create", execute)


@goal_app.command("list")
def goal_list(
    ctx: typer.Context,
    status: str | None = typer.Option(None, "--status"),
    active: bool = typer.Option(False, "--active"),
    closed: bool = typer.Option(False, "--closed"),
    all_records: bool = typer.Option(False, "--all"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        resolved_status = (
            _validate_choice("status", status, ACTIVE_GOAL_STATUSES | TERMINAL_GOAL_STATUSES | {"parked"})
            if status is not None
            else None
        )
        goals = _filter_records(
            _sort_records(list_records(workspace, "goal")),
            status=resolved_status,
            active=active,
            closed=closed,
            all_records=all_records,
            active_statuses=ACTIVE_GOAL_STATUSES,
            terminal_statuses=TERMINAL_GOAL_STATUSES,
        )
        payload = [
            {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "status": item.front_matter.get("status"),
                "close_reason": item.front_matter.get("close_reason"),
            }
            for item in goals
        ]
        message = "\n".join([_format_record_line(item) for item in goals])
        return (
            {"kind": "planledger_goal_list", "goals": payload},
            message or "No goals.",
            [],
        )

    _run_command(ctx, "goal.list", execute)


@goal_app.command("show")
def goal_show(ctx: typer.Context, goal_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        goal = load_record(workspace, "goal", goal_ref)
        return (
            {
                "kind": "planledger_goal",
                "id": goal.record_id,
                "front_matter": goal.front_matter,
                "body": goal.body,
            },
            _record_human(goal),
            [],
        )

    _run_command(ctx, "goal.show", execute)


@goal_app.command("activate")
def goal_activate(
    ctx: typer.Context,
    goal_ref: str,
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        goal = load_record(workspace, "goal", goal_ref)
        require_not_terminal(goal, "activate")
        event = transition_record(
            workspace,
            goal,
            new_status="active",
            command=f"planledger goal activate {goal_ref} --reason {reason}",
            reason=reason,
        )
        return (
            {"kind": "planledger_goal_status", "id": goal_ref, "status": "active"},
            f"Activated goal {goal_ref}",
            [event],
        )

    _run_command(ctx, "goal.activate", execute)


@goal_app.command("complete")
def goal_complete(
    ctx: typer.Context,
    goal_ref: str,
    reason: str = typer.Option(..., "--reason"),
    evidence: str = typer.Option("", "--evidence"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        goal = load_record(workspace, "goal", goal_ref)
        require_not_terminal(goal, "complete")
        extra: dict[str, Any] = {}
        if evidence:
            extra["evidence"] = [evidence]
        event = transition_record(
            workspace,
            goal,
            new_status="fulfilled",
            command=f"planledger goal complete {goal_ref} --reason {reason}",
            reason=reason,
            extra=extra,
        )
        return (
            {"kind": "planledger_goal_status", "id": goal_ref, "status": "fulfilled"},
            f"Completed goal {goal_ref}",
            [event],
        )

    _run_command(ctx, "goal.complete", execute)


@goal_app.command("cancel")
def goal_cancel(
    ctx: typer.Context,
    goal_ref: str,
    reason: str = typer.Option(..., "--reason"),
    because_goal: str | None = typer.Option(None, "--because-goal"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        goal = load_record(workspace, "goal", goal_ref)
        require_not_terminal(goal, "cancel")
        events = [
            transition_record(
                workspace,
                goal,
                new_status="cancelled",
                command=f"planledger goal cancel {goal_ref} --reason {reason}",
                reason=reason,
            )
        ]
        if because_goal is not None:
            _ = load_record(workspace, "goal", because_goal)
            events.append(
                link_records(
                    workspace,
                    goal,
                    "invalidated_by",
                    because_goal,
                    command=(
                        f"planledger goal cancel {goal_ref} --reason {reason} "
                        f"--because-goal {because_goal}"
                    ),
                )
            )
            events.append(
                link_records(
                    workspace,
                    goal,
                    "related_goals",
                    because_goal,
                    command=(
                        f"planledger goal cancel {goal_ref} --reason {reason} "
                        f"--because-goal {because_goal}"
                    ),
                )
            )
        events.extend(
            _cascade_initiative_cancellations(
                workspace,
                goal,
                command=f"planledger goal cancel {goal_ref} --reason {reason}",
                reason=reason,
            )
        )
        return (
            {"kind": "planledger_goal_status", "id": goal_ref, "status": "cancelled"},
            f"Cancelled goal {goal_ref}",
            events,
        )

    _run_command(ctx, "goal.cancel", execute)


@goal_app.command("park")
def goal_park(
    ctx: typer.Context,
    goal_ref: str,
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        goal = load_record(workspace, "goal", goal_ref)
        require_not_terminal(goal, "park")
        event = transition_record(
            workspace,
            goal,
            new_status="parked",
            command=f"planledger goal park {goal_ref} --reason {reason}",
            reason=reason,
            extra={"park_reason": reason},
        )
        return (
            {"kind": "planledger_goal_status", "id": goal_ref, "status": "parked"},
            f"Parked goal {goal_ref}",
            [event],
        )

    _run_command(ctx, "goal.park", execute)


@goal_app.command("supersede")
def goal_supersede(
    ctx: typer.Context,
    goal_ref: str,
    new_title: str = typer.Option(..., "--new-title"),
    reason: str = typer.Option(..., "--reason"),
    status: str = typer.Option("active", "--status"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        goal = load_record(workspace, "goal", goal_ref)
        require_not_terminal(goal, "supersede")
        new_status = _validate_choice("status", status, {"exploring", "active"})
        new_goal_id = allocate_id(workspace, "goal")
        timestamp = now_iso()
        new_front = {
            "id": new_goal_id,
            "type": "goal",
            "title": new_title,
            "status": new_status,
            "horizon": goal.front_matter.get("horizon", "quarter"),
            "priority": goal.front_matter.get("priority", "high"),
            "confidence": goal.front_matter.get("confidence", "medium"),
            "success_metrics": list(goal.front_matter.get("success_metrics") or []),
            "supersedes": [goal_ref],
            "related_goals": [goal_ref],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        create_record(workspace, "goal", new_front, goal.body)
        events = [
            append_event(
                workspace,
                command=(
                    f"planledger goal supersede {goal_ref} --new-title {new_title} "
                    f"--reason {reason} --status {new_status}"
                ),
                object_type="goal",
                object_id=new_goal_id,
                event_type="created",
                after={"title": new_title, "status": new_status},
            ),
            transition_record(
                workspace,
                goal,
                new_status="superseded",
                command=(
                    f"planledger goal supersede {goal_ref} --new-title {new_title} "
                    f"--reason {reason} --status {new_status}"
                ),
                reason=reason,
                extra={"superseded_by": new_goal_id},
            ),
        ]
        events.extend(
            _cascade_initiative_cancellations(
                workspace,
                goal,
                command=(
                    f"planledger goal supersede {goal_ref} --new-title {new_title} "
                    f"--reason {reason}"
                ),
                reason=reason,
            )
        )
        return (
            {
                "kind": "planledger_goal_supersede",
                "old_goal": goal_ref,
                "new_goal": new_goal_id,
            },
            f"Superseded goal {goal_ref} with {new_goal_id}",
            events,
        )

    _run_command(ctx, "goal.supersede", execute)


@goal_app.command("revise")
def goal_revise(
    ctx: typer.Context,
    goal_ref: str,
    title: str | None = typer.Option(None, "--title"),
    priority: str | None = typer.Option(None, "--priority"),
    horizon: str | None = typer.Option(None, "--horizon"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        goal = load_record(workspace, "goal", goal_ref)
        require_not_terminal(goal, "revise")
        if title is None and priority is None and horizon is None:
            raise PlanledgerError(
                "invalid_options",
                "Provide at least one of --title, --priority, or --horizon.",
            )
        before = {
            "title": goal.front_matter.get("title"),
            "priority": goal.front_matter.get("priority"),
            "horizon": goal.front_matter.get("horizon"),
            "status": goal.front_matter.get("status"),
        }
        if title is not None:
            goal.front_matter["title"] = title
        if priority is not None:
            goal.front_matter["priority"] = _validate_choice(
                "priority", priority, PRIORITY_LEVELS
            )
        if horizon is not None:
            goal.front_matter["horizon"] = _validate_choice(
                "horizon", horizon, GOAL_HORIZONS
            )
        update_record_timestamp(goal)
        save_record(goal)
        after = {
            "title": goal.front_matter.get("title"),
            "priority": goal.front_matter.get("priority"),
            "horizon": goal.front_matter.get("horizon"),
            "status": goal.front_matter.get("status"),
            "reason": reason,
        }
        event = append_event(
            workspace,
            command=f"planledger goal revise {goal_ref} --reason {reason}",
            object_type="goal",
            object_id=goal_ref,
            event_type="revised",
            before=before,
            after=after,
        )
        return (
            {"kind": "planledger_goal_revision", "id": goal_ref, "front_matter": goal.front_matter},
            f"Revised goal {goal_ref}",
            [event],
        )

    _run_command(ctx, "goal.revise", execute)


@initiative_app.command("create")
def initiative_create(
    ctx: typer.Context,
    title: str,
    goal: str = typer.Option(..., "--goal"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        goal_record = load_record(workspace, "goal", goal)
        _require_parent_available(goal_record, f"create initiative under goal {goal}")
        initiative_id = allocate_id(workspace, "initiative")
        timestamp = now_iso()
        front = {
            "id": initiative_id,
            "type": "initiative",
            "goal": goal,
            "title": title,
            "status": "shaping",
            "owner": "human",
            "priority": "high",
            "active": False,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        record = create_record(workspace, "initiative", front, "")
        event = append_event(
            workspace,
            command=f"planledger initiative create {title} --goal {goal}",
            object_type="initiative",
            object_id=initiative_id,
            event_type="created",
            after={"goal": goal, "title": title},
        )
        return (
            {"kind": "planledger_initiative", "id": record.record_id, "title": title},
            f"Created initiative {record.record_id}: {title}",
            [event],
        )

    _run_command(ctx, "initiative.create", execute)


@initiative_app.command("activate")
def initiative_activate(ctx: typer.Context, initiative_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        initiative = load_record(workspace, "initiative", initiative_ref)
        require_not_terminal(initiative, "activate")
        goal = _goal_for_initiative(workspace, initiative)
        if goal is not None:
            _require_parent_available(goal, f"activate initiative {initiative_ref}")
        set_active_initiative(workspace, initiative_ref)
        event = append_event(
            workspace,
            command=f"planledger initiative activate {initiative_ref}",
            object_type="initiative",
            object_id=initiative_ref,
            event_type="activated",
            after={"active": True},
        )
        return (
            {
                "kind": "planledger_initiative_activate",
                "active_initiative": initiative_ref,
            },
            f"Activated initiative {initiative_ref}",
            [event],
        )

    _run_command(ctx, "initiative.activate", execute)


@initiative_app.command("active")
def initiative_active(ctx: typer.Context) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        active = active_initiative(workspace)
        if active is None:
            raise PlanledgerError(
                "not_found",
                "No active initiative.",
                remediation=["Run: planledger initiative activate INIT"],
            )
        record = load_record(workspace, "initiative", active)
        return (
            {
                "kind": "planledger_initiative",
                "id": record.record_id,
                "front_matter": record.front_matter,
                "body": record.body,
            },
            _record_human(record),
            [],
        )

    _run_command(ctx, "initiative.active", execute)


@initiative_app.command("list")
def initiative_list(
    ctx: typer.Context,
    status: str | None = typer.Option(None, "--status"),
    active: bool = typer.Option(False, "--active"),
    closed: bool = typer.Option(False, "--closed"),
    all_records: bool = typer.Option(False, "--all"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        active_id = active_initiative(workspace)
        if sum((1 if status is not None else 0, 1 if active else 0, 1 if closed else 0, 1 if all_records else 0)) > 1:
            raise PlanledgerError(
                "invalid_options",
                "Use at most one of --status, --active, --closed, or --all.",
            )
        initiatives = _sort_records(list_records(workspace, "initiative"))
        if status is not None:
            resolved_status = _validate_choice(
                "status",
                status,
                {"shaping", "planned", "executing", "fulfilled", "cancelled", "superseded", "parked"},
            )
            initiatives = [
                item
                for item in initiatives
                if item.front_matter.get("status") == resolved_status
            ]
        elif active:
            initiatives = [
                item for item in initiatives if item.record_id == active_id
            ]
        elif closed:
            initiatives = [
                item
                for item in initiatives
                if item.front_matter.get("status") in TERMINAL_INITIATIVE_STATUSES
            ]
        payload = []
        lines = []
        for item in initiatives:
            row = {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "status": item.front_matter.get("status"),
                "active": item.record_id == active_id,
            }
            payload.append(row)
            lines.append(_format_record_line(item, active_marker=row["active"]))
        return (
            {"kind": "planledger_initiative_list", "initiatives": payload},
            "\n".join(lines) or "No initiatives.",
            [],
        )

    _run_command(ctx, "initiative.list", execute)


@initiative_app.command("show")
def initiative_show(ctx: typer.Context, initiative_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        initiative = load_record(workspace, "initiative", initiative_ref)
        return (
            {
                "kind": "planledger_initiative",
                "id": initiative.record_id,
                "front_matter": initiative.front_matter,
                "body": initiative.body,
            },
            _record_human(initiative),
            [],
        )

    _run_command(ctx, "initiative.show", execute)


@initiative_app.command("complete")
def initiative_complete(
    ctx: typer.Context,
    initiative_ref: str,
    reason: str = typer.Option(..., "--reason"),
    evidence: str = typer.Option("", "--evidence"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        initiative = load_record(workspace, "initiative", initiative_ref)
        require_not_terminal(initiative, "complete")
        extra: dict[str, Any] = {}
        if evidence:
            extra["evidence"] = [evidence]
        event = transition_record(
            workspace,
            initiative,
            new_status="fulfilled",
            command=f"planledger initiative complete {initiative_ref} --reason {reason}",
            reason=reason,
            extra=extra,
        )
        _clear_active_initiative_if_needed(workspace, initiative_ref)
        return (
            {
                "kind": "planledger_initiative_status",
                "id": initiative_ref,
                "status": "fulfilled",
            },
            f"Completed initiative {initiative_ref}",
            [event],
        )

    _run_command(ctx, "initiative.complete", execute)


@initiative_app.command("cancel")
def initiative_cancel(
    ctx: typer.Context,
    initiative_ref: str,
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        initiative = load_record(workspace, "initiative", initiative_ref)
        require_not_terminal(initiative, "cancel")
        event = transition_record(
            workspace,
            initiative,
            new_status="cancelled",
            command=f"planledger initiative cancel {initiative_ref} --reason {reason}",
            reason=reason,
        )
        _clear_active_initiative_if_needed(workspace, initiative_ref)
        return (
            {
                "kind": "planledger_initiative_status",
                "id": initiative_ref,
                "status": "cancelled",
            },
            f"Cancelled initiative {initiative_ref}",
            [event],
        )

    _run_command(ctx, "initiative.cancel", execute)


@initiative_app.command("park")
def initiative_park(
    ctx: typer.Context,
    initiative_ref: str,
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        initiative = load_record(workspace, "initiative", initiative_ref)
        require_not_terminal(initiative, "park")
        event = transition_record(
            workspace,
            initiative,
            new_status="parked",
            command=f"planledger initiative park {initiative_ref} --reason {reason}",
            reason=reason,
            extra={"park_reason": reason},
        )
        return (
            {"kind": "planledger_initiative_status", "id": initiative_ref, "status": "parked"},
            f"Parked initiative {initiative_ref}",
            [event],
        )

    _run_command(ctx, "initiative.park", execute)


@initiative_app.command("revise")
def initiative_revise(
    ctx: typer.Context,
    initiative_ref: str,
    title: str | None = typer.Option(None, "--title"),
    priority: str | None = typer.Option(None, "--priority"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        initiative = load_record(workspace, "initiative", initiative_ref)
        require_not_terminal(initiative, "revise")
        if title is None and priority is None:
            raise PlanledgerError(
                "invalid_options",
                "Provide at least one of --title or --priority.",
            )
        before = {
            "title": initiative.front_matter.get("title"),
            "priority": initiative.front_matter.get("priority"),
            "status": initiative.front_matter.get("status"),
        }
        if title is not None:
            initiative.front_matter["title"] = title
        if priority is not None:
            initiative.front_matter["priority"] = _validate_choice(
                "priority", priority, PRIORITY_LEVELS
            )
        update_record_timestamp(initiative)
        save_record(initiative)
        event = append_event(
            workspace,
            command=f"planledger initiative revise {initiative_ref} --reason {reason}",
            object_type="initiative",
            object_id=initiative_ref,
            event_type="revised",
            before=before,
            after={
                "title": initiative.front_matter.get("title"),
                "priority": initiative.front_matter.get("priority"),
                "status": initiative.front_matter.get("status"),
                "reason": reason,
            },
        )
        return (
            {
                "kind": "planledger_initiative_revision",
                "id": initiative_ref,
                "front_matter": initiative.front_matter,
            },
            f"Revised initiative {initiative_ref}",
            [event],
        )

    _run_command(ctx, "initiative.revise", execute)


@plan_app.command("draft")
def plan_draft(
    ctx: typer.Context,
    initiative: str | None = typer.Option(None, "--initiative"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        resolved_initiative = initiative
        if resolved_initiative is None:
            resolved_initiative = active_initiative(workspace)
            if resolved_initiative is None:
                raise PlanledgerError(
                    "not_found",
                    "No active initiative.",
                    remediation=[
                        "Use --initiative to specify one, or activate an initiative first."
                    ],
                )
        initiative_record = load_record(workspace, "initiative", resolved_initiative)
        require_not_terminal(initiative_record, "draft plan for")
        goal_record = _goal_for_initiative(workspace, initiative_record)
        if goal_record is not None:
            _require_parent_available(
                goal_record, f"draft plan for initiative {resolved_initiative}"
            )
        plan_id = allocate_id(workspace, "plan")
        existing = [
            plan
            for plan in list_records(workspace, "plan")
            if plan.front_matter.get("initiative") == resolved_initiative
        ]
        version = (
            max(
                (int(plan.front_matter.get("version", 0)) for plan in existing),
                default=0,
        )
            + 1
        )
        timestamp = now_iso()
        goal_ref = initiative_record.front_matter.get("goal")
        front = {
            "id": plan_id,
            "type": "plan",
            "goal": goal_ref,
            "initiative": resolved_initiative,
            "version": version,
            "status": "draft",
            "supersedes": None,
            "accepted_at": None,
            "accepted_by": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        plan_body = render_plan_template(
            initiative=initiative_record,
            goal=goal_record,
            version=version,
        )
        record = create_record(workspace, "plan", front, plan_body)
        event = append_event(
            workspace,
            command=f"planledger plan draft --initiative {resolved_initiative}",
            object_type="plan",
            object_id=plan_id,
            event_type="created",
            after={"initiative": resolved_initiative, "version": version},
        )
        return (
            {"kind": "planledger_plan", "id": record.record_id, "version": version},
            f"Drafted plan {record.record_id} (v{version}) for {resolved_initiative}",
            [event],
        )

    _run_command(ctx, "plan.draft", execute)


@plan_app.command("show")
def plan_show(ctx: typer.Context, plan_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        plan = load_record(workspace, "plan", plan_ref)
        return (
            {
                "kind": "planledger_plan",
                "id": plan.record_id,
                "front_matter": plan.front_matter,
                "body": plan.body,
            },
            _record_human(plan),
            [],
        )

    _run_command(ctx, "plan.show", execute)


@plan_app.command("list")
def plan_list(
    ctx: typer.Context,
    initiative: str | None = typer.Option(None, "--initiative"),
    status: str | None = typer.Option(None, "--status"),
    active: bool = typer.Option(False, "--active"),
    all_records: bool = typer.Option(False, "--all"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        plans = _sort_records(list_records(workspace, "plan"))
        if initiative is not None:
            plans = [
                plan
                for plan in plans
                if plan.front_matter.get("initiative") == initiative
            ]
        if sum((1 if status is not None else 0, 1 if active else 0, 1 if all_records else 0)) > 1:
            raise PlanledgerError(
                "invalid_options",
                "Use at most one of --status, --active, or --all.",
            )
        if status is not None:
            resolved_status = _validate_choice(
                "status", status, {"draft", "accepted", "superseded", "retired"}
            )
            plans = [
                plan for plan in plans if plan.front_matter.get("status") == resolved_status
            ]
        elif active:
            plans = [
                plan
                for plan in plans
                if plan.front_matter.get("status") in ACTIVE_PLAN_STATUSES
            ]
        payload = [
            {
                "id": item.record_id,
                "initiative": item.front_matter.get("initiative"),
                "version": item.front_matter.get("version"),
                "status": item.front_matter.get("status"),
            }
            for item in plans
        ]
        lines = [
            _format_record_line(item)
            for item in plans
        ]
        return (
            {"kind": "planledger_plan_list", "plans": payload},
            "\n".join(lines) or "No plans.",
            [],
        )

    _run_command(ctx, "plan.list", execute)


@plan_app.command("lint")
def plan_lint_cmd(ctx: typer.Context, plan_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        plan = load_record(workspace, "plan", plan_ref)
        lint = lint_plan(workspace, plan)
        message = (
            f"Plan {plan_ref} lint: pass"
            if lint.ok
            else f"Plan {plan_ref} lint: fail\n- " + "\n- ".join(lint.issues)
        )
        result = {
            "kind": "planledger_plan_lint",
            "plan": plan_ref,
            "ok": lint.ok,
            "issues": lint.issues,
        }
        return result, message, []

    _run_command(ctx, "plan.lint", execute)


@plan_app.command("accept")
def plan_accept(
    ctx: typer.Context,
    plan_ref: str,
    note: str = typer.Option(..., "--note"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        plan = load_record(workspace, "plan", plan_ref)
        _require_plan_lineage_available(
            workspace,
            plan,
            f"accept plan {plan_ref}",
        )
        lint = lint_plan(workspace, plan)
        if lint.issues:
            raise PlanledgerError(
                "lint_failed",
                f"Plan {plan_ref} is not lint-clean.",
                remediation=[f"Run: planledger plan lint {plan_ref}"],
            )

        now = now_iso()
        plan.front_matter["status"] = "accepted"
        plan.front_matter["accepted_at"] = now
        plan.front_matter["accepted_by"] = "human"
        update_record_timestamp(plan)
        if "## Acceptance notes" not in plan.body:
            plan.body = plan.body.rstrip() + "\n\n## Acceptance notes\n\n"
        plan.body = plan.body.rstrip() + f"\n- {note}\n"
        save_record(plan)

        superseded: list[str] = []
        for other in list_records(workspace, "plan"):
            if other.record_id == plan.record_id:
                continue
            if (
                other.front_matter.get("initiative")
                == plan.front_matter.get("initiative")
                and other.front_matter.get("status") == "accepted"
            ):
                other.front_matter["status"] = "superseded"
                update_record_timestamp(other)
                save_record(other)
                superseded.append(other.record_id)

        event = append_event(
            workspace,
            command=f"planledger plan accept {plan_ref} --note {note}",
            object_type="plan",
            object_id=plan_ref,
            event_type="accepted",
            after={"status": "accepted", "accepted_at": now},
        )
        return (
            {
                "kind": "planledger_plan_accept",
                "plan": plan_ref,
                "status": "accepted",
                "superseded": superseded,
            },
            f"Accepted plan {plan_ref}",
            [event],
        )

    _run_command(ctx, "plan.accept", execute)


@plan_app.command("retire")
def plan_retire(
    ctx: typer.Context,
    plan_ref: str,
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        plan = load_record(workspace, "plan", plan_ref)
        require_not_terminal(plan, "retire")
        event = transition_record(
            workspace,
            plan,
            new_status="retired",
            command=f"planledger plan retire {plan_ref} --reason {reason}",
            reason=reason,
        )
        return (
            {"kind": "planledger_plan_status", "id": plan_ref, "status": "retired"},
            f"Retired plan {plan_ref}",
            [event],
        )

    _run_command(ctx, "plan.retire", execute)


@milestone_app.command("add")
def milestone_add(
    ctx: typer.Context,
    title: str,
    plan: str = typer.Option(..., "--plan"),
    order: int | None = typer.Option(None, "--order"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        plan_record = load_record(workspace, "plan", plan)
        milestone_id = allocate_id(workspace, "milestone")
        timestamp = now_iso()
        current = [
            ms
            for ms in list_records(workspace, "milestone")
            if ms.front_matter.get("plan") == plan
        ]
        ordinal = order if order is not None else (len(current) + 1) * 10
        front = {
            "id": milestone_id,
            "type": "milestone",
            "initiative": plan_record.front_matter.get("initiative"),
            "plan": plan,
            "title": title,
            "status": "planned",
            "order": ordinal,
            "target": None,
            "exit_criteria": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        record = create_record(workspace, "milestone", front, "")
        event = append_event(
            workspace,
            command=f"planledger milestone add --plan {plan} {title}",
            object_type="milestone",
            object_id=record.record_id,
            event_type="created",
            after={"plan": plan, "title": title},
        )
        return (
            {"kind": "planledger_milestone", "id": record.record_id, "plan": plan},
            f"Added milestone {record.record_id}: {title}",
            [event],
        )

    _run_command(ctx, "milestone.add", execute)


@milestone_app.command("list")
def milestone_list(
    ctx: typer.Context, plan: str | None = typer.Option(None, "--plan")
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        milestones = list_records(workspace, "milestone")
        if plan is not None:
            milestones = [
                item for item in milestones if item.front_matter.get("plan") == plan
            ]
        milestones = sorted(
            milestones, key=lambda item: int(item.front_matter.get("order", 0))
        )
        payload = [
            {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "plan": item.front_matter.get("plan"),
                "status": item.front_matter.get("status"),
            }
            for item in milestones
        ]
        lines = [f"{item['id']} {item['title']} [{item['status']}]" for item in payload]
        return (
            {"kind": "planledger_milestone_list", "milestones": payload},
            "\n".join(lines) or "No milestones.",
            [],
        )

    _run_command(ctx, "milestone.list", execute)


@milestone_app.command("show")
def milestone_show(ctx: typer.Context, milestone_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        milestone = load_record(workspace, "milestone", milestone_ref)
        return (
            {
                "kind": "planledger_milestone",
                "id": milestone.record_id,
                "front_matter": milestone.front_matter,
                "body": milestone.body,
            },
            _record_human(milestone),
            [],
        )

    _run_command(ctx, "milestone.show", execute)


@slice_app.command("add")
def slice_add(
    ctx: typer.Context,
    title: str,
    milestone: str = typer.Option(..., "--milestone"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        milestone_record = load_record(workspace, "milestone", milestone)
        plan_record = load_record(
            workspace, "plan", str(milestone_record.front_matter.get("plan"))
        )
        _require_plan_lineage_available(
            workspace,
            plan_record,
            f"add slice under milestone {milestone}",
            include_plan=True,
        )
        slice_id = allocate_id(workspace, "slice")
        timestamp = now_iso()
        front = {
            "id": slice_id,
            "type": "slice",
            "initiative": milestone_record.front_matter.get("initiative"),
            "plan": milestone_record.front_matter.get("plan"),
            "milestone": milestone,
            "title": title,
            "status": "shaping",
            "priority": "high",
            "size": "M",
            "risk": "medium",
            "depends_on": [],
            "blocked_by": [],
            "taskledger_bindings": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        record = create_record(workspace, "slice", front, "")
        event = append_event(
            workspace,
            command=f"planledger slice add --milestone {milestone} {title}",
            object_type="slice",
            object_id=record.record_id,
            event_type="created",
            after={"title": title, "milestone": milestone},
        )
        return (
            {"kind": "planledger_slice", "id": record.record_id, "title": title},
            f"Added slice {record.record_id}: {title}",
            [event],
        )

    _run_command(ctx, "slice.add", execute)


@slice_app.command("list")
def slice_list(
    ctx: typer.Context,
    initiative: str | None = typer.Option(None, "--initiative"),
    status: str | None = typer.Option(None, "--status"),
    all_records: bool = typer.Option(False, "--all"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        if status is not None and all_records:
            raise PlanledgerError(
                "invalid_options",
                "Use at most one of --status or --all.",
            )
        slices = _sort_records(list_records(workspace, "slice"))
        if initiative is not None:
            slices = [
                item
                for item in slices
                if item.front_matter.get("initiative") == initiative
            ]
        if status is not None:
            resolved_status = _validate_choice(
                "status",
                status,
                {"idea", "shaping", "ready-for-execution", "in-execution", "executed", "validated", "cancelled", "obsolete"},
            )
            slices = [
                item for item in slices if item.front_matter.get("status") == resolved_status
            ]
        payload = [
            {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "status": item.front_matter.get("status"),
                "milestone": item.front_matter.get("milestone"),
            }
            for item in slices
        ]
        lines = [f"{item['id']} {item['title']} [{item['status']}]" for item in payload]
        return (
            {"kind": "planledger_slice_list", "slices": payload},
            "\n".join(lines) or "No slices.",
            [],
        )

    _run_command(ctx, "slice.list", execute)


@slice_app.command("show")
def slice_show(ctx: typer.Context, slice_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        slice_record = load_record(workspace, "slice", slice_ref)
        return (
            {
                "kind": "planledger_slice",
                "id": slice_record.record_id,
                "front_matter": slice_record.front_matter,
                "body": slice_record.body,
            },
            _record_human(slice_record),
            [],
        )

    _run_command(ctx, "slice.show", execute)


@slice_app.command("ready")
def slice_ready(ctx: typer.Context, slice_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        slice_record = load_record(workspace, "slice", slice_ref)
        plan_record = _plan_for_slice(workspace, slice_record)
        _require_plan_lineage_available(
            workspace,
            plan_record,
            f"mark slice {slice_ref} ready",
            include_plan=True,
        )
        event = transition_record(
            workspace,
            slice_record,
            new_status="ready-for-execution",
            command=f"planledger slice ready {slice_ref}",
            reason="Slice marked ready for taskledger handoff.",
        )
        return (
            {
                "kind": "planledger_slice_status",
                "id": slice_ref,
                "status": "ready-for-execution",
            },
            f"Slice {slice_ref} marked ready-for-execution",
            [event],
        )

    _run_command(ctx, "slice.ready", execute)


@slice_app.command("done")
def slice_done(
    ctx: typer.Context,
    slice_ref: str,
    evidence: str = typer.Option("", "--evidence"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        slice_record = load_record(workspace, "slice", slice_ref)
        extra: dict[str, Any] = {"execution_status": "done"}
        if evidence:
            extra["execution_evidence"] = evidence
        event = transition_record(
            workspace,
            slice_record,
            new_status="executed",
            command=f"planledger slice done {slice_ref}",
            reason="Implementation completed.",
            extra=extra,
        )
        return (
            {"kind": "planledger_slice_status", "id": slice_ref, "status": "executed"},
            f"Slice {slice_ref} marked executed",
            [event],
        )

    _run_command(ctx, "slice.done", execute)


@slice_app.command("cancel")
def slice_cancel(
    ctx: typer.Context,
    slice_ref: str,
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        slice_record = load_record(workspace, "slice", slice_ref)
        event = transition_record(
            workspace,
            slice_record,
            new_status="cancelled",
            command=f"planledger slice cancel {slice_ref} --reason {reason}",
            reason=reason,
        )
        return (
            {"kind": "planledger_slice_status", "id": slice_ref, "status": "cancelled"},
            f"Cancelled slice {slice_ref}",
            [event],
        )

    _run_command(ctx, "slice.cancel", execute)


@slice_app.command("obsolete")
def slice_obsolete(
    ctx: typer.Context,
    slice_ref: str,
    reason: str = typer.Option(..., "--reason"),
    because_goal: str | None = typer.Option(None, "--because-goal"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        slice_record = load_record(workspace, "slice", slice_ref)
        events = [
            transition_record(
                workspace,
                slice_record,
                new_status="obsolete",
                command=f"planledger slice obsolete {slice_ref} --reason {reason}",
                reason=reason,
            )
        ]
        if because_goal is not None:
            _ = load_record(workspace, "goal", because_goal)
            events.append(
                link_records(
                    workspace,
                    slice_record,
                    "invalidated_by",
                    because_goal,
                    command=(
                        f"planledger slice obsolete {slice_ref} --reason {reason} "
                        f"--because-goal {because_goal}"
                    ),
                )
            )
        return (
            {"kind": "planledger_slice_status", "id": slice_ref, "status": "obsolete"},
            f"Marked slice {slice_ref} obsolete",
            events,
        )

    _run_command(ctx, "slice.obsolete", execute)


@slice_app.command("validate")
def slice_validate(
    ctx: typer.Context,
    slice_ref: str,
    evidence: str = typer.Option(..., "--evidence"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        slice_record = load_record(workspace, "slice", slice_ref)
        event = transition_record(
            workspace,
            slice_record,
            new_status="validated",
            command=f"planledger slice validate {slice_ref} --evidence {evidence}",
            reason="Validation completed.",
            extra={"validation_evidence": evidence},
        )
        return (
            {"kind": "planledger_slice_status", "id": slice_ref, "status": "validated"},
            f"Validated slice {slice_ref}",
            [event],
        )

    _run_command(ctx, "slice.validate", execute)


@decision_app.command("create")
def decision_create(
    ctx: typer.Context,
    title: str,
    initiative: str = typer.Option(..., "--initiative"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        _ = load_record(workspace, "initiative", initiative)
        decision_id = allocate_id(workspace, "decision")
        timestamp = now_iso()
        front = {
            "id": decision_id,
            "type": "decision",
            "initiative": initiative,
            "title": title,
            "status": "open",
            "chosen_option": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "accepted_at": None,
        }
        create_record(workspace, "decision", front, DECISION_TEMPLATE)
        event = append_event(
            workspace,
            command=f"planledger decision create {title} --initiative {initiative}",
            object_type="decision",
            object_id=decision_id,
            event_type="created",
            after={"title": title},
        )
        return (
            {"kind": "planledger_decision", "id": decision_id, "title": title},
            f"Created decision {decision_id}: {title}",
            [event],
        )

    _run_command(ctx, "decision.create", execute)


@decision_app.command("list")
def decision_list(
    ctx: typer.Context, open_only: bool = typer.Option(False, "--open")
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        decisions = list_records(workspace, "decision")
        if open_only:
            decisions = [
                item for item in decisions if item.front_matter.get("status") == "open"
            ]
        payload = [
            {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "status": item.front_matter.get("status"),
                "chosen_option": item.front_matter.get("chosen_option"),
            }
            for item in decisions
        ]
        lines = [f"{item['id']} {item['title']} [{item['status']}]" for item in payload]
        return (
            {"kind": "planledger_decision_list", "decisions": payload},
            "\n".join(lines) or "No decisions.",
            [],
        )

    _run_command(ctx, "decision.list", execute)


@decision_app.command("show")
def decision_show(ctx: typer.Context, decision_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        decision = load_record(workspace, "decision", decision_ref)
        options = [
            option
            for option in list_records(workspace, "option")
            if option.front_matter.get("decision") == decision_ref
        ]
        return (
            {
                "kind": "planledger_decision",
                "id": decision.record_id,
                "front_matter": decision.front_matter,
                "body": decision.body,
                "options": [
                    {
                        "id": option.record_id,
                        "title": option.front_matter.get("title"),
                        "status": option.front_matter.get("status"),
                    }
                    for option in options
                ],
            },
            _record_human(decision),
            [],
        )

    _run_command(ctx, "decision.show", execute)


@decision_app.command("accept")
def decision_accept(
    ctx: typer.Context,
    decision_ref: str,
    option: str = typer.Option(..., "--option"),
    rationale: str = typer.Option(..., "--rationale"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        decision = load_record(workspace, "decision", decision_ref)
        chosen_option = load_record(workspace, "option", option)
        if chosen_option.front_matter.get("decision") != decision_ref:
            raise PlanledgerError(
                "invalid_reference",
                f"Option {option} does not belong to {decision_ref}.",
                remediation=[f"Run: planledger option compare {decision_ref}"],
            )
        decision.front_matter["status"] = "accepted"
        decision.front_matter["chosen_option"] = option
        decision.front_matter["accepted_at"] = now_iso()
        update_record_timestamp(decision)
        if "## Rationale" in decision.body:
            decision.body = decision.body.rstrip() + f"\n\n{rationale}\n"
        else:
            decision.body = (
                decision.body.rstrip() + f"\n\n## Rationale\n\n{rationale}\n"
            )
        save_record(decision)
        event = append_event(
            workspace,
            command=(
                f"planledger decision accept {decision_ref} --option {option} "
                f"--rationale {rationale}"
            ),
            object_type="decision",
            object_id=decision_ref,
            event_type="accepted",
            after={"chosen_option": option},
        )
        return (
            {
                "kind": "planledger_decision_accept",
                "decision": decision_ref,
                "chosen_option": option,
            },
            f"Accepted decision {decision_ref} with option {option}",
            [event],
        )

    _run_command(ctx, "decision.accept", execute)


@option_app.command("add")
def option_add(
    ctx: typer.Context,
    title: str,
    decision: str = typer.Option(..., "--decision"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        _ = load_record(workspace, "decision", decision)
        option_id = allocate_id(workspace, "option")
        timestamp = now_iso()
        front = {
            "id": option_id,
            "type": "option",
            "decision": decision,
            "title": title,
            "status": "candidate",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        create_record(workspace, "option", front, OPTION_TEMPLATE)
        event = append_event(
            workspace,
            command=f"planledger option add --decision {decision} {title}",
            object_type="option",
            object_id=option_id,
            event_type="created",
            after={"decision": decision, "title": title},
        )
        return (
            {"kind": "planledger_option", "id": option_id, "decision": decision},
            f"Added option {option_id}: {title}",
            [event],
        )

    _run_command(ctx, "option.add", execute)


@option_app.command("compare")
def option_compare(ctx: typer.Context, decision_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        _ = load_record(workspace, "decision", decision_ref)
        options = [
            option
            for option in list_records(workspace, "option")
            if option.front_matter.get("decision") == decision_ref
        ]
        payload = [
            {
                "id": option.record_id,
                "title": option.front_matter.get("title"),
                "status": option.front_matter.get("status"),
            }
            for option in options
        ]
        lines = [f"{item['id']} {item['title']} [{item['status']}]" for item in payload]
        result = {
            "kind": "planledger_option_compare",
            "decision": decision_ref,
            "options": payload,
        }
        return result, "\n".join(lines) or "No options.", []

    _run_command(ctx, "option.compare", execute)


@risk_app.command("add")
def risk_add(
    ctx: typer.Context,
    title: str,
    initiative: str = typer.Option(..., "--initiative"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        _ = load_record(workspace, "initiative", initiative)
        risk_id = allocate_id(workspace, "risk")
        timestamp = now_iso()
        front = {
            "id": risk_id,
            "type": "risk",
            "initiative": initiative,
            "title": title,
            "status": "open",
            "likelihood": "medium",
            "impact": "medium",
            "mitigation": "",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        create_record(workspace, "risk", front, "")
        event = append_event(
            workspace,
            command=f"planledger risk add --initiative {initiative} {title}",
            object_type="risk",
            object_id=risk_id,
            event_type="created",
            after={"title": title},
        )
        return (
            {"kind": "planledger_risk", "id": risk_id, "title": title},
            f"Added risk {risk_id}: {title}",
            [event],
        )

    _run_command(ctx, "risk.add", execute)


@risk_app.command("list")
def risk_list(
    ctx: typer.Context, open_only: bool = typer.Option(False, "--open")
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        risks = list_records(workspace, "risk")
        if open_only:
            risks = [
                item for item in risks if item.front_matter.get("status") == "open"
            ]
        payload = [
            {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "status": item.front_matter.get("status"),
                "impact": item.front_matter.get("impact"),
                "likelihood": item.front_matter.get("likelihood"),
            }
            for item in risks
        ]
        lines = [f"{item['id']} {item['title']} [{item['status']}]" for item in payload]
        return (
            {"kind": "planledger_risk_list", "risks": payload},
            "\n".join(lines) or "No risks.",
            [],
        )

    _run_command(ctx, "risk.list", execute)


@question_app.command("add")
def question_add(
    ctx: typer.Context,
    title: str,
    goal: str | None = typer.Option(None, "--goal"),
    initiative: str | None = typer.Option(None, "--initiative"),
    priority: str = typer.Option("medium", "--priority"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        scope_kind, scope_id = _resolve_scope_from_refs(
            workspace,
            goal_ref=goal,
            initiative_ref=initiative,
        )
        question_id = allocate_id(workspace, "question")
        timestamp = now_iso()
        front = {
            "id": question_id,
            "type": "question",
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "title": title,
            "status": "open",
            "priority": _validate_choice("priority", priority, PRIORITY_LEVELS),
            "answer": None,
            "answered_at": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        create_record(workspace, "question", front, QUESTION_TEMPLATE)
        event = append_event(
            workspace,
            command=f"planledger question add {title}",
            object_type="question",
            object_id=question_id,
            event_type="created",
            after={"scope_kind": scope_kind, "scope_id": scope_id},
        )
        return (
            {"kind": "planledger_question", "id": question_id, "title": title},
            f"Added question {question_id}: {title}",
            [event],
        )

    _run_command(ctx, "question.add", execute)


@question_app.command("answer")
def question_answer(
    ctx: typer.Context,
    question_ref: str,
    answer: str = typer.Option(..., "--answer"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        question = load_record(workspace, "question", question_ref)
        question.front_matter["status"] = "answered"
        question.front_matter["answer"] = answer
        question.front_matter["answered_at"] = now_iso()
        update_record_timestamp(question)
        save_record(question)
        event = append_event(
            workspace,
            command=f"planledger question answer {question_ref} --answer {answer}",
            object_type="question",
            object_id=question_ref,
            event_type="question_answered",
            after={"status": "answered", "answer": answer},
        )
        return (
            {"kind": "planledger_question_status", "id": question_ref, "status": "answered"},
            f"Answered question {question_ref}",
            [event],
        )

    _run_command(ctx, "question.answer", execute)


@question_app.command("obsolete")
def question_obsolete(
    ctx: typer.Context,
    question_ref: str,
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        question = load_record(workspace, "question", question_ref)
        question.front_matter["status"] = "obsolete"
        question.front_matter["obsolete_reason"] = reason
        update_record_timestamp(question)
        save_record(question)
        event = append_event(
            workspace,
            command=f"planledger question obsolete {question_ref} --reason {reason}",
            object_type="question",
            object_id=question_ref,
            event_type="status_changed",
            after={"status": "obsolete", "reason": reason},
        )
        return (
            {"kind": "planledger_question_status", "id": question_ref, "status": "obsolete"},
            f"Marked question {question_ref} obsolete",
            [event],
        )

    _run_command(ctx, "question.obsolete", execute)


@question_app.command("list")
def question_list(
    ctx: typer.Context,
    open_only: bool = typer.Option(False, "--open"),
    scope: str | None = typer.Option(None, "--scope"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        questions = _sort_records(list_records(workspace, "question"))
        if open_only:
            questions = [
                item for item in questions if item.front_matter.get("status") == "open"
            ]
        if scope is not None:
            scope_kind, scope_id = _resolve_scope_selector(scope)
            questions = [
                item
                for item in questions
                if item.front_matter.get("scope_kind") == scope_kind
                and item.front_matter.get("scope_id") == scope_id
            ]
        payload = [
            {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "status": item.front_matter.get("status"),
                "scope_kind": item.front_matter.get("scope_kind"),
                "scope_id": item.front_matter.get("scope_id"),
            }
            for item in questions
        ]
        return (
            {"kind": "planledger_question_list", "questions": payload},
            "\n".join(_format_record_line(item) for item in questions) or "No questions.",
            [],
        )

    _run_command(ctx, "question.list", execute)


@question_app.command("show")
def question_show(ctx: typer.Context, question_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        question = load_record(workspace, "question", question_ref)
        return (
            {
                "kind": "planledger_question",
                "id": question.record_id,
                "front_matter": question.front_matter,
                "body": question.body,
            },
            _record_human(question),
            [],
        )

    _run_command(ctx, "question.show", execute)


@assumption_app.command("add")
def assumption_add(
    ctx: typer.Context,
    title: str,
    goal: str | None = typer.Option(None, "--goal"),
    initiative: str | None = typer.Option(None, "--initiative"),
    confidence: str = typer.Option("medium", "--confidence"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        scope_kind, scope_id = _resolve_scope_from_refs(
            workspace,
            goal_ref=goal,
            initiative_ref=initiative,
        )
        assumption_id = allocate_id(workspace, "assumption")
        timestamp = now_iso()
        front = {
            "id": assumption_id,
            "type": "assumption",
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "title": title,
            "status": "unverified",
            "confidence": _validate_choice("confidence", confidence, PRIORITY_LEVELS),
            "evidence": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        create_record(workspace, "assumption", front, ASSUMPTION_TEMPLATE)
        event = append_event(
            workspace,
            command=f"planledger assumption add {title}",
            object_type="assumption",
            object_id=assumption_id,
            event_type="created",
            after={"scope_kind": scope_kind, "scope_id": scope_id},
        )
        return (
            {"kind": "planledger_assumption", "id": assumption_id, "title": title},
            f"Added assumption {assumption_id}: {title}",
            [event],
        )

    _run_command(ctx, "assumption.add", execute)


@assumption_app.command("confirm")
def assumption_confirm(
    ctx: typer.Context,
    assumption_ref: str,
    evidence: str = typer.Option(..., "--evidence"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        assumption = load_record(workspace, "assumption", assumption_ref)
        evidence_list = list(assumption.front_matter.get("evidence") or [])
        evidence_list.append(evidence)
        assumption.front_matter["status"] = "confirmed"
        assumption.front_matter["evidence"] = evidence_list
        update_record_timestamp(assumption)
        save_record(assumption)
        event = append_event(
            workspace,
            command=f"planledger assumption confirm {assumption_ref} --evidence {evidence}",
            object_type="assumption",
            object_id=assumption_ref,
            event_type="assumption_confirmed",
            after={"status": "confirmed", "evidence": evidence},
        )
        return (
            {
                "kind": "planledger_assumption_status",
                "id": assumption_ref,
                "status": "confirmed",
            },
            f"Confirmed assumption {assumption_ref}",
            [event],
        )

    _run_command(ctx, "assumption.confirm", execute)


@assumption_app.command("invalidate")
def assumption_invalidate(
    ctx: typer.Context,
    assumption_ref: str,
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        assumption = load_record(workspace, "assumption", assumption_ref)
        assumption.front_matter["status"] = "invalidated"
        assumption.front_matter["invalidation_reason"] = reason
        update_record_timestamp(assumption)
        save_record(assumption)
        event = append_event(
            workspace,
            command=f"planledger assumption invalidate {assumption_ref} --reason {reason}",
            object_type="assumption",
            object_id=assumption_ref,
            event_type="assumption_invalidated",
            after={"status": "invalidated", "reason": reason},
        )
        return (
            {
                "kind": "planledger_assumption_status",
                "id": assumption_ref,
                "status": "invalidated",
            },
            f"Invalidated assumption {assumption_ref}",
            [event],
        )

    _run_command(ctx, "assumption.invalidate", execute)


@assumption_app.command("list")
def assumption_list(
    ctx: typer.Context,
    open_only: bool = typer.Option(False, "--open"),
    scope: str | None = typer.Option(None, "--scope"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        assumptions = _sort_records(list_records(workspace, "assumption"))
        if open_only:
            assumptions = [
                item
                for item in assumptions
                if item.front_matter.get("status") == "unverified"
            ]
        if scope is not None:
            scope_kind, scope_id = _resolve_scope_selector(scope)
            assumptions = [
                item
                for item in assumptions
                if item.front_matter.get("scope_kind") == scope_kind
                and item.front_matter.get("scope_id") == scope_id
            ]
        payload = [
            {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "status": item.front_matter.get("status"),
                "scope_kind": item.front_matter.get("scope_kind"),
                "scope_id": item.front_matter.get("scope_id"),
            }
            for item in assumptions
        ]
        return (
            {"kind": "planledger_assumption_list", "assumptions": payload},
            "\n".join(_format_record_line(item) for item in assumptions) or "No assumptions.",
            [],
        )

    _run_command(ctx, "assumption.list", execute)


@assumption_app.command("show")
def assumption_show(ctx: typer.Context, assumption_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        assumption = load_record(workspace, "assumption", assumption_ref)
        return (
            {
                "kind": "planledger_assumption",
                "id": assumption.record_id,
                "front_matter": assumption.front_matter,
                "body": assumption.body,
            },
            _record_human(assumption),
            [],
        )

    _run_command(ctx, "assumption.show", execute)


@constraint_app.command("add")
def constraint_add(
    ctx: typer.Context,
    title: str,
    scope: str = typer.Option("project", "--scope"),
    goal: str | None = typer.Option(None, "--goal"),
    initiative: str | None = typer.Option(None, "--initiative"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        resolved_scope = _validate_choice("scope", scope, {"project", "goal", "initiative"})
        scope_kind = resolved_scope
        scope_id: str | None = None
        if resolved_scope == "goal":
            if goal is None or initiative is not None:
                raise PlanledgerError(
                    "invalid_options",
                    "Use --goal for goal-scoped constraints.",
                )
            _ = load_record(workspace, "goal", goal)
            scope_id = goal
        elif resolved_scope == "initiative":
            if initiative is None or goal is not None:
                raise PlanledgerError(
                    "invalid_options",
                    "Use --initiative for initiative-scoped constraints.",
                )
            _ = load_record(workspace, "initiative", initiative)
            scope_id = initiative
        constraint_id = allocate_id(workspace, "constraint")
        timestamp = now_iso()
        front = {
            "id": constraint_id,
            "type": "constraint",
            "scope_kind": scope_kind,
            "scope_id": scope_id,
            "title": title,
            "status": "active",
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        create_record(workspace, "constraint", front, CONSTRAINT_TEMPLATE)
        event = append_event(
            workspace,
            command=f"planledger constraint add {title}",
            object_type="constraint",
            object_id=constraint_id,
            event_type="created",
            after={"scope_kind": scope_kind, "scope_id": scope_id},
        )
        return (
            {"kind": "planledger_constraint", "id": constraint_id, "title": title},
            f"Added constraint {constraint_id}: {title}",
            [event],
        )

    _run_command(ctx, "constraint.add", execute)


@constraint_app.command("retire")
def constraint_retire(
    ctx: typer.Context,
    constraint_ref: str,
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        constraint = load_record(workspace, "constraint", constraint_ref)
        constraint.front_matter["status"] = "retired"
        constraint.front_matter["close_reason"] = reason
        constraint.front_matter["closed_at"] = now_iso()
        update_record_timestamp(constraint)
        save_record(constraint)
        event = append_event(
            workspace,
            command=f"planledger constraint retire {constraint_ref} --reason {reason}",
            object_type="constraint",
            object_id=constraint_ref,
            event_type="status_changed",
            after={"status": "retired", "reason": reason},
        )
        return (
            {"kind": "planledger_constraint_status", "id": constraint_ref, "status": "retired"},
            f"Retired constraint {constraint_ref}",
            [event],
        )

    _run_command(ctx, "constraint.retire", execute)


@constraint_app.command("list")
def constraint_list(
    ctx: typer.Context,
    active_only: bool = typer.Option(False, "--active"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        constraints = _sort_records(list_records(workspace, "constraint"))
        if active_only:
            constraints = [
                item for item in constraints if item.front_matter.get("status") == "active"
            ]
        payload = [
            {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "status": item.front_matter.get("status"),
                "scope_kind": item.front_matter.get("scope_kind"),
                "scope_id": item.front_matter.get("scope_id"),
            }
            for item in constraints
        ]
        return (
            {"kind": "planledger_constraint_list", "constraints": payload},
            "\n".join(_format_record_line(item) for item in constraints) or "No constraints.",
            [],
        )

    _run_command(ctx, "constraint.list", execute)


@constraint_app.command("show")
def constraint_show(ctx: typer.Context, constraint_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        constraint = load_record(workspace, "constraint", constraint_ref)
        return (
            {
                "kind": "planledger_constraint",
                "id": constraint.record_id,
                "front_matter": constraint.front_matter,
                "body": constraint.body,
            },
            _record_human(constraint),
            [],
        )

    _run_command(ctx, "constraint.show", execute)


@review_app.command("add")
def review_add(
    ctx: typer.Context,
    title: str,
    scope_kind: str = typer.Option(..., "--scope-kind"),
    scope_id: str = typer.Option(..., "--scope-id"),
    outcome: str = typer.Option(..., "--outcome"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        resolved_scope_kind = _validate_choice(
            "scope-kind", scope_kind, {"goal", "initiative", "plan"}
        )
        resolved_outcome = _validate_choice(
            "outcome",
            outcome,
            {"fulfilled", "cancelled", "superseded", "needs-followup"},
        )
        _ = load_record(workspace, resolved_scope_kind, scope_id)
        review_id = allocate_id(workspace, "review")
        timestamp = now_iso()
        front = {
            "id": review_id,
            "type": "review",
            "scope_kind": resolved_scope_kind,
            "scope_id": scope_id,
            "title": title,
            "status": "completed",
            "outcome": resolved_outcome,
            "findings": [],
            "recommendations": [],
            "created_at": timestamp,
            "updated_at": timestamp,
            "closed_at": timestamp,
        }
        create_record(workspace, "review", front, REVIEW_TEMPLATE)
        event = append_event(
            workspace,
            command=f"planledger review add {title}",
            object_type="review",
            object_id=review_id,
            event_type="review_created",
            after={"scope_kind": resolved_scope_kind, "scope_id": scope_id},
        )
        return (
            {"kind": "planledger_review", "id": review_id, "title": title},
            f"Added review {review_id}: {title}",
            [event],
        )

    _run_command(ctx, "review.add", execute)


@review_app.command("list")
def review_list(
    ctx: typer.Context,
    scope: str | None = typer.Option(None, "--scope"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        reviews = _sort_records(list_records(workspace, "review"))
        if scope is not None:
            scope_kind, scope_id = _resolve_scope_selector(scope)
            reviews = [
                item
                for item in reviews
                if item.front_matter.get("scope_kind") == scope_kind
                and item.front_matter.get("scope_id") == scope_id
            ]
        payload = [
            {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "status": item.front_matter.get("status"),
                "scope_kind": item.front_matter.get("scope_kind"),
                "scope_id": item.front_matter.get("scope_id"),
                "outcome": item.front_matter.get("outcome"),
            }
            for item in reviews
        ]
        return (
            {"kind": "planledger_review_list", "reviews": payload},
            "\n".join(_format_record_line(item) for item in reviews) or "No reviews.",
            [],
        )

    _run_command(ctx, "review.list", execute)


@review_app.command("show")
def review_show(ctx: typer.Context, review_ref: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        review = load_record(workspace, "review", review_ref)
        return (
            {
                "kind": "planledger_review",
                "id": review.record_id,
                "front_matter": review.front_matter,
                "body": review.body,
            },
            _record_human(review),
            [],
        )

    _run_command(ctx, "review.show", execute)


@app.command("next-action")
def next_action_cmd(ctx: typer.Context) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        suggestion = suggest_next_action(workspace)
        message = (
            f"{suggestion.get('action')}: {suggestion.get('next_command')}"
            if suggestion.get("next_command")
            else "No next action"
        )
        return suggestion, message, []

    _run_command(ctx, "next-action", execute)


@taskledger_app.command("detect")
def taskledger_detect(ctx: typer.Context) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        result = detect(workspace)
        if result["detected"]:
            active = result.get("active_task")
            active_display = "none"
            if isinstance(active, dict) and active:
                active_display = (
                    f"{active.get('task_ref')} {active.get('slug') or ''}".strip()
                )
            message = (
                "taskledger detected\n"
                f"Workspace: {result['workspace_root']}\n"
                f"Config: {result['config_path']}\n"
                f"Ledger: {result.get('ledger_ref') or 'unknown'}\n"
                f"Active task: {active_display}"
            )
        else:
            message = "taskledger not detected"
        return result, message, []

    _run_command(ctx, "taskledger.detect", execute)


@taskledger_app.command("bind")
def taskledger_bind(
    ctx: typer.Context,
    slice_ref: str,
    task: str = typer.Option(..., "--task"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        result = bind_slice(workspace, slice_ref, task)
        message = (
            f"Bound {slice_ref} to taskledger task {result['task_ref']} "
            f"via {result['binding']}"
        )
        return result, message, []

    _run_command(ctx, "taskledger.bind", execute)


@taskledger_app.command("push")
def taskledger_push(
    ctx: typer.Context,
    slice_ref: str,
    create_task: bool = typer.Option(False, "--create-task"),
    activate: bool = typer.Option(False, "--activate"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        result = push_slice(
            workspace, slice_ref, create_task=create_task, activate=activate
        )
        message = (
            f"Pushed {slice_ref} to taskledger task {result['task_ref']} "
            f"({result['binding']})"
        )
        return result, message, []

    _run_command(ctx, "taskledger.push", execute)


@taskledger_app.command("pull")
def taskledger_pull(
    ctx: typer.Context,
    slice_ref: str | None = typer.Option(None, "--slice"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        result = pull_status(workspace, slice_id=slice_ref)
        message = f"Pulled {result['count']} taskledger binding snapshots"
        return result, message, []

    _run_command(ctx, "taskledger.pull", execute)


@taskledger_app.command("reconcile")
def taskledger_reconcile(ctx: typer.Context) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        result = reconcile(workspace)
        drift = result.get("drift", [])
        if drift:
            lines = ["Drift found:"]
            for item in drift:
                lines.append(
                    f"- {item.get('kind')} for {item.get('slice')} {item.get('task') or ''}".strip()
                )
                suggestion = item.get("suggested_command")
                if suggestion:
                    lines.append(f"  Suggested command: {suggestion}")
            message = "\n".join(lines)
        else:
            message = "No drift found."
        return result, message, []

    _run_command(ctx, "taskledger.reconcile", execute)


@taskledger_app.command("push-plan")
def taskledger_push_plan(
    ctx: typer.Context,
    plan_ref: str,
    create_tasks: bool = typer.Option(False, "--create-tasks"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    activate_first: bool = typer.Option(False, "--activate-first"),
    update_existing: bool = typer.Option(False, "--update-existing"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        result = push_plan(
            workspace,
            plan_ref,
            create_tasks=create_tasks,
            dry_run=dry_run,
            activate_first=activate_first,
            update_existing=update_existing,
        )
        created = len(result.get("created", []))
        skipped = len(result.get("skipped", []))
        failed = len(result.get("failed", []))
        if dry_run:
            message = (
                f"Dry-run: would push {created} slices, skip {skipped}, fail {failed}."
            )
        else:
            message = f"Pushed {created} slices, skipped {skipped}, failed {failed}."
        return result, message, []

    _run_command(ctx, "taskledger.push-plan", execute)


@taskledger_app.command("plan-template")
def taskledger_plan_template(
    ctx: typer.Context,
    slice_ref: str,
    output: Path = typer.Option(..., "--output"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        output_path = output
        if not output_path.is_absolute():
            output_path = (workspace.root / output_path).resolve()
        result = generate_plan_template(workspace, slice_ref, output_path)
        message = f"Generated taskledger plan template at {result['output']}"
        return result, message, []

    _run_command(ctx, "taskledger.plan-template", execute)


@bundle_app.command("validate")
def bundle_validate(
    ctx: typer.Context,
    bundle_path: Path = typer.Option(..., "--file", help="Path to bundle JSON"),
    strict_unknown_fields: bool = typer.Option(
        False,
        "--strict-unknown-fields",
        help="Treat unknown top-level bundle fields as errors.",
    ),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        bundle = load_bundle(bundle_path)
        details = validate_bundle_details(
            bundle,
            strict_unknown_fields=strict_unknown_fields,
        )
        errors = details.errors
        ok = len(errors) == 0
        result = {
            "kind": "planledger_bundle_validate",
            "ok": ok,
            "errors": errors,
            "warnings": details.warnings,
        }
        if ok:
            if details.warnings:
                message = (
                    "Bundle validation passed with warnings:\n- "
                    + "\n- ".join(details.warnings)
                )
            else:
                message = "Bundle validation passed."
        else:
            message = "Bundle validation failed:\n- " + "\n- ".join(errors)
        return result, message, []

    _run_command(ctx, "bundle.validate", execute)


@bundle_app.command("apply")
def bundle_apply_cmd(
    ctx: typer.Context,
    bundle_path: Path = typer.Option(..., "--file", help="Path to bundle JSON"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        bundle = load_bundle(bundle_path)
        apply_result = apply_bundle(
            workspace,
            bundle,
            dry_run=dry_run,
        )
        result = {
            "kind": "planledger_bundle_apply",
            "dry_run": dry_run,
            "created": apply_result.created,
            "reused": apply_result.reused,
            "plan_id": apply_result.plan_id,
            "events": apply_result.events,
        }
        if dry_run:
            message = (
                f"Bundle dry-run: would create {len(apply_result.created)} records."
            )
        else:
            message = (
                f"Bundle applied: {len(apply_result.created)} created, "
                f"{len(apply_result.reused)} reused."
            )
        return result, message, apply_result.events

    _run_command(ctx, "bundle.apply", execute)


@evolution_app.command("validate")
def evolution_validate(
    ctx: typer.Context,
    bundle_path: Path = typer.Option(..., "--file", help="Path to evolution bundle JSON"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        _ = _resolve_workspace(ctx)
        bundle = load_bundle(bundle_path)
        details = validate_evolution_details(bundle)
        result = {
            "kind": "planledger_evolution_validate",
            "ok": not details.errors,
            "errors": details.errors,
            "warnings": details.warnings,
        }
        message = (
            "Evolution bundle validation: pass"
            if not details.errors
            else "Evolution bundle validation: fail\n- " + "\n- ".join(details.errors)
        )
        return result, message, []

    _run_command(ctx, "evolution.validate", execute)


@evolution_app.command("apply")
def evolution_apply_cmd(
    ctx: typer.Context,
    bundle_path: Path = typer.Option(..., "--file", help="Path to evolution bundle JSON"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        bundle = load_bundle(bundle_path)
        result = apply_evolution_bundle(workspace, bundle, dry_run=dry_run)
        message = (
            f"Evolution dry-run: create {len(result.created)}, update {len(result.updated)}, reuse {len(result.reused)}."
            if dry_run
            else f"Evolution applied: create {len(result.created)}, update {len(result.updated)}, reuse {len(result.reused)}."
        )
        return (
            {
                "kind": "planledger_evolution_apply",
                "dry_run": dry_run,
                "created": result.created,
                "updated": result.updated,
                "reused": result.reused,
            },
            message,
            result.events,
        )

    _run_command(ctx, "evolution.apply", execute)


@adr_app.command("create")
def adr_create(
    ctx: typer.Context,
    title: str,
    initiative: str = typer.Option(..., "--initiative"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        _ = load_record(workspace, "initiative", initiative)
        decision_id = allocate_id(workspace, "decision")
        timestamp = now_iso()
        front: dict[str, Any] = {
            "id": decision_id,
            "type": "decision",
            "decision_type": "architecture",
            "initiative": initiative,
            "title": title,
            "status": "open",
            "chosen_option": None,
            "created_at": timestamp,
            "updated_at": timestamp,
            "accepted_at": None,
        }
        create_record(workspace, "decision", front, ADR_TEMPLATE)
        event = append_event(
            workspace,
            command=f"planledger adr create {title} --initiative {initiative}",
            object_type="decision",
            object_id=decision_id,
            event_type="created",
            after={"title": title, "decision_type": "architecture"},
        )
        return (
            {
                "kind": "planledger_adr",
                "id": decision_id,
                "title": title,
                "decision_type": "architecture",
            },
            f"Created ADR {decision_id}: {title}",
            [event],
        )

    _run_command(ctx, "adr.create", execute)


@adr_app.command("list")
def adr_list(
    ctx: typer.Context,
    initiative: str | None = typer.Option(None, "--initiative"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        decisions = list_records(workspace, "decision")
        adrs = [
            d
            for d in decisions
            if d.front_matter.get("decision_type") == "architecture"
        ]
        if initiative is not None:
            adrs = [d for d in adrs if d.front_matter.get("initiative") == initiative]
        payload = [
            {
                "id": d.record_id,
                "title": d.front_matter.get("title"),
                "status": d.front_matter.get("status"),
                "initiative": d.front_matter.get("initiative"),
            }
            for d in adrs
        ]
        lines = [f"{item['id']} {item['title']} [{item['status']}]" for item in payload]
        return (
            {"kind": "planledger_adr_list", "decisions": payload},
            "\n".join(lines) or "No ADRs.",
            [],
        )

    _run_command(ctx, "adr.list", execute)


@adr_app.command("accept")
def adr_accept(
    ctx: typer.Context,
    decision_ref: str,
    option: str = typer.Option(..., "--option"),
    rationale: str = typer.Option(..., "--rationale"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        decision = load_record(workspace, "decision", decision_ref)
        if decision.front_matter.get("decision_type") != "architecture":
            raise PlanledgerError(
                "invalid_reference",
                f"{decision_ref} is not an ADR.",
                remediation=["Use planledger decision accept for non-ADR decisions."],
            )
        chosen_option = load_record(workspace, "option", option)
        if chosen_option.front_matter.get("decision") != decision_ref:
            raise PlanledgerError(
                "invalid_reference",
                f"Option {option} does not belong to {decision_ref}.",
            )
        decision.front_matter["status"] = "accepted"
        decision.front_matter["chosen_option"] = option
        decision.front_matter["accepted_at"] = now_iso()
        update_record_timestamp(decision)
        if "## Rationale" in decision.body:
            decision.body = decision.body.rstrip() + f"\n\n{rationale}\n"
        else:
            decision.body = (
                decision.body.rstrip() + f"\n\n## Rationale\n\n{rationale}\n"
            )
        save_record(decision)
        event = append_event(
            workspace,
            command=(
                f"planledger adr accept {decision_ref} "
                f"--option {option} --rationale {rationale}"
            ),
            object_type="decision",
            object_id=decision_ref,
            event_type="accepted",
            after={"chosen_option": option},
        )
        return (
            {
                "kind": "planledger_adr_accept",
                "decision": decision_ref,
                "chosen_option": option,
            },
            f"Accepted ADR {decision_ref} with option {option}",
            [event],
        )

    _run_command(ctx, "adr.accept", execute)


@backfill_app.command("apply")
def backfill_apply_cmd(
    ctx: typer.Context,
    bundle_path: Path = typer.Option(..., "--file", help="Path to bundle JSON file"),
    evidence: list[str] = typer.Option(
        [], "--evidence", help="Evidence: path:reason pairs"
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        parsed_evidence = []
        for ev in evidence:
            parts = ev.split(":", 1)
            if len(parts) == 2:
                parsed_evidence.append({"path": parts[0], "reason": parts[1]})
            else:
                parsed_evidence.append({"path": ev, "reason": ""})
        result = backfill_apply(
            workspace,
            bundle_path,
            evidence=parsed_evidence or None,
            dry_run=dry_run,
        )
        message = (
            f"Backfill {result['provenance']}: "
            f"{len(result['created'])} created, "
            f"{len(result['reused'])} reused."
        )
        return result, message, result.get("events", [])

    _run_command(ctx, "backfill.apply", execute)


@backfill_app.command("review")
def backfill_review_cmd(ctx: typer.Context) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        result = backfill_review(workspace)
        records = result["records"]
        if records:
            lines = ["Inferred records:"]
            for r in records:
                lines.append(f"  {r['id']} ({r['kind']}) {r['title']}")
            message = "\n".join(lines)
        else:
            message = "No inferred records found."
        return result, message, []

    _run_command(ctx, "backfill.review", execute)
