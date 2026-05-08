# ruff: noqa: B008, E501
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from planledger import __version__
from planledger.backfill import backfill_apply, backfill_review
from planledger.bundle import apply_bundle, load_bundle, validate_bundle
from planledger.context import export_context
from planledger.errors import PlanledgerError
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
taskledger_app = typer.Typer(help="taskledger integration")
bundle_app = typer.Typer(help="Bundle import")
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
app.add_typer(taskledger_app, name="taskledger")
app.add_typer(bundle_app, name="bundle")
app.add_typer(context_app, name="context")
app.add_typer(adr_app, name="adr")
app.add_typer(backfill_app, name="backfill")


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


@app.command("init")
def project_init(
    ctx: typer.Context,
    project_name: str = typer.Option("Planledger", "--project-name"),
    planledger_dir: str = typer.Option(".planledger", "--planledger-dir"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        app_ctx = _context(ctx)
        root = workspace_root_from_context(app_ctx, init_mode=True)
        workspace = initialize_project(
            root, project_name, planledger_dir=planledger_dir
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
        next_action = suggest_next_action(workspace)
        doctor_result = doctor(workspace)

        # Build structured result
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
        }

        lines: list[str] = []
        lines.append(f"Project: {project_name}")
        lines.append(f"Root: {workspace.root}")
        lines.append(f"Ledger: {workspace.ledger_ref}")
        lines.append(f"Counts: {counts}")

        # Active initiative + goal
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

        # Latest plan
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

        # Open decisions
        all_decisions = list_records(workspace, "decision")
        open_decisions = [
            d for d in all_decisions if d.front_matter.get("status") == "open"
        ]
        decision_items = []
        if open_decisions:
            lines.append("")
            lines.append(f"Open decisions ({len(open_decisions)}):")
            for d in open_decisions:
                d_title = d.front_matter.get("title", "")
                decision_items.append({"id": d.record_id, "title": d_title})
                lines.append(f"  {d.record_id} {d_title}")
        result["open_decisions"] = decision_items

        # Open risks
        all_risks = list_records(workspace, "risk")
        open_risks = [r for r in all_risks if r.front_matter.get("status") == "open"]
        risk_items = []
        if open_risks:
            lines.append("")
            lines.append(f"Open risks ({len(open_risks)}):")
            for r in open_risks:
                r_title = r.front_matter.get("title", "")
                r_impact = r.front_matter.get("impact", "")
                risk_items.append(
                    {"id": r.record_id, "title": r_title, "impact": r_impact}
                )
                lines.append(f"  {r.record_id} {r_title} (impact: {r_impact})")
        result["open_risks"] = risk_items

        # Next action
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

        # Doctor issues
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
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        result = export_context(
            workspace,
            include_taskledger=include_taskledger,
            include_bodies=include_bodies,
            max_body_chars=max_body_chars,
            max_events=max_events,
            allow_external=include_taskledger,
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
def goal_create(ctx: typer.Context, title: str) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        goal_id = allocate_id(workspace, "goal")
        timestamp = now_iso()
        front = {
            "id": goal_id,
            "type": "goal",
            "title": title,
            "status": "active",
            "horizon": "quarter",
            "priority": "high",
            "success_metrics": [],
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        create_record(workspace, "goal", front, "")
        event = append_event(
            workspace,
            command=f"planledger goal create {title}",
            object_type="goal",
            object_id=goal_id,
            event_type="created",
            after={"title": title},
        )
        return (
            {"kind": "planledger_goal", "id": goal_id, "title": title},
            f"Created goal {goal_id}: {title}",
            [event],
        )

    _run_command(ctx, "goal.create", execute)


@goal_app.command("list")
def goal_list(ctx: typer.Context) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        goals = list_records(workspace, "goal")
        payload = [
            {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "status": item.front_matter.get("status"),
            }
            for item in goals
        ]
        message = "\n".join(
            [f"{item['id']} {item['title']} [{item['status']}]" for item in payload]
        )
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


@initiative_app.command("create")
def initiative_create(
    ctx: typer.Context,
    title: str,
    goal: str = typer.Option(..., "--goal"),
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        _ = load_record(workspace, "goal", goal)
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
def initiative_list(ctx: typer.Context) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        active = active_initiative(workspace)
        initiatives = list_records(workspace, "initiative")
        payload = []
        lines = []
        for item in initiatives:
            row = {
                "id": item.record_id,
                "title": item.front_matter.get("title"),
                "status": item.front_matter.get("status"),
                "active": item.record_id == active,
            }
            payload.append(row)
            marker = "*" if row["active"] else " "
            lines.append(f"{marker} {row['id']} {row['title']} [{row['status']}]")
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
        goal_record = None
        if goal_ref is not None:
            goal_record = load_record(workspace, "goal", str(goal_ref))
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
    ctx: typer.Context, initiative: str | None = typer.Option(None, "--initiative")
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        plans = list_records(workspace, "plan")
        if initiative is not None:
            plans = [
                plan
                for plan in plans
                if plan.front_matter.get("initiative") == initiative
            ]
        plans = sorted(plans, key=lambda item: parse_ref_numeric(item.record_id))
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
            f"{item['id']} v{item['version']} {item['initiative']} [{item['status']}]"
            for item in payload
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
    ctx: typer.Context, initiative: str | None = typer.Option(None, "--initiative")
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        slices = list_records(workspace, "slice")
        if initiative is not None:
            slices = [
                item
                for item in slices
                if item.front_matter.get("initiative") == initiative
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
        before = {"status": slice_record.front_matter.get("status")}
        slice_record.front_matter["status"] = "ready-for-execution"
        update_record_timestamp(slice_record)
        save_record(slice_record)
        event = append_event(
            workspace,
            command=f"planledger slice ready {slice_ref}",
            object_type="slice",
            object_id=slice_ref,
            event_type="status_changed",
            before=before,
            after={"status": "ready-for-execution"},
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
        before = {"status": slice_record.front_matter.get("status")}
        slice_record.front_matter["status"] = "executed"
        slice_record.front_matter["execution_status"] = "done"
        if evidence:
            slice_record.front_matter["execution_evidence"] = evidence
        update_record_timestamp(slice_record)
        save_record(slice_record)
        event = append_event(
            workspace,
            command=f"planledger slice done {slice_ref}",
            object_type="slice",
            object_id=slice_ref,
            event_type="status_changed",
            before=before,
            after={"status": "executed", "evidence": evidence or None},
        )
        return (
            {"kind": "planledger_slice_status", "id": slice_ref, "status": "executed"},
            f"Slice {slice_ref} marked executed",
            [event],
        )

    _run_command(ctx, "slice.done", execute)


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
) -> None:
    def execute() -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        workspace = _resolve_workspace(ctx)
        bundle = load_bundle(bundle_path)
        errors = validate_bundle(bundle)
        ok = len(errors) == 0
        result = {
            "kind": "planledger_bundle_validate",
            "ok": ok,
            "errors": errors,
        }
        if ok:
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
