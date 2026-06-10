from __future__ import annotations

import copy
import hashlib
import shutil
import sys
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

import yaml

from planledger.errors import PlanledgerError
from planledger.guardrails import validate_handoff_contents
from planledger.models import AppContext, ComponentSpec, Plan, PlanStatus, Workspace

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


PLANLEDGER_CONFIG_FILENAMES: tuple[str, str] = ("planledger.toml", ".planledger.toml")
DEFAULT_PLANLEDGER_CONFIG_FILENAME = "planledger.toml"
DEFAULT_PLANLEDGER_DIR = ".planledger"
STORAGE_FILENAME = "storage.yaml"
VALID_STATUSES: set[PlanStatus] = {
    "new",
    "in_progress",
    "rework",
    "cancelled",
    "done",
}
VALID_TRANSITIONS: dict[PlanStatus, set[PlanStatus]] = {
    "new": {"in_progress", "rework", "cancelled", "done"},
    "in_progress": {"rework", "cancelled", "done"},
    "rework": {"in_progress", "cancelled", "done"},
    "done": {"rework"},
    "cancelled": set(),
}
COMPONENT_DEFINITIONS: tuple[tuple[str, str, str, int, bool], ...] = (
    ("request", "components/00-request.md", "Original request", 0, True),
    ("summary", "components/10-executive-verdict.md", "Executive verdict", 10, True),
    (
        "context",
        "components/20-context.md",
        "Repository context and evidence",
        20,
        True,
    ),
    ("open_questions", "components/30-open-questions.md", "Open questions", 30, False),
    ("assumptions", "components/40-assumptions.md", "Assumptions", 40, False),
    ("approach", "components/50-approach.md", "Proposed approach", 50, True),
    (
        "todo_items",
        "components/60-todo-items.md",
        "Todo items",
        60,
        True,
    ),
    ("target_files", "components/70-target-files.md", "Target files", 70, True),
    ("validation", "components/80-validation.md", "Validation plan", 80, True),
    ("risks", "components/90-risks.md", "Risks and mitigations", 90, True),
    ("rollback", "components/95-rollback.md", "Rollback / repair", 95, False),
    ("notes", "components/99-notes.md", "Notes", 99, False),
)


def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def version_label(version: int) -> str:
    return f"v{version:04d}"


def default_component_specs() -> dict[str, ComponentSpec]:
    return {
        key: ComponentSpec(
            key=key,
            path=path,
            title=title,
            order=order,
            required=required,
        )
        for key, path, title, order, required in COMPONENT_DEFINITIONS
    }


def ordered_component_keys(
    components: dict[str, ComponentSpec] | None = None,
) -> list[str]:
    selected = components or default_component_specs()
    return [
        spec.key
        for spec in sorted(selected.values(), key=lambda item: (item.order, item.key))
    ]


def component_spec(component: str) -> ComponentSpec:
    specs = default_component_specs()
    try:
        return specs[component]
    except KeyError as exc:
        raise PlanledgerError(
            "invalid_component",
            f"Unknown component key {component!r}.",
            remediation=[
                "Use one of: " + ", ".join(ordered_component_keys(specs)),
            ],
        ) from exc


def read_input_text(
    text: str | None,
    file_path: Path | None,
    *,
    stdin: bool = False,
) -> str:
    selected_sources = sum(
        (
            text is not None,
            file_path is not None,
            stdin,
        )
    )
    if selected_sources == 0:
        raise PlanledgerError(
            "missing_input",
            "Provide exactly one of --text, --file, or --stdin.",
        )
    if selected_sources > 1:
        raise PlanledgerError(
            "invalid_options",
            "Use exactly one of --text, --file, or --stdin.",
        )
    if stdin:
        return sys.stdin.read()
    if file_path is not None:
        if file_path.as_posix() == "-":
            return sys.stdin.read()
        try:
            return file_path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise PlanledgerError(
                "not_found",
                f"Input file does not exist: {file_path}",
            ) from exc
    assert text is not None
    return text


def workspace_root_from_context(app_ctx: AppContext) -> Path:
    candidate = app_ctx.root or app_ctx.cwd or Path.cwd()
    return candidate.resolve()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    _atomic_write(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PlanledgerError(
            "not_found",
            f"Required file does not exist: {path}",
        ) from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise PlanledgerError(
            "invalid_yaml",
            f"Expected a mapping in {path}.",
        )
    return loaded


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            loaded = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise PlanledgerError(
            "not_found",
            f"Config file does not exist: {path}",
        ) from exc
    if not isinstance(loaded, dict):
        raise PlanledgerError(
            "invalid_config",
            f"Expected a table mapping in {path}.",
        )
    return loaded


def _find_config(start: Path) -> tuple[Path, Path] | None:
    for candidate in (start, *start.parents):
        for name in PLANLEDGER_CONFIG_FILENAMES:
            config_path = candidate / name
            if config_path.exists():
                return candidate, config_path
    return None


def _resolve_planledger_dir(root: Path, configured_dir: str) -> Path:
    configured_path = Path(configured_dir).expanduser()
    if configured_path.is_absolute():
        return configured_path.resolve()
    return (root / configured_path).resolve()


def discover_workspace(app_ctx: AppContext) -> Workspace | None:
    start = workspace_root_from_context(app_ctx)
    found = _find_config(start)
    if found is None:
        return None
    root, config_path = found
    config = _load_toml(config_path)
    storage_config = config.get("storage", {})
    planledger_dir_name = DEFAULT_PLANLEDGER_DIR
    if isinstance(storage_config, dict):
        configured_dir = storage_config.get("planledger_dir")
        if isinstance(configured_dir, str) and configured_dir.strip():
            planledger_dir_name = configured_dir.strip()
    planledger_dir = _resolve_planledger_dir(root, planledger_dir_name)
    return Workspace(
        root=root,
        config_path=config_path,
        planledger_dir=planledger_dir,
        storage_path=planledger_dir / STORAGE_FILENAME,
        config=config,
    )


def load_workspace(app_ctx: AppContext) -> Workspace:
    workspace = discover_workspace(app_ctx)
    if workspace is None:
        raise PlanledgerError(
            "workspace_not_initialized",
            "planledger is not initialized in this workspace.",
            remediation=[
                "Run: planledger init",
            ],
        )
    return workspace


def plans_dir(workspace: Workspace) -> Path:
    return workspace.planledger_dir / "plans"


def plan_dir(workspace: Workspace, plan_id: str) -> Path:
    return plans_dir(workspace) / plan_id


def plan_metadata_path_from_dir(path: Path) -> Path:
    return path / "plan.yaml"


def plan_metadata_path(workspace: Workspace, plan_id: str) -> Path:
    return plan_metadata_path_from_dir(plan_dir(workspace, plan_id))


def rendered_dir(plan: Plan) -> Path:
    return plan.path / "rendered"


def latest_rendered_path(plan: Plan) -> Path:
    return rendered_dir(plan) / "latest.md"


def versioned_rendered_path(plan: Plan, version: int | None = None) -> Path:
    selected_version = version if version is not None else plan.version
    return rendered_dir(plan) / f"{plan.plan_id}-{version_label(selected_version)}.md"


def versions_dir(plan: Plan) -> Path:
    return plan.path / "versions"


def version_snapshot_dir(plan: Plan, version: int) -> Path:
    return versions_dir(plan) / version_label(version)


def storage_data(workspace: Workspace) -> dict[str, Any]:
    return _load_yaml(workspace.storage_path)


def save_storage_data(workspace: Workspace, data: dict[str, Any]) -> None:
    _write_yaml(workspace.storage_path, data)


def preview_plan_id(workspace: Workspace) -> str:
    data = storage_data(workspace)
    next_plan_id = int(data.get("next_plan_id", 1))
    return f"plan-{next_plan_id:04d}"


def allocate_plan_id(workspace: Workspace) -> str:
    data = storage_data(workspace)
    next_plan_id = int(data.get("next_plan_id", 1))
    plan_id = f"plan-{next_plan_id:04d}"
    data["next_plan_id"] = next_plan_id + 1
    data["updated_at"] = now_iso()
    save_storage_data(workspace, data)
    return plan_id

def get_active_plan_id(workspace: Workspace) -> str | None:
    data = storage_data(workspace)
    return data.get("active_plan_id")


def set_active_plan_id(workspace: Workspace, plan_id: str) -> None:
    data = storage_data(workspace)
    data["active_plan_id"] = plan_id
    data["updated_at"] = now_iso()
    save_storage_data(workspace, data)


def activate_plan(workspace: Workspace, plan_id: str) -> Plan:
    plan = load_plan(workspace, plan_id)
    set_active_plan_id(workspace, plan_id)
    return plan


def resolve_plan_id(
    workspace: Workspace,
    explicit: str | None = None,
    positional: str | None = None,
) -> str:
    """Resolve plan id from --plan, positional arg, or active plan."""
    if explicit is not None:
        return explicit
    if positional is not None:
        return positional
    active = get_active_plan_id(workspace)
    if active is not None:
        return active
    raise PlanledgerError(
        "no_active_plan",
        "No active plan and no plan selector provided.",
        remediation=[
            "Run: planledger plan create --title TITLE --request REQUEST",
            "Or: planledger plan activate PLAN_ID",
        ],
    )


def initialize_project(
    root: Path,
    project_name: str,
    planledger_dir: str = DEFAULT_PLANLEDGER_DIR,
    config_filename: str = DEFAULT_PLANLEDGER_CONFIG_FILENAME,
) -> Workspace:
    resolved_root = root.resolve()
    if config_filename not in PLANLEDGER_CONFIG_FILENAMES:
        raise PlanledgerError(
            "invalid_config",
            f"Unsupported config filename {config_filename!r}.",
        )
    for filename in PLANLEDGER_CONFIG_FILENAMES:
        if (resolved_root / filename).exists():
            raise PlanledgerError(
                "already_initialized",
                f"Workspace already contains {filename}.",
            )
    planledger_path = _resolve_planledger_dir(resolved_root, planledger_dir)
    if planledger_path.exists():
        raise PlanledgerError(
            "already_initialized",
            f"Workspace already contains {planledger_path}.",
        )
    project_uuid = str(uuid4())
    timestamp = now_iso()
    config: dict[str, Any] = {
        "project": {
            "name": project_name,
            "uuid": project_uuid,
        },
        "storage": {
            "planledger_dir": planledger_dir,
        },
    }
    storage: dict[str, Any] = {
        "schema_version": 2,
        "project_uuid": project_uuid,
        "next_plan_id": 1,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    _write_yaml(planledger_path / STORAGE_FILENAME, storage)
    (planledger_path / "plans").mkdir(parents=True, exist_ok=True)
    _atomic_write(
        resolved_root / config_filename,
        _toml_dump(config),
    )
    return Workspace(
        root=resolved_root,
        config_path=resolved_root / config_filename,
        planledger_dir=planledger_path,
        storage_path=planledger_path / STORAGE_FILENAME,
        config=config,
    )


def _toml_dump(data: dict[str, Any]) -> str:
    lines: list[str] = []
    project = data.get("project", {})
    if isinstance(project, dict):
        lines.append("[project]")
        for key in ("name", "uuid"):
            value = project.get(key)
            if isinstance(value, str):
                lines.append(f'{key} = "{value}"')
        lines.append("")
    storage = data.get("storage", {})
    if isinstance(storage, dict):
        lines.append("[storage]")
        planledger_dir = storage.get("planledger_dir")
        if isinstance(planledger_dir, str):
            lines.append(f'planledger_dir = "{planledger_dir}"')
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _hash_text(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _plan_from_metadata(plan_path: Path, metadata: dict[str, Any]) -> Plan:
    raw_components = metadata.get("components")
    if not isinstance(raw_components, dict):
        raise PlanledgerError(
            "invalid_plan",
            f"Plan metadata at {plan_path} is missing a valid components mapping.",
        )
    components: dict[str, ComponentSpec] = {}
    for key, raw_spec in raw_components.items():
        if not isinstance(raw_spec, dict):
            raise PlanledgerError(
                "invalid_plan",
                f"Component metadata for {key!r} must be a mapping.",
            )
        path = raw_spec.get("path")
        title = raw_spec.get("title")
        order = raw_spec.get("order")
        required = raw_spec.get("required")
        if not isinstance(path, str) or not isinstance(title, str):
            raise PlanledgerError(
                "invalid_plan",
                f"Component {key!r} is missing path/title metadata.",
            )
        if not isinstance(order, int) or not isinstance(required, bool):
            raise PlanledgerError(
                "invalid_plan",
                f"Component {key!r} has invalid order/required metadata.",
            )
        sha256 = raw_spec.get("sha256")
        components[key] = ComponentSpec(
            key=key,
            path=path,
            title=title,
            order=order,
            required=required,
            sha256=str(sha256) if isinstance(sha256, str) else None,
        )
    plan_id = str(metadata.get("id") or plan_path.name)
    return Plan(
        plan_id=plan_id,
        path=plan_path,
        metadata=metadata,
        components=components,
    )


def _component_metadata(spec: ComponentSpec) -> dict[str, Any]:
    data: dict[str, Any] = {
        "path": spec.path,
        "required": spec.required,
        "order": spec.order,
        "title": spec.title,
    }
    if spec.sha256 is not None:
        data["sha256"] = spec.sha256
    return data


def _write_plan_metadata(plan: Plan) -> None:
    plan.metadata["components"] = {
        key: _component_metadata(spec)
        for key, spec in sorted(
            plan.components.items(),
            key=lambda item: (item[1].order, item[0]),
        )
    }
    _write_yaml(plan_metadata_path_from_dir(plan.path), plan.metadata)


def load_plan(workspace: Workspace, plan_id: str) -> Plan:
    target_dir = plan_dir(workspace, plan_id)
    if not target_dir.exists():
        raise PlanledgerError(
            "not_found",
            f"Plan {plan_id} does not exist.",
        )
    return _plan_from_metadata(
        target_dir,
        _load_yaml(plan_metadata_path(workspace, plan_id)),
    )


def list_plans(workspace: Workspace, status: str | None = None) -> list[Plan]:
    listed: list[Plan] = []
    target_dir = plans_dir(workspace)
    if not target_dir.exists():
        return listed
    for candidate in sorted(target_dir.iterdir()):
        if not candidate.is_dir():
            continue
        metadata_path = plan_metadata_path_from_dir(candidate)
        if not metadata_path.exists():
            continue
        plan = _plan_from_metadata(candidate, _load_yaml(metadata_path))
        if status is None or plan.status == status:
            listed.append(plan)
    return listed


def load_component_content(plan: Plan, component: str) -> str:
    spec = plan.components.get(component)
    if spec is None:
        component_spec(component)
        raise AssertionError("unreachable")
    path = plan.path / spec.path
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PlanledgerError(
            "not_found",
            f"Component file does not exist: {path}",
        ) from exc


def load_component_contents(plan: Plan) -> dict[str, str]:
    return {
        key: load_component_content(plan, key)
        for key in ordered_component_keys(plan.components)
    }


def _validate_status(status: str) -> PlanStatus:
    if status not in VALID_STATUSES:
        raise PlanledgerError(
            "invalid_status",
            f"Invalid status {status!r}.",
            remediation=[
                "Use one of: " + ", ".join(sorted(VALID_STATUSES)),
            ],
        )
    return status


def _validate_transition(current: PlanStatus, next_status: PlanStatus) -> None:
    if current == next_status:
        return
    if next_status not in VALID_TRANSITIONS[current]:
        raise PlanledgerError(
            "invalid_status_transition",
            f"Cannot change plan status from {current!r} to {next_status!r}.",
        )


def _required_component_content_errors(
    plan: Plan,
    proposed_contents: dict[str, str],
) -> list[str]:
    errors: list[str] = []
    for key in ordered_component_keys(plan.components):
        spec = plan.components[key]
        if spec.required and not proposed_contents.get(key, "").strip():
            errors.append(f"Required component {key!r} must be non-empty.")
    return errors


def validate_plan(plan: Plan, *, for_done: bool = False) -> list[str]:
    errors: list[str] = []
    try:
        _validate_status(plan.status)
    except PlanledgerError as exc:
        errors.append(exc.message)
    contents = load_component_contents(plan)
    default_specs = default_component_specs()
    for key in default_specs:
        if key not in plan.components:
            errors.append(f"Missing component metadata for {key!r}.")
    for key in plan.components:
        if key not in default_specs:
            errors.append(f"Unknown component metadata for {key!r}.")
    if for_done:
        errors.extend(_required_component_content_errors(plan, contents))
        errors.extend(validate_handoff_contents(contents))
    return errors


def create_plan(
    workspace: Workspace,
    title: str,
    request: str,
    status: str = "new",
    *,
    components: dict[str, str] | None = None,
) -> Plan:
    if not title.strip():
        raise PlanledgerError("invalid_title", "Plan title must not be empty.")
    validated_status = _validate_status(status)
    component_values = components or {}
    for key in component_values:
        component_spec(key)
    plan_id = allocate_plan_id(workspace)
    created_at = now_iso()
    target_dir = plan_dir(workspace, plan_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    specs = default_component_specs()
    contents = {key: "" for key in specs}
    contents["request"] = request
    contents.update(component_values)
    if validated_status == "done":
        provisional_plan = Plan(
            plan_id=plan_id,
            path=target_dir,
            metadata={"status": validated_status},
            components=copy.deepcopy(specs),
        )
        done_errors = _required_component_content_errors(provisional_plan, contents)
        done_errors.extend(validate_handoff_contents(contents))
        if done_errors:
            raise PlanledgerError(
                "invalid_plan",
                "Cannot create a done plan: validation failed.",
                remediation=done_errors,
            )
    for key in ordered_component_keys(specs):
        spec = specs[key]
        content = contents[key]
        spec.sha256 = _hash_text(content)
        _atomic_write(target_dir / spec.path, content)
    metadata: dict[str, Any] = {
        "schema_version": 2,
        "id": plan_id,
        "type": "plan",
        "title": title,
        "status": validated_status,
        "version": 1,
        "created_at": created_at,
        "updated_at": created_at,
        "request": {
            "source": "human",
            "prompt_file": "components/00-request.md",
        },
        "components": {
            key: _component_metadata(spec)
            for key, spec in sorted(
                specs.items(),
                key=lambda item: (item[1].order, item[0]),
            )
        },
        "history": [
            {
                "version": 1,
                "status": validated_status,
                "created_at": created_at,
                "reason": "Initial plan",
            }
        ],
    }
    plan = Plan(plan_id=plan_id, path=target_dir, metadata=metadata, components=specs)
    _write_plan_metadata(plan)
    snapshot_version(plan)
    set_active_plan_id(workspace, plan_id)
    return load_plan(workspace, plan_id)


def _append_text(current: str, addition: str) -> str:
    if not current:
        return addition
    if not addition:
        return current
    separator = (
        "" if current.endswith(("\n", "\r")) or addition.startswith("\n") else "\n"
    )
    return f"{current}{separator}{addition}"


def _default_reason(
    plan: Plan,
    changed_keys: Iterable[str],
    status: PlanStatus,
    status_changed: bool,
) -> str:
    keys = list(changed_keys)
    if status_changed and keys:
        return "Updated plan status and components."
    if status_changed:
        return f"Changed status to {status}."
    if len(keys) == 1:
        return f"Updated {keys[0]} component."
    return "Updated plan components."


def apply_plan_mutations(
    workspace: Workspace,
    plan_id: str,
    *,
    component_updates: dict[str, str] | None = None,
    append_components: set[str] | None = None,
    status: str | None = None,
    reason: str | None = None,
    force: bool = False,
) -> Plan:
    plan = load_plan(workspace, plan_id)
    updates = component_updates or {}
    append_keys = append_components or set()
    for key in updates:
        component_spec(key)
    if plan.status == "cancelled" and (updates or status is not None) and not force:
        raise PlanledgerError(
            "cancelled_plan",
            f"Plan {plan.plan_id} is cancelled and cannot be edited.",
            remediation=[
                "Use --force only when you intentionally need "
                "to override the terminal state.",
            ],
        )
    current_contents = load_component_contents(plan)
    next_contents = dict(current_contents)
    changed_keys: list[str] = []
    for key, value in updates.items():
        new_content = (
            _append_text(current_contents[key], value) if key in append_keys else value
        )
        if new_content != current_contents[key]:
            next_contents[key] = new_content
            changed_keys.append(key)
    next_status = plan.status
    status_changed = False
    if status is not None:
        validated_status = _validate_status(status)
        _validate_transition(plan.status, validated_status)
        if validated_status != plan.status:
            next_status = validated_status
            status_changed = True
    if next_status == "done":
        errors = _required_component_content_errors(plan, next_contents)
        errors.extend(validate_handoff_contents(next_contents))
        if errors:
            raise PlanledgerError(
                "invalid_plan",
                "Cannot set plan status to done: validation failed.",
                remediation=errors,
            )
    if not changed_keys and not status_changed:
        return plan
    timestamp = now_iso()
    for key in changed_keys:
        spec = plan.components[key]
        spec.sha256 = _hash_text(next_contents[key])
        _atomic_write(plan.path / spec.path, next_contents[key])
    plan.metadata["status"] = next_status
    plan.metadata["version"] = plan.version + 1
    plan.metadata["updated_at"] = timestamp
    history = plan.metadata.setdefault("history", [])
    if not isinstance(history, list):
        raise PlanledgerError(
            "invalid_plan",
            f"Plan {plan.plan_id} has invalid history metadata.",
        )
    history.append(
        {
            "version": plan.metadata["version"],
            "status": next_status,
            "created_at": timestamp,
            "reason": reason.strip()
            if isinstance(reason, str) and reason.strip()
            else _default_reason(plan, changed_keys, next_status, status_changed),
        }
    )
    _write_plan_metadata(plan)
    snapshot_version(plan)
    return load_plan(workspace, plan_id)


def set_component(
    workspace: Workspace,
    plan_id: str,
    component: str,
    content: str,
    reason: str | None = None,
    *,
    force: bool = False,
) -> Plan:
    return apply_plan_mutations(
        workspace,
        plan_id,
        component_updates={component: content},
        reason=reason,
        force=force,
    )


def append_component(
    workspace: Workspace,
    plan_id: str,
    component: str,
    content: str,
    reason: str | None = None,
    *,
    force: bool = False,
) -> Plan:
    return apply_plan_mutations(
        workspace,
        plan_id,
        component_updates={component: content},
        append_components={component},
        reason=reason,
        force=force,
    )


def set_plan_status(
    workspace: Workspace,
    plan_id: str,
    status: str,
    reason: str,
    *,
    force: bool = False,
) -> Plan:
    if not reason.strip():
        raise PlanledgerError(
            "missing_reason",
            "Status changes require --reason.",
        )
    return apply_plan_mutations(
        workspace,
        plan_id,
        status=status,
        reason=reason,
        force=force,
    )


def snapshot_version(plan: Plan) -> Path:
    target = version_snapshot_dir(plan, plan.version)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(plan_metadata_path_from_dir(plan.path), target / "plan.yaml")
    shutil.copytree(plan.path / "components", target / "components")
    manifest = {
        "plan_id": plan.plan_id,
        "version": plan.version,
        "status": plan.status,
        "generated_at": now_iso(),
        "components": {
            key: {
                "path": spec.path,
                "sha256": spec.sha256,
            }
            for key, spec in sorted(
                plan.components.items(),
                key=lambda item: (item[1].order, item[0]),
            )
        },
    }
    _write_yaml(target / "manifest.yaml", manifest)
    return target


def parse_version(value: str) -> int:
    normalized = value.strip()
    if normalized.startswith("v"):
        normalized = normalized[1:]
    try:
        parsed = int(normalized)
    except ValueError as exc:
        raise PlanledgerError(
            "invalid_version",
            f"Invalid version reference {value!r}.",
        ) from exc
    if parsed <= 0:
        raise PlanledgerError(
            "invalid_version",
            f"Invalid version reference {value!r}.",
        )
    return parsed


def list_versions(plan: Plan) -> list[str]:
    target_dir = versions_dir(plan)
    if not target_dir.exists():
        return []
    versions = [item.name for item in sorted(target_dir.iterdir()) if item.is_dir()]
    return versions


def diff_versions(
    workspace: Workspace,
    plan_id: str,
    from_version: str,
    to_version: str,
) -> str:
    plan = load_plan(workspace, plan_id)
    from_dir = version_snapshot_dir(plan, parse_version(from_version))
    to_dir = version_snapshot_dir(plan, parse_version(to_version))
    if not from_dir.exists():
        raise PlanledgerError(
            "not_found",
            f"Snapshot {from_version} does not exist for {plan_id}.",
        )
    if not to_dir.exists():
        raise PlanledgerError(
            "not_found",
            f"Snapshot {to_version} does not exist for {plan_id}.",
        )
    from_files = _snapshot_files(from_dir)
    to_files = _snapshot_files(to_dir)
    diff_lines: list[str] = []
    import difflib

    for relative_path in sorted(set(from_files) | set(to_files)):
        before = from_files.get(relative_path, [])
        after = to_files.get(relative_path, [])
        diff_lines.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"{version_label(parse_version(from_version))}/{relative_path}",
                tofile=f"{version_label(parse_version(to_version))}/{relative_path}",
            )
        )
    return "".join(diff_lines) if diff_lines else "No differences.\n"


def _snapshot_files(snapshot_dir: Path) -> dict[str, list[str]]:
    results: dict[str, list[str]] = {}
    for path in sorted(snapshot_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(snapshot_dir).as_posix()
        results[relative] = path.read_text(encoding="utf-8").splitlines(keepends=True)
    return results


def plan_to_dict(plan: Plan) -> dict[str, Any]:
    return {
        "plan_id": plan.plan_id,
        "title": plan.title,
        "status": plan.status,
        "version": plan.version,
        "path": str(plan.path),
        "rendered_path": str(versioned_rendered_path(plan)),
        "latest_rendered_path": str(latest_rendered_path(plan)),
        "components": {
            key: {
                "title": spec.title,
                "path": spec.path,
                "order": spec.order,
                "required": spec.required,
                "sha256": spec.sha256,
            }
            for key, spec in sorted(
                plan.components.items(),
                key=lambda item: (item[1].order, item[0]),
            )
        },
        "history": plan.metadata.get("history", []),
    }


def plan_status_counts(workspace: Workspace) -> dict[str, int]:
    counts: dict[str, int] = {}
    for plan in list_plans(workspace):
        counts[plan.status] = counts.get(plan.status, 0) + 1
    return counts


def doctor(workspace: Workspace) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    legacy_dir = workspace.planledger_dir / "ledgers" / "main"
    if legacy_dir.exists():
        errors.append(
            f"Old schema detected under {legacy_dir}; "
            "automatic migration is unsupported."
        )
        warnings.append(
            f"Move configured storage directory aside ({workspace.planledger_dir}) "
            "or initialize a fresh v2 workspace."
        )
    if not workspace.storage_path.exists():
        errors.append(f"Missing storage file: {workspace.storage_path}.")
    else:
        data = storage_data(workspace)
        if int(data.get("schema_version", 0)) != 2:
            errors.append("Unsupported storage schema; expected schema_version 2.")
    if not plans_dir(workspace).exists():
        errors.append(f"Missing plans directory: {plans_dir(workspace)}.")
    if not errors:
        for plan in list_plans(workspace):
            plan_errors = validate_plan(plan)
            for item in plan_errors:
                errors.append(f"{plan.plan_id}: {item}")
    return {
        "healthy": not errors,
        "errors": errors,
        "warnings": warnings,
        "workspace": {
            "root": str(workspace.root),
            "config_path": str(workspace.config_path),
            "planledger_dir": str(workspace.planledger_dir),
            "storage_path": str(workspace.storage_path),
        },
    }
def compute_next_action(
    workspace: Workspace | None, plan_id: str | None = None
) -> dict[str, Any]:
    """Compute the recommended next action for an agent.

    Read-only. Never creates or mutates a plan.
    """
    if workspace is None:
        return {
            "workspace_initialized": False,
            "plan_id": None,
            "status": None,
            "next_item": "init",
            "next_command": "planledger init",
            "blockers": [],
            "validation_errors": [],
        }

    plans = list_plans(workspace)

    if plan_id is not None:
        plan = load_plan(workspace, plan_id)
    else:
        active_plan_id = get_active_plan_id(workspace)
        if active_plan_id is not None:
            plan = load_plan(workspace, active_plan_id)
        else:
            active = [p for p in plans if p.status != "cancelled"]
            non_done = [p for p in active if p.status != "done"]
            if len(active) == 1:
                plan = active[0]
            elif len(non_done) == 1:
                plan = non_done[0]
            elif len(non_done) > 1:
                return {
                    "workspace_initialized": True,
                    "plan_id": None,
                    "status": None,
                    "next_item": "specify_plan",
                    "next_command": "planledger --json plan list",
                    "blockers": [
                        "Multiple non-done plans exist; specify a plan id."
                    ],
                    "validation_errors": [],
                }
            else:
                return {
                    "workspace_initialized": True,
                    "plan_id": None,
                    "status": None,
                    "next_item": "create_plan",
                    "next_command": (
                        "planledger plan create --title \"TITLE\" "
                        "--request-file /tmp/request.md"
                    ),
                    "blockers": [],
                    "validation_errors": [],
                }

    contents = load_component_contents(plan)
    errors = validate_plan(plan, for_done=True)

    empty_required = [
        key
        for key in ordered_component_keys(plan.components)
        if plan.components[key].required and not contents.get(key, "").strip()
    ]

    if empty_required:
        first_empty = empty_required[0]
        return {
            "workspace_initialized": True,
            "plan_id": plan.plan_id,
            "status": plan.status,
            "next_item": "fill_component",
            "next_command": (
                f"planledger plan component set {plan.plan_id} {first_empty} "
                f"--file /tmp/{first_empty}.md"
            ),
            "blockers": [],
            "validation_errors": errors,
        }

    if errors:
        return {
            "workspace_initialized": True,
            "plan_id": plan.plan_id,
            "status": plan.status,
            "next_item": "fix_validation",
            "next_command": f"planledger plan validate {plan.plan_id}",
            "blockers": errors,
            "validation_errors": errors,
        }

    if plan.status == "done":
        rendered = latest_rendered_path(plan)
        return {
            "workspace_initialized": True,
            "plan_id": plan.plan_id,
            "status": plan.status,
            "next_item": "handoff_ready",
            "next_command": f"planledger plan show {plan.plan_id} --rendered",
            "blockers": [],
            "validation_errors": [],
            "rendered_path": str(rendered),
        }

    return {
        "workspace_initialized": True,
        "plan_id": plan.plan_id,
        "status": plan.status,
        "next_item": "mark_done_after_human_approval",
        "next_command": (
            f"planledger plan status {plan.plan_id} done "
            f"--reason \"Ready for handoff.\""
        ),
        "blockers": [],
        "validation_errors": [],
    }
