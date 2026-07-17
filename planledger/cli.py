# ruff: noqa: B008,E501
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import typer

from planledger import __version__
from planledger.bundle import (
    apply_structured_plan_bundle,
    apply_structured_workshop_bundle,
    load_bundle,
)
from planledger.errors import PlanledgerError
from planledger.migration import (
    apply_migration,
    inspect_migration,
    inspection_to_dict,
    result_to_dict,
)
from planledger.models import AppContext, PlanStatus, Workspace
from planledger.prompt_profiles import load_prompt_profile
from planledger.render import build_plan, build_workshop
from planledger.storage import (
    activate_plan,
    activate_workshop,
    append_component,
    append_workshop_component,
    collect_inventory,
    component_spec,
    compute_next_action,
    create_plan,
    create_plan_from_workshop,
    create_workshop,
    diff_versions,
    diff_workshop_versions,
    discover_workspace,
    doctor,
    get_active_plan_id,
    get_active_workshop_id,
    initialize_project,
    latest_rendered_path,
    latest_rendered_workshop_path,
    list_plans,
    list_versions,
    list_workshop_versions,
    list_workshops,
    load_component_content,
    load_plan,
    load_workshop,
    load_workshop_component_content,
    load_workspace,
    plan_status_counts,
    plan_to_dict,
    read_input_text,
    resolve_plan_id,
    resolve_workshop_id,
    set_component,
    set_plan_status,
    set_workshop_component,
    set_workshop_status,
    storage_data,
    validate_plan,
    validate_workshop,
    version_label,
    workshop_status_counts,
    workshop_to_dict,
    workspace_root_from_context,
)

ACTIVE_PLAN_HELP = "Plan id (uses active plan if omitted)"
PLAN_OVERRIDE_HELP = "Plan id (overrides positional)"

app = typer.Typer(help="Structured versioned planning files")
plan_app = typer.Typer(help="Plan commands")
component_app = typer.Typer(help="Plan component commands")
workshop_app = typer.Typer(help="Planning workshop commands")
workshop_component_app = typer.Typer(help="Workshop component commands")
app.add_typer(plan_app, name="plan")
plan_app.add_typer(component_app, name="component")
app.add_typer(workshop_app, name="workshop")
migrate_app = typer.Typer(help="Inspect and apply canonical Planledger migrations")
app.add_typer(migrate_app, name="migrate")
workshop_app.add_typer(workshop_component_app, name="component")


def _migration_message(payload: dict[str, Any]) -> str:
    source = payload.get("source", {})
    target = payload.get("target", {})
    issues = payload.get("issues", [])
    lines = [
        "PLANLEDGER MIGRATION",
        f"Source: {source.get('kind')} {source.get('path') or '(none)'}",
        f"Target: {target.get('data_root')}",
        f"Plans: {payload.get('plan_count', 0)}  Workshops: {payload.get('workshop_count', 0)}",
        "Safety: source preserved by default; Taskledger data is not modified.",
    ]
    if issues:
        lines.append("Issues:")
        lines.extend(
            f"  [{item.get('severity')}] {item.get('code')}: {item.get('message')}"
            for item in issues
        )
    else:
        lines.append("Apply: planledger migrate apply")
    return "\n".join(lines)


@migrate_app.callback(invoke_without_command=True)
def migrate_callback(
    ctx: typer.Context,
    source: Path | None = typer.Option(
        None, "--source", help="Legacy source data root"
    ),
    sibling_ledger_root: Path | None = typer.Option(
        None,
        "--sibling-ledger-root",
        help="Migration-only destination sibling root",
    ),
    ) -> None:
    if ctx.invoked_subcommand is not None:
        return

    def run() -> tuple[dict[str, Any], str]:
        inspection = inspect_migration(
            workspace_root_from_context(_context(ctx)),
            source=source,
            sibling_ledger_root=sibling_ledger_root,
        )
        payload = inspection_to_dict(inspection)
        return payload, _migration_message(payload)

    _run_command(ctx, "migrate", run)


@migrate_app.command("apply")
def migrate_apply(
    ctx: typer.Context,
    source: Path | None = typer.Option(
        None, "--source", help="Legacy source data root"
    ),
    backup: bool = typer.Option(
        True, "--backup/--no-backup", help="Deprecated; backup is automatic."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Inspect without writing."
    ),
    create_sibling_store: bool = typer.Option(
        False,
        "--create-sibling-store",
        help="Create the selected sibling store if absent",
    ),
    sibling_ledger_root: Path | None = typer.Option(
        None,
        "--sibling-ledger-root",
        help="Migration-only destination sibling root",
    ),
    backup_dir: Path | None = typer.Option(
        None, "--backup-dir", help="Backup destination"
    ),
    retire_source: bool = typer.Option(
        False,
        "--retire-source",
        "--retire-legacy",
        help="Retire the source after verification",
    ),
    ) -> None:
    def run() -> tuple[dict[str, Any], str]:
        root = workspace_root_from_context(_context(ctx))
        inspection = inspect_migration(
            root,
            source=source,
            sibling_ledger_root=sibling_ledger_root,
        )
        if dry_run:
            payload = inspection_to_dict(inspection)
            payload["status"] = "dry_run"
            return payload, _migration_message(payload)
        result = apply_migration(
            inspection,
            backup_dir=backup_dir,
            create_sibling_store=create_sibling_store,
            retire_source=retire_source,
            backup=backup,
        )
        payload = result_to_dict(result)
        return (
            payload,
            f"Migration applied\nTarget: {result.receipt_path.parent.parent}\nReceipt: {result.receipt_path}\nBackup: {result.backup_dir}",
        )

    _run_command(ctx, "migrate.apply", run)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    root: Path | None = typer.Option(None, "--root", help="Workspace root override"),
    cwd: Path | None = typer.Option(None, "--cwd", help="Current workspace"),
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
        raise PlanledgerError("internal_error", "Missing application context.")
    return app_ctx


def _emit(
    app_ctx: AppContext,
    command: str,
    result: dict[str, Any],
    message: str,
) -> None:
    if app_ctx.json_output:
        typer.echo(
            json.dumps(
                {
                    "ok": True,
                    "command": command,
                    "result": result,
                    "events": [],
                },
                indent=2,
                default=str,
            )
        )
        return
    typer.echo(message)


def _emit_error(app_ctx: AppContext, command: str, error: PlanledgerError) -> None:
    if app_ctx.json_output:
        typer.echo(
            json.dumps(
                {
                    "ok": False,
                    "command": command,
                    "error": error.to_dict(),
                },
                indent=2,
                default=str,
            )
        )
        return
    typer.echo(f"Error [{error.code}]: {error.message}")
    for item in error.remediation:
        typer.echo(f"- {item}")


def _run_command(
    ctx: typer.Context,
    command: str,
    fn: Callable[[], tuple[dict[str, Any], str]],
) -> None:
    app_ctx = _context(ctx)
    try:
        result, message = fn()
    except PlanledgerError as error:
        _emit_error(app_ctx, command, error)
        raise typer.Exit(code=error.exit_code) from error
    except Exception as error:  # pragma: no cover
        wrapped = PlanledgerError("internal_error", str(error))
        _emit_error(app_ctx, command, wrapped)
        raise typer.Exit(code=1) from error
    _emit(app_ctx, command, result, message)


def _require_workspace(ctx: typer.Context) -> Workspace:
    return load_workspace(_context(ctx))


def _summary_message(plan: dict[str, Any], verb: str) -> str:
    return (
        f"{verb} {plan['plan_id']} "
        f"({plan['status']}, {version_label(int(plan['version']))}) -> "
        f"{plan['latest_rendered_path']}"
    )


def _human_plan_details(plan: dict[str, Any]) -> str:
    lines = [
        plan["plan_id"],
        f"title: {plan['title']}",
        f"status: {plan['status']}",
        f"version: {version_label(int(plan['version']))}",
        f"path: {plan['path']}",
        f"rendered: {plan['latest_rendered_path']}",
    ]
    return "\n".join(lines)


@app.command()
def init(
    ctx: typer.Context,
    project_name: str | None = typer.Option(
        None, "--project-name", help="Project name"
    ),
    create_sibling_store: bool = typer.Option(
        False,
        "--create-sibling-store",
        help="Create the canonical sibling Ledger store if absent",
    ),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        app_ctx = _context(ctx)
        root = workspace_root_from_context(app_ctx)
        store_existed = (root.parent / "ledger" / ".ledger-store").is_file()
        workspace = initialize_project(
            root=root,
            project_name=project_name or root.name,
            create_sibling_store=create_sibling_store,
        )
        result = {
            "kind": "planledger_init",
            "schema_version": 1,
            "workspace_provider": workspace.workspace_provider,
            "store_root": str(workspace.store_root),
            "authoritative_path": str(workspace.planledger_dir),
            "binding": "valid",
            "created_store": create_sibling_store and not store_existed,
        }
        return result, (
            f"Initialized planledger\nProvider: {workspace.workspace_provider}\n"
            f"Store: {workspace.store_root}\nAuthoritative data: {workspace.planledger_dir}"
        )

    _run_command(ctx, "init", run)


@app.command()
def status(
    ctx: typer.Context,
    check: bool = typer.Option(False, "--check", help="Run health checks"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        app_ctx = _context(ctx)
        workspace = discover_workspace(app_ctx)
        root = workspace_root_from_context(app_ctx)
        if workspace is None:
            result = {"initialized": False, "root": str(root)}
            message = f"Planledger status\nWorkspace: {root}\nNot initialized."
            return result, message

        config = workspace.config.get("project", {})
        if not isinstance(config, dict):
            config = {}
        try:
            data = storage_data(workspace)
        except PlanledgerError as error:
            recovery_health: dict[str, Any] = {"checked": True, **doctor(workspace)}
            project_name = str(config.get("name") or workspace.root.name)
            project_uuid = str(config.get("uuid") or "")
            result = {
                "initialized": True,
                "storage_ready": False,
                "root": str(workspace.root),
                "config_path": str(workspace.config_path),
                "project_name": project_name,
                "project_uuid": project_uuid,
                "planledger_dir": str(workspace.planledger_dir),
                "storage_path": str(workspace.storage_path),
                "schema_version": None,
                "plan_count": 0,
                "status_counts": {},
                "active_plan": None,
                "health": recovery_health,
                "storage_error": error.to_dict(),
            }
            lines = [
                "Planledger status",
                f"Workspace: {workspace.root}",
                f"Config: {workspace.config_path}",
                f"Planledger dir: {workspace.planledger_dir}",
            ]
            if project_name and project_uuid:
                lines.append(f"Project: {project_name} ({project_uuid})")
            elif project_name:
                lines.append(f"Project: {project_name}")
            lines.append(f"Storage: missing or unreadable ({workspace.storage_path})")
            lines.append("Active plan: none")
            lines.append("Counts: plans=0")
            lines.append("Health: issues found")
            lines.append("Next: planledger doctor")
            return result, "\n".join(lines)

        project_name = workspace.project_name or workspace.root.name
        project_uuid = workspace.project_uuid

        active_workshop_id = get_active_workshop_id(workspace)
        active_workshop_info: dict[str, Any] | None = None
        if active_workshop_id is not None:
            try:
                active_workshop = load_workshop(workspace, active_workshop_id)
                active_workshop_info = {
                    "workshop_id": active_workshop.workshop_id,
                    "title": active_workshop.title,
                    "status": active_workshop.status,
                }
            except PlanledgerError:
                active_workshop_info = {
                    "workshop_id": active_workshop_id,
                    "title": "(missing)",
                    "status": "unknown",
                }

        active_plan_id = get_active_plan_id(workspace)
        active_plan_info: dict[str, Any] | None = None
        if active_plan_id is not None:
            try:
                active_plan = load_plan(workspace, active_plan_id)
                active_plan_info = {
                    "plan_id": active_plan.plan_id,
                    "title": active_plan.title,
                    "status": active_plan.status,
                }
            except PlanledgerError:
                active_plan_info = {
                    "plan_id": active_plan_id,
                    "title": "(missing)",
                    "status": "unknown",
                }

        status_counts = plan_status_counts(workspace)
        workshop_counts = workshop_status_counts(workspace)
        plan_count = len(list_plans(workspace))
        workshop_count = len(list_workshops(workspace))

        health_result: dict[str, Any] = {"checked": False, "healthy": None}
        if check:
            health_result = {"checked": True, **doctor(workspace)}

        profiles = [
            load_prompt_profile(workspace.config).to_dict()
            for profile_name in ("planning_interview",)
            if load_prompt_profile(workspace.config, name=profile_name).enabled
        ]
        enabled_profile = load_prompt_profile(workspace.config)
        profiles = [enabled_profile.to_dict()] if enabled_profile.enabled else []
        result = {
            "initialized": True,
            "root": str(workspace.root),
            "config_path": str(workspace.config_path),
            "project_name": project_name,
            "project_uuid": project_uuid,
            "planledger_dir": str(workspace.planledger_dir),
            "workspace_provider": workspace.workspace_provider,
            "store_root": str(workspace.store_root),
            "store_marker_path": str(workspace.store_marker_path),
            "active_mount": workspace.active_mount_name,
            "binding_path": str(workspace.binding_path),
            "schema_version": data.get("schema_version"),
            "plan_count": plan_count,
            "workshop_count": workshop_count,
            "status_counts": status_counts,
            "workshop_status_counts": workshop_counts,
            "active_plan": active_plan_info,
            "active_workshop": active_workshop_info,
            "health": health_result,
            "prompt_profiles": profiles,
        }

        lines = ["Planledger status"]
        lines.append(f"Workspace: {workspace.root}")
        lines.append(f"Config: {workspace.config_path}")
        lines.append(f"Storage provider: {workspace.workspace_provider}")
        lines.append(f"Sibling store: {workspace.store_root}")
        lines.append(f"Authoritative data: {workspace.planledger_dir}")
        lines.append(f"Binding: {workspace.binding_path}")
        if project_name and project_uuid:
            lines.append(f"Project: {project_name} ({project_uuid})")
        elif project_name:
            lines.append(f"Project: {project_name}")

        if isinstance(active_plan_info, dict):
            lines.append(
                f"Active plan: {active_plan_info['plan_id']} "
                f"{active_plan_info['title']} ({active_plan_info['status']})"
            )
        else:
            lines.append("Active plan: none")

        count_parts = [f"plans={plan_count}"]
        for key in sorted(status_counts):
            count_parts.append(f"{key}={status_counts[key]}")
        lines.append(f"Counts: {' '.join(count_parts)}")

        if health_result.get("checked"):
            health = "healthy" if health_result.get("healthy") else "issues found"
            lines.append(f"Health: {health}")
        else:
            lines.append("Health: not checked (use --check)")
        if profiles:
            hint = "active" if profiles[0].get("active") else "enabled"
            lines.append(f"Prompt profile: {profiles[0]['name']} {hint}")
        lines.append("Next: planledger next-action")

        return result, "\n".join(lines)

    _run_command(ctx, "status", run)


def _format_bytes(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{int(size)} B" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _record_matches(
    entry_id: str, global_ref: str, file_ref: str, selector: str
) -> bool:
    sel = selector.strip().lower()
    if not sel:
        return False
    return sel in {entry_id.lower(), global_ref.lower(), file_ref.lower()}


def _inventory_header(
    result: dict[str, Any], title: str = "Planledger info"
) -> list[str]:
    ws = result["workspace"]
    lines = [title, f"Workspace: {ws['root']}", f"Config: {ws['config_path']}"]
    lines.append(f"Planledger dir: {ws['planledger_dir']}")
    lines.append(f"Storage provider: {ws['workspace_provider']}")
    lines.append(f"Storage: {ws['storage_path']}")
    return lines


def _human_inventory_paths(result: dict[str, Any]) -> str:
    lines = _inventory_header(result, "Planledger info (paths)")
    lines.append(f"Plans ({result['plan_count']}):")
    if result["plans"]:
        for entry in result["plans"]:
            lines.append(f"  {entry['plan_id']}  {entry['path']}")
            lines.append(f"    rendered: {entry['latest_rendered_path']}")
    else:
        lines.append("  (none)")
    lines.append(f"Workshops ({result['workshop_count']}):")
    if result["workshops"]:
        for entry in result["workshops"]:
            lines.append(f"  {entry['workshop_id']}  {entry['path']}")
            lines.append(f"    rendered: {entry['latest_rendered_path']}")
    else:
        lines.append("  (none)")
    lines.append("Next: planledger next-action")
    return "\n".join(lines)


def _human_record_focused(
    entry: dict[str, Any],
    *,
    kind: str,
    id_key: str,
    no_components: bool,
    paths_only: bool,
) -> str:
    lines = [
        f"{kind.capitalize()}: {entry[id_key]}  {entry['global_ref']}",
        f"title: {entry['title']}",
        f"status: {entry['status']}",
        f"version: {version_label(int(entry['version']))}",
    ]
    if paths_only:
        lines.append(f"path: {entry['path']}")
        lines.append(f"rendered: {entry['latest_rendered_path']}")
        return "\n".join(lines)
    lines.append(f"path: {entry['path']}")
    rendered_state = "exists" if entry.get("latest_rendered_exists") else "(missing)"
    lines.append(f"rendered: {entry['latest_rendered_path']}  {rendered_state}")
    versions = entry.get("versions") or []
    lines.append(f"versions: {', '.join(versions) if versions else '(none)'}")
    lines.append(f"size: {_format_bytes(int(entry.get('size_bytes', 0)))}")
    components = entry.get("components", {})
    filled = int(entry.get("filled_components", 0))
    total = int(entry.get("total_components", len(components)))
    if no_components:
        lines.append(
            f"components: {filled}/{total} filled (use without --no-components for detail)"
        )
    else:
        lines.append(f"components ({filled}/{total} filled):")
        for key, is_filled in components.items():
            mark = "[x]" if is_filled else "[ ]"
            lines.append(f"  {mark} {key}")
    lines.append("Next: planledger next-action")
    return "\n".join(lines)


def _human_inventory_full(result: dict[str, Any], *, no_components: bool) -> str:
    lines = _inventory_header(result)
    ws = result["workspace"]
    if ws["project_name"] and ws["project_uuid"]:
        lines.append(f"Project: {ws['project_name']} ({ws['project_uuid']})")
    elif ws["project_name"]:
        lines.append(f"Project: {ws['project_name']}")
    storage = result["storage"]
    lines.append(f"Storage provider: {ws['workspace_provider']}")
    lines.append(f"Authoritative data: {ws['planledger_dir']}")
    lines.append(f"Binding: {ws['binding_path']}")
    schema = storage.get("schema_version")
    lines.append(f"Schema: {f'v{schema}' if schema is not None else 'unknown'}")
    allocations = result.get("allocations", {})
    lines.append(f"Next plan ID: {allocations.get('next_plan_id')}")
    lines.append(f"Next workshop ID: {allocations.get('next_workshop_id')}")
    active_plan = storage.get("active_plan_id")
    if active_plan:
        match = next((p for p in result["plans"] if p["plan_id"] == active_plan), None)
        if match:
            lines.append(
                f"Active plan: {match['plan_id']} {match['title']} ({match['status']})"
            )
        else:
            lines.append(f"Active plan: {active_plan} (missing)")
    else:
        lines.append("Active plan: none")
    active_workshop = storage.get("active_workshop_id")
    if active_workshop:
        match = next(
            (w for w in result["workshops"] if w["workshop_id"] == active_workshop),
            None,
        )
        if match:
            lines.append(
                f"Active workshop: {match['workshop_id']} {match['title']} ({match['status']})"
            )
        else:
            lines.append(f"Active workshop: {active_workshop} (missing)")
    else:
        lines.append("Active workshop: none")

    lines.append(f"\nPlans ({result['plan_count']}):")
    if result["plans"]:
        for entry in result["plans"]:
            fill = ""
            if not no_components:
                fill = f"  {entry['filled_components']}/{entry['total_components']}"
            lines.append(
                f"  {entry['plan_id']}  {version_label(int(entry['version']))}  "
                f"[{entry['status']}]{fill}  {entry['title']}"
            )
    else:
        lines.append("  (none)")

    lines.append(f"\nWorkshops ({result['workshop_count']}):")
    if result["workshops"]:
        for entry in result["workshops"]:
            fill = ""
            if not no_components:
                fill = f"  {entry['filled_components']}/{entry['total_components']}"
            lines.append(
                f"  {entry['workshop_id']}  {version_label(int(entry['version']))}  "
                f"[{entry['status']}]{fill}  {entry['title']}"
            )
    else:
        lines.append("  (none)")

    size = result.get("size_bytes", {})
    lines.append("\nDisk footprint:")
    lines.append(f"  plans:      {_format_bytes(int(size.get('plans', 0)))}")
    lines.append(f"  workshops:  {_format_bytes(int(size.get('workshops', 0)))}")
    lines.append(f"  total:      {_format_bytes(int(size.get('total', 0)))}")
    lines.append("Next: planledger next-action")
    return "\n".join(lines)


def _human_inventory(
    result: dict[str, Any],
    *,
    no_components: bool = False,
    paths_only: bool = False,
) -> str:
    if not result.get("initialized", True):
        return f"Planledger info\nWorkspace: {result['root']}\nNot initialized."
    focus = result.get("focus")
    if focus == "plan":
        return _human_record_focused(
            result["plan"],
            kind="plan",
            id_key="plan_id",
            no_components=no_components,
            paths_only=paths_only,
        )
    if focus == "workshop":
        return _human_record_focused(
            result["workshop"],
            kind="workshop",
            id_key="workshop_id",
            no_components=no_components,
            paths_only=paths_only,
        )
    if paths_only:
        return _human_inventory_paths(result)
    return _human_inventory_full(result, no_components=no_components)


def _strip_components(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stripped: list[dict[str, Any]] = []
    for entry in entries:
        copy_entry = {key: value for key, value in entry.items() if key != "components"}
        stripped.append(copy_entry)
    return stripped


@app.command("info")
def info(
    ctx: typer.Context,
    plan: str | None = typer.Option(
        None, "--plan", help="Narrow to one plan (id, global ref, or file ref)"
    ),
    workshop: str | None = typer.Option(
        None,
        "--workshop",
        help="Narrow to one workshop (id, global ref, or file ref)",
    ),
    no_components: bool = typer.Option(
        False,
        "--no-components",
        help="Omit per-component fill-state detail",
    ),
    paths_only: bool = typer.Option(
        False,
        "--paths-only",
        help="Print only resolved paths (reduces human and JSON output)",
    ),
) -> None:
    """Show a read-only inventory of everything planledger has stored.

    Prints workspace/config/storage paths, schema version and id counters,
    the active plan/workshop, and every plan and workshop with status,
    version, component fill-state, rendered artifact path, and disk size.
    Unlike ``status`` (quick health/counts + active plan), ``info`` shows the
    full stored inventory. Use ``--plan``/``--workshop`` to narrow to one
    record, ``--paths-only`` for just paths, or ``--no-components`` to drop
    per-component fill-state.
    """

    def run() -> tuple[dict[str, Any], str]:
        app_ctx = _context(ctx)
        workspace = discover_workspace(app_ctx)
        root = workspace_root_from_context(app_ctx)
        if workspace is None:
            result = {"initialized": False, "root": str(root)}
            return result, f"Planledger info\nWorkspace: {root}\nNot initialized."

        if plan is not None and workshop is not None:
            raise PlanledgerError(
                "invalid_options",
                "Use either --plan or --workshop, not both.",
            )

        inventory = collect_inventory(workspace)

        if plan is not None:
            match = next(
                (
                    entry
                    for entry in inventory["plans"]
                    if _record_matches(
                        entry["plan_id"], entry["global_ref"], entry["file_ref"], plan
                    )
                ),
                None,
            )
            if match is None:
                raise PlanledgerError(
                    "not_found",
                    f"No plan matches {plan!r}.",
                    remediation=["Run: planledger info"],
                )
            if no_components:
                match = {k: v for k, v in match.items() if k != "components"}
            result = {
                "initialized": True,
                "workspace": inventory["workspace"],
                "focus": "plan",
                "plan": match,
            }
        elif workshop is not None:
            match = next(
                (
                    entry
                    for entry in inventory["workshops"]
                    if _record_matches(
                        entry["workshop_id"],
                        entry["global_ref"],
                        entry["file_ref"],
                        workshop,
                    )
                ),
                None,
            )
            if match is None:
                raise PlanledgerError(
                    "not_found",
                    f"No workshop matches {workshop!r}.",
                    remediation=["Run: planledger info"],
                )
            if no_components:
                match = {k: v for k, v in match.items() if k != "components"}
            result = {
                "initialized": True,
                "workspace": inventory["workspace"],
                "focus": "workshop",
                "workshop": match,
            }
        elif paths_only:
            result = {
                "initialized": True,
                "workspace": inventory["workspace"],
                "plan_count": inventory["plan_count"],
                "workshop_count": inventory["workshop_count"],
                "plans": [
                    {
                        "plan_id": e["plan_id"],
                        "path": e["path"],
                        "latest_rendered_path": e["latest_rendered_path"],
                        "latest_rendered_exists": e["latest_rendered_exists"],
                    }
                    for e in inventory["plans"]
                ],
                "workshops": [
                    {
                        "workshop_id": e["workshop_id"],
                        "path": e["path"],
                        "latest_rendered_path": e["latest_rendered_path"],
                        "latest_rendered_exists": e["latest_rendered_exists"],
                    }
                    for e in inventory["workshops"]
                ],
            }
        else:
            result = inventory
            if no_components:
                result = {
                    **inventory,
                    "plans": _strip_components(inventory["plans"]),
                    "workshops": _strip_components(inventory["workshops"]),
                }

        message = _human_inventory(
            result, no_components=no_components, paths_only=paths_only
        )
        return result, message

    _run_command(ctx, "info", run)


@app.command("doctor")
def doctor_command(ctx: typer.Context) -> None:
    def run() -> tuple[dict[str, Any], str]:
        app_ctx = _context(ctx)
        workspace = discover_workspace(app_ctx)
        if workspace is None:
            result = {
                "healthy": False,
                "errors": ["planledger is not initialized."],
                "warnings": [],
            }
            return result, "healthy: false"
        result = doctor(workspace)
        summary = "healthy: true" if result["healthy"] else "healthy: false"
        errors = result.get("errors", [])
        warnings = result.get("warnings", [])
        if isinstance(errors, list) and errors:
            summary += "\n" + "\n".join(f"- {item}" for item in errors)
        if isinstance(warnings, list) and warnings:
            summary += "\n" + "\n".join(f"- {item}" for item in warnings)
        return result, summary

    _run_command(ctx, "doctor", run)


@plan_app.command("create")
def plan_create(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title", help="Plan title"),
    request: str | None = typer.Option(None, "--request", help="Inline request text"),
    request_file: Path | None = typer.Option(
        None,
        "--request-file",
        help="Request file; use '-' to read from standard input",
    ),
    request_stdin: bool = typer.Option(
        False,
        "--stdin",
        help="Read request text from standard input",
    ),
    status: PlanStatus = typer.Option("new", "--status", help="Initial status"),
    from_workshop: str | None = typer.Option(
        None, "--from-workshop", help="Create from shaped workshop"
    ),
    allow_unshaped: bool = typer.Option(
        False, "--allow-unshaped", help="Allow plan creation from an unshaped workshop"
    ),
    no_workshop_status_update: bool = typer.Option(
        False, "--no-workshop-status-update", help="Do not mark source workshop planned"
    ),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        if from_workshop is not None:
            created, workshop = create_plan_from_workshop(
                workspace,
                from_workshop,
                title=title,
                allow_unshaped=allow_unshaped,
                update_workshop_status=not no_workshop_status_update,
            )
            built = build_plan(workspace, created.plan_id)
            built["workshop_id"] = workshop.workshop_id
            built["workshop_ref"] = workshop_to_dict(
                workshop, ledger_code=workspace.ledger_code
            )["global_ref"]
            return built, _summary_message(built, "Created from workshop")
        request_text = read_input_text(request, request_file, stdin=request_stdin)
        created = create_plan(
            workspace,
            title=title,
            request=request_text,
            status=status,
        )
        built = build_plan(workspace, created.plan_id)
        return built, _summary_message(built, "Created")

    _run_command(ctx, "plan.create", run)


@plan_app.command("list")
def plan_list(
    ctx: typer.Context,
    status: PlanStatus | None = typer.Option(None, "--status", help="Filter by status"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        plans = [
            plan_to_dict(plan, ledger_code=workspace.ledger_code)
            for plan in list_plans(workspace, status=status)
        ]
        if not plans:
            return {"plans": []}, "No plans found."
        lines = [
            (
                f"{plan['plan_id']} {plan['title']} "
                f"[{plan['status']}] {version_label(int(plan['version']))}"
            )
            for plan in plans
        ]
        return {"plans": plans}, "\n".join(lines)

    _run_command(ctx, "plan.list", run)


@plan_app.command("activate")
def plan_activate(
    ctx: typer.Context,
    plan_id: str = typer.Argument(..., help="Plan id to activate"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, positional=plan_id)
        plan = activate_plan(workspace, resolved)
        result = plan_to_dict(plan, ledger_code=workspace.ledger_code)
        return result, f"Activated {resolved} ({plan.title})."

    _run_command(ctx, "plan.activate", run)


@plan_app.command("show")
def plan_show(
    ctx: typer.Context,
    plan_id: str | None = typer.Argument(None, help=ACTIVE_PLAN_HELP),
    plan: str | None = typer.Option(None, "--plan", help=PLAN_OVERRIDE_HELP),
    component: str | None = typer.Option(None, "--component", help="Component key"),
    rendered: bool = typer.Option(
        False,
        "--rendered",
        help="Print latest rendered Markdown",
    ),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, explicit=plan, positional=plan_id)
        plan_obj = load_plan(workspace, resolved)
        if component and rendered:
            raise PlanledgerError(
                "invalid_options",
                "Use either --component or --rendered, not both.",
            )
        result = plan_to_dict(plan_obj, ledger_code=workspace.ledger_code)
        if component is not None:
            component_spec(component)
            content = load_component_content(plan_obj, component)
            result["component"] = component
            result["content"] = content
            return result, content
        if rendered:
            latest = latest_rendered_path(plan_obj)
            if not latest.exists():
                raise PlanledgerError(
                    "not_found",
                    f"No rendered artifact exists for {resolved}.",
                )
            rendered_markdown = latest.read_text(encoding="utf-8")
            result["markdown"] = rendered_markdown
            return result, rendered_markdown
        return result, _human_plan_details(result)

    _run_command(ctx, "plan.show", run)


_VALID_PLAN_STATUS_ARGS: set[str] = {
    "new",
    "in_progress",
    "rework",
    "cancelled",
    "done",
}


def _parse_plan_status_args(
    args: list[str],
    *,
    plan_opt: str | None,
) -> tuple[str | None, PlanStatus]:
    """Parse the variadic ``plan status`` positional arguments.

    Accepts all of these shapes:

    - ``STATUS`` (active plan implied)
    - ``STATUS PLAN_ID``
    - ``PLAN_ID STATUS``

    The ``--plan`` option may supply the plan id for the ``STATUS`` and
    ``STATUS PLAN_ID`` shapes.
    """
    remediation = [
        "Run: planledger plan status done --reason REASON",
        "Run: planledger plan status PLAN_ID done --reason REASON",
        "Run: planledger plan status done --plan PLAN_ID --reason REASON",
    ]

    if len(args) == 1:
        only = args[0]
        if only not in _VALID_PLAN_STATUS_ARGS:
            raise PlanledgerError(
                "invalid_status_args",
                "Expected STATUS or PLAN_ID STATUS.",
                remediation=remediation,
                exit_code=2,
            )
        return plan_opt, cast("PlanStatus", only)

    if len(args) == 2:
        first, second = args
        first_is_status = first in _VALID_PLAN_STATUS_ARGS
        second_is_status = second in _VALID_PLAN_STATUS_ARGS

        if first_is_status and not second_is_status:
            selected_plan = plan_opt or second
            return selected_plan, cast("PlanStatus", first)

        if second_is_status and not first_is_status:
            selected_plan = plan_opt or first
            return selected_plan, cast("PlanStatus", second)

    raise PlanledgerError(
        "invalid_status_args",
        "Expected STATUS, PLAN_ID STATUS, or STATUS PLAN_ID.",
        remediation=remediation,
        exit_code=2,
    )


@plan_app.command("status")
def plan_status_command(
    ctx: typer.Context,
    args: list[str] = typer.Argument(
        ...,
        metavar="[PLAN_ID] STATUS",
        help="New status, optionally with a plan id.",
    ),
    plan_opt: str | None = typer.Option(None, "--plan", help=PLAN_OVERRIDE_HELP),
    reason: str = typer.Option(..., "--reason", help="Reason for the status change"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        parsed_plan, parsed_status = _parse_plan_status_args(args, plan_opt=plan_opt)
        resolved = resolve_plan_id(workspace, explicit=parsed_plan, positional=None)
        updated = set_plan_status(workspace, resolved, parsed_status, reason)
        built = build_plan(workspace, updated.plan_id)
        return built, _summary_message(built, "Updated")

    _run_command(ctx, "plan.status", run)


@plan_app.command("cancel")
def plan_cancel(
    ctx: typer.Context,
    plan_id: str | None = typer.Argument(None, help=ACTIVE_PLAN_HELP),
    plan_opt: str | None = typer.Option(None, "--plan", help=PLAN_OVERRIDE_HELP),
    reason: str = typer.Option(..., "--reason", help="Cancellation reason"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, explicit=plan_opt, positional=plan_id)
        updated = set_plan_status(workspace, resolved, "cancelled", reason)
        built = build_plan(workspace, updated.plan_id)
        return built, _summary_message(built, "Cancelled")

    _run_command(ctx, "plan.cancel", run)


@component_app.command("list")
def plan_component_list(
    ctx: typer.Context,
    plan_id: str | None = typer.Argument(None, help=ACTIVE_PLAN_HELP),
    plan_opt: str | None = typer.Option(None, "--plan", help=PLAN_OVERRIDE_HELP),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, explicit=plan_opt, positional=plan_id)
        plan_obj = load_plan(workspace, resolved)
        result = {
            "plan_id": resolved,
            "components": [
                {
                    "key": key,
                    "title": spec.title,
                    "path": spec.path,
                    "required": spec.required,
                    "order": spec.order,
                }
                for key, spec in sorted(
                    plan_obj.components.items(),
                    key=lambda item: (item[1].order, item[0]),
                )
            ],
        }
        components = result["components"]
        assert isinstance(components, list)
        message = "\n".join(
            f"{item['key']} -> {item['path']}"
            for item in components
            if isinstance(item, dict)
        )
        return result, message

    _run_command(ctx, "plan.component.list", run)


@component_app.command("show")
def plan_component_show(
    ctx: typer.Context,
    component: str = typer.Argument(..., help="Component key"),
    plan_opt: str | None = typer.Option(None, "--plan", help=ACTIVE_PLAN_HELP),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, explicit=plan_opt)
        plan_obj = load_plan(workspace, resolved)
        component_spec(component)
        content = load_component_content(plan_obj, component)
        return {
            "plan_id": resolved,
            "component": component,
            "content": content,
        }, content

    _run_command(ctx, "plan.component.show", run)


@component_app.command("set")
def plan_component_set(
    ctx: typer.Context,
    component: str = typer.Argument(..., help="Component key"),
    plan_opt: str | None = typer.Option(None, "--plan", help=ACTIVE_PLAN_HELP),
    text: str | None = typer.Option(None, "--text", help="Inline component content"),
    file: Path | None = typer.Option(
        None,
        "--file",
        help="Read component content from file; use '-' to read from standard input",
    ),
    stdin: bool = typer.Option(
        False,
        "--stdin",
        help="Read component content from standard input",
    ),
    reason: str | None = typer.Option(None, "--reason", help="Reason for the update"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override cancelled plan protection",
    ),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, explicit=plan_opt)
        content = read_input_text(text, file, stdin=stdin)
        updated = set_component(
            workspace,
            resolved,
            component,
            content,
            reason,
            force=force,
        )
        built = build_plan(workspace, updated.plan_id)
        return built, _summary_message(built, "Updated")

    _run_command(ctx, "plan.component.set", run)


@component_app.command("append")
def plan_component_append(
    ctx: typer.Context,
    component: str = typer.Argument(..., help="Component key"),
    plan_opt: str | None = typer.Option(None, "--plan", help=ACTIVE_PLAN_HELP),
    text: str | None = typer.Option(None, "--text", help="Inline component content"),
    file: Path | None = typer.Option(
        None,
        "--file",
        help="Read component content from file; use '-' to read from standard input",
    ),
    stdin: bool = typer.Option(
        False,
        "--stdin",
        help="Read component content from standard input",
    ),
    reason: str | None = typer.Option(None, "--reason", help="Reason for the update"),
    force: bool = typer.Option(
        False,
        "--force",
        help="Override cancelled plan protection",
    ),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, explicit=plan_opt)
        content = read_input_text(text, file, stdin=stdin)
        updated = append_component(
            workspace,
            resolved,
            component,
            content,
            reason,
            force=force,
        )
        built = build_plan(workspace, updated.plan_id)
        return built, _summary_message(built, "Updated")

    _run_command(ctx, "plan.component.append", run)


@plan_app.command("build")
def plan_build(
    ctx: typer.Context,
    plan_id: str | None = typer.Argument(None, help=ACTIVE_PLAN_HELP),
    plan_opt: str | None = typer.Option(None, "--plan", help=PLAN_OVERRIDE_HELP),
    out: Path | None = typer.Option(None, "--out", help="Write build output to path"),
    print_output: bool = typer.Option(False, "--print", help="Print rendered Markdown"),
    include_empty: bool = typer.Option(
        False,
        "--include-empty",
        help="Include empty optional sections",
    ),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, explicit=plan_opt, positional=plan_id)
        built = build_plan(workspace, resolved, out=out, include_empty=include_empty)
        message = (
            built["markdown"] if print_output else _summary_message(built, "Built")
        )
        return built, message

    _run_command(ctx, "plan.build", run)


@plan_app.command("export")
def plan_export(
    ctx: typer.Context,
    plan_id: str | None = typer.Argument(None, help=ACTIVE_PLAN_HELP),
    plan_opt: str | None = typer.Option(None, "--plan", help=PLAN_OVERRIDE_HELP),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Export path; defaults to WORKSPACE_ROOT/PLAN_ID.md",
    ),
    include_empty: bool = typer.Option(
        False,
        "--include-empty",
        help="Include empty optional sections",
    ),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, explicit=plan_opt, positional=plan_id)
        output_path = out or Path(f"{resolved}.md")
        if not output_path.is_absolute():
            output_path = workspace.root / output_path
        built = build_plan(
            workspace,
            resolved,
            out=output_path,
            include_empty=include_empty,
        )
        return built, f"Exported {resolved} -> {built['output_path']}"

    _run_command(ctx, "plan.export", run)


@plan_app.command("validate")
def plan_validate(
    ctx: typer.Context,
    plan_id: str | None = typer.Argument(None, help=ACTIVE_PLAN_HELP),
    plan_opt: str | None = typer.Option(None, "--plan", help=PLAN_OVERRIDE_HELP),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, explicit=plan_opt, positional=plan_id)
        plan_obj = load_plan(workspace, resolved)
        errors = validate_plan(plan_obj, for_done=plan_obj.status == "done")
        result = {
            "plan_id": resolved,
            "valid": not errors,
            "errors": errors,
        }
        if errors:
            return result, "\n".join(errors)
        return result, f"{resolved} is valid."

    _run_command(ctx, "plan.validate", run)


@plan_app.command("versions")
def plan_versions(
    ctx: typer.Context,
    plan_id: str | None = typer.Argument(None, help=ACTIVE_PLAN_HELP),
    plan_opt: str | None = typer.Option(None, "--plan", help=PLAN_OVERRIDE_HELP),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, explicit=plan_opt, positional=plan_id)
        plan_obj = load_plan(workspace, resolved)
        versions = list_versions(plan_obj)
        return {
            "plan_id": resolved,
            "versions": versions,
        }, "\n".join(versions) or "No versions."

    _run_command(ctx, "plan.versions", run)


@plan_app.command("diff")
def plan_diff(
    ctx: typer.Context,
    plan_id: str | None = typer.Argument(None, help=ACTIVE_PLAN_HELP),
    plan_opt: str | None = typer.Option(None, "--plan", help=PLAN_OVERRIDE_HELP),
    from_version: str = typer.Option(..., "--from", help="From version label"),
    to_version: str = typer.Option(..., "--to", help="To version label"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        resolved = resolve_plan_id(workspace, explicit=plan_opt, positional=plan_id)
        diff = diff_versions(workspace, resolved, from_version, to_version)
        return {
            "plan_id": resolved,
            "from": from_version,
            "to": to_version,
            "diff": diff,
        }, diff

    _run_command(ctx, "plan.diff", run)


@plan_app.command("apply")
def plan_apply(
    ctx: typer.Context,
    file: Path = typer.Option(..., "--file", help="Structured plan bundle file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Validate without writing"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        bundle = load_bundle(file)
        result = apply_structured_plan_bundle(workspace, bundle, dry_run=dry_run)
        if dry_run:
            return result, "Bundle dry-run passed."
        plan = result["plan"]
        assert isinstance(plan, dict)
        return result, _summary_message(plan, "Applied")

    _run_command(ctx, "plan.apply", run)


@app.command("next-action")
def next_action(
    ctx: typer.Context,
    plan_id: str | None = typer.Argument(None, help="Plan id"),
    plan_opt: str | None = typer.Option(None, "--plan", help=PLAN_OVERRIDE_HELP),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit JSON envelope. Equivalent to root --json for this command.",
    ),
) -> None:
    if json_output:
        # Agents naturally place flags after the subcommand. Accept the
        # command-local --json form and force JSON output for this run.
        ctx.obj = replace(_context(ctx), json_output=True)
    selected_plan = plan_opt if plan_opt is not None else plan_id

    def run() -> tuple[dict[str, Any], str]:
        app_ctx = _context(ctx)
        workspace = discover_workspace(app_ctx)
        result = compute_next_action(workspace, selected_plan)
        lines = [f"next_item: {result['next_item']}"]
        if result.get("plan_id"):
            lines.append(f"plan_id: {result['plan_id']}")
        if result.get("status"):
            lines.append(f"status: {result['status']}")
        if result.get("next_command"):
            lines.append(f"next_command: {result['next_command']}")
        if result.get("question"):
            lines.append(f"question: {result['question']}")
        if result.get("agent_instruction"):
            lines.append(f"agent_instruction: {result['agent_instruction']}")
        profile = result.get("prompt_profile")
        if isinstance(profile, dict) and profile.get("enabled"):
            lines.append(f"prompt_profile: {profile['name']} enabled")
            if profile.get("active"):
                lines.append("prompt_profile_active: true")
        for blocker in result.get("blockers", []):
            lines.append(f"blocker: {blocker}")
        for error in result.get("validation_errors", []):
            lines.append(f"validation_error: {error}")
        return result, "\n".join(lines)

    _run_command(ctx, "next-action", run)


def _summary_workshop_message(workshop: dict[str, Any], verb: str) -> str:
    return f"{verb} {workshop['workshop_id']} ({workshop['status']}, {version_label(int(workshop['version']))}) -> {workshop['latest_rendered_path']}"


@workshop_app.command("create")
def workshop_create(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title"),
    request: str | None = typer.Option(None, "--request"),
    request_file: Path | None = typer.Option(None, "--request-file"),
    request_stdin: bool = typer.Option(False, "--stdin"),
    status: str = typer.Option("new", "--status"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        text = read_input_text(request, request_file, stdin=request_stdin)
        created = create_workshop(workspace, title, text, status)
        built = build_workshop(workspace, created.workshop_id)
        return built, _summary_workshop_message(built, "Created")

    _run_command(ctx, "workshop.create", run)


@workshop_app.command("list")
def workshop_list(
    ctx: typer.Context, status: str | None = typer.Option(None, "--status")
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        workshops = [
            workshop_to_dict(w, ledger_code=workspace.ledger_code)
            for w in list_workshops(workspace, status=status)
        ]
        return {
            "workshops": workshops
        }, "No workshops found." if not workshops else "\n".join(
            f"{w['workshop_id']} {w['title']} [{w['status']}] {version_label(int(w['version']))}"
            for w in workshops
        )

    _run_command(ctx, "workshop.list", run)


@workshop_app.command("activate")
def workshop_activate(ctx: typer.Context, workshop_id: str) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        w = activate_workshop(workspace, workshop_id)
        payload = workshop_to_dict(w, ledger_code=workspace.ledger_code)
        return payload, f"Activated {w.workshop_id}"

    _run_command(ctx, "workshop.activate", run)


@workshop_app.command("show")
def workshop_show(
    ctx: typer.Context,
    positional: str | None = typer.Argument(None),
    workshop: str | None = typer.Option(None, "--workshop"),
    component: str | None = typer.Option(None, "--component"),
    rendered: bool = typer.Option(False, "--rendered"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop, positional)
        w = load_workshop(workspace, wid)
        if component is not None:
            content = load_workshop_component_content(w, component)
            return {
                "workshop_id": w.workshop_id,
                "component": component,
                "content": content,
            }, content
        if rendered:
            path = latest_rendered_workshop_path(w)
            if not path.exists():
                build_workshop(workspace, w.workshop_id)
            content = path.read_text(encoding="utf-8")
            return {
                "workshop_id": w.workshop_id,
                "rendered_path": str(path),
                "content": content,
            }, content
        payload = workshop_to_dict(w, ledger_code=workspace.ledger_code)
        return (
            payload,
            f"{payload['workshop_id']}\ntitle: {payload['title']}\nstatus: {payload['status']}\nversion: {version_label(int(payload['version']))}\npath: {payload['path']}\nrendered: {payload['latest_rendered_path']}",
        )

    _run_command(ctx, "workshop.show", run)


@workshop_app.command("status")
def workshop_status(
    ctx: typer.Context,
    status: str,
    positional: str | None = typer.Argument(None),
    workshop: str | None = typer.Option(None, "--workshop"),
    reason: str = typer.Option(..., "--reason"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop, positional)
        updated = set_workshop_status(workspace, wid, status, reason, force=force)
        built = build_workshop(workspace, updated.workshop_id)
        return built, _summary_workshop_message(built, "Updated")

    _run_command(ctx, "workshop.status", run)


@workshop_app.command("cancel")
def workshop_cancel(
    ctx: typer.Context,
    positional: str | None = typer.Argument(None),
    workshop: str | None = typer.Option(None, "--workshop"),
    reason: str = typer.Option(..., "--reason"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop, positional)
        updated = set_workshop_status(workspace, wid, "cancelled", reason)
        payload = workshop_to_dict(updated, ledger_code=workspace.ledger_code)
        return payload, f"Cancelled {wid}"

    _run_command(ctx, "workshop.cancel", run)


@workshop_app.command("validate")
def workshop_validate(
    ctx: typer.Context,
    positional: str | None = typer.Argument(None),
    workshop: str | None = typer.Option(None, "--workshop"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop, positional)
        w = load_workshop(workspace, wid)
        errors = validate_workshop(w, for_shaped=True)
        return (
            {"workshop_id": wid, "valid": not errors, "errors": errors},
            "Workshop validation passed."
            if not errors
            else "Workshop validation failed:\n" + "\n".join(f"- {e}" for e in errors),
        )

    _run_command(ctx, "workshop.validate", run)


@workshop_app.command("build")
def workshop_build(
    ctx: typer.Context,
    positional: str | None = typer.Argument(None),
    workshop: str | None = typer.Option(None, "--workshop"),
    out: Path | None = typer.Option(None, "--out"),
    print_output: bool = typer.Option(False, "--print"),
    include_empty: bool = typer.Option(False, "--include-empty"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop, positional)
        built = build_workshop(workspace, wid, out=out, include_empty=include_empty)
        return built, built["markdown"] if print_output else _summary_workshop_message(
            built, "Built"
        )

    _run_command(ctx, "workshop.build", run)


@workshop_app.command("export")
def workshop_export(
    ctx: typer.Context,
    positional: str | None = typer.Argument(None),
    workshop: str | None = typer.Option(None, "--workshop"),
    out: Path | None = typer.Option(None, "--out"),
    include_empty: bool = typer.Option(False, "--include-empty"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop, positional)
        target = out or (workspace.root / f"{wid}.md")
        built = build_workshop(workspace, wid, out=target, include_empty=include_empty)
        return built, f"Exported {wid} -> {target}"

    _run_command(ctx, "workshop.export", run)


@workshop_app.command("versions")
def workshop_versions(
    ctx: typer.Context,
    positional: str | None = typer.Argument(None),
    workshop: str | None = typer.Option(None, "--workshop"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop, positional)
        w = load_workshop(workspace, wid)
        versions = list_workshop_versions(w)
        return {"workshop_id": wid, "versions": versions}, "\n".join(
            versions
        ) if versions else "No versions."

    _run_command(ctx, "workshop.versions", run)


@workshop_app.command("diff")
def workshop_diff(
    ctx: typer.Context,
    positional: str | None = typer.Argument(None),
    workshop: str | None = typer.Option(None, "--workshop"),
    from_version: str = typer.Option(..., "--from"),
    to_version: str = typer.Option(..., "--to"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop, positional)
        diff = diff_workshop_versions(workspace, wid, from_version, to_version)
        return {"workshop_id": wid, "diff": diff}, diff

    _run_command(ctx, "workshop.diff", run)


@workshop_component_app.command("list")
def workshop_component_list(
    ctx: typer.Context,
    positional: str | None = typer.Argument(None),
    workshop: str | None = typer.Option(None, "--workshop"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop, positional)
        w = load_workshop(workspace, wid)
        components = workshop_to_dict(w, ledger_code=workspace.ledger_code)[
            "components"
        ]
        return {"workshop_id": wid, "components": components}, "\n".join(
            components.keys()
        )

    _run_command(ctx, "workshop.component.list", run)


@workshop_component_app.command("show")
def workshop_component_show(
    ctx: typer.Context,
    component: str,
    workshop: str | None = typer.Option(None, "--workshop"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop)
        w = load_workshop(workspace, wid)
        content = load_workshop_component_content(w, component)
        return {"workshop_id": wid, "component": component, "content": content}, content

    _run_command(ctx, "workshop.component.show", run)


@workshop_component_app.command("set")
def workshop_component_set(
    ctx: typer.Context,
    component: str,
    workshop: str | None = typer.Option(None, "--workshop"),
    text: str | None = typer.Option(None, "--text"),
    file: Path | None = typer.Option(None, "--file"),
    stdin: bool = typer.Option(False, "--stdin"),
    reason: str | None = typer.Option(None, "--reason"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop)
        content = read_input_text(text, file, stdin=stdin)
        updated = set_workshop_component(
            workspace, wid, component, content, reason, force=force
        )
        built = build_workshop(workspace, updated.workshop_id)
        return built, _summary_workshop_message(built, "Updated")

    _run_command(ctx, "workshop.component.set", run)


@workshop_component_app.command("append")
def workshop_component_append(
    ctx: typer.Context,
    component: str,
    workshop: str | None = typer.Option(None, "--workshop"),
    text: str | None = typer.Option(None, "--text"),
    file: Path | None = typer.Option(None, "--file"),
    stdin: bool = typer.Option(False, "--stdin"),
    reason: str | None = typer.Option(None, "--reason"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        wid = resolve_workshop_id(workspace, workshop)
        content = read_input_text(text, file, stdin=stdin)
        updated = append_workshop_component(
            workspace, wid, component, content, reason, force=force
        )
        built = build_workshop(workspace, updated.workshop_id)
        return built, _summary_workshop_message(built, "Updated")

    _run_command(ctx, "workshop.component.append", run)


@workshop_app.command("apply")
def workshop_apply(
    ctx: typer.Context,
    file: Path = typer.Option(..., "--file"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    def run() -> tuple[dict[str, Any], str]:
        workspace = _require_workspace(ctx)
        bundle = load_bundle(file)
        result = apply_structured_workshop_bundle(workspace, bundle, dry_run=dry_run)
        return result, json.dumps(result, indent=2, default=str)

    _run_command(ctx, "workshop.apply", run)
