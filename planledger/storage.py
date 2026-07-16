# ruff: noqa: E501
from __future__ import annotations

import copy
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from uuid import uuid4

from ledgercore.atomic import atomic_write_text
from ledgercore.errors import AtomicWriteError, IdFormatError, YamlStoreError
from ledgercore.io import content_hash
from ledgercore.paths import locate_config
from ledgercore.time import utc_now_iso
from ledgercore.yamlio import load_yaml_object, write_yaml
from tomlkit import dumps as toml_dumps

from planledger.errors import PlanledgerError
from planledger.guardrails import (
    count_resolved_required_questions,
    resolved_required_question_topics,
    unresolved_required_question_topics,
    unresolved_required_questions,
    validate_handoff_contents,
    validate_workshop_contents,
)
from planledger.id_inventory import (
    reserve_plan_directory,
    reserve_workshop_directory,
    scan_plan_allocations,
    scan_workshop_allocations,
)
from planledger.identity import (
    DEFAULT_LEDGER_CODE,
    DEFAULT_LEDGER_NAME,
    PLAN_KIND,
    WORKSHOP_KIND,
    ledger_code_from_config,
    normalize_plan_selector,
    normalize_workshop_selector,
    plan_ref,
    workshop_ref,
)
from planledger.models import (
    AppContext,
    ComponentSpec,
    Plan,
    PlanStatus,
    Workshop,
    WorkshopStatus,
    Workspace,
)
from planledger.project_binding import (
    create_project_binding,
    directory_is_effectively_empty,
)
from planledger.project_context import (
    load_workspace as load_canonical_workspace,
)
from planledger.project_context import (
    locate_project,
)
from planledger.prompt_profiles import (
    active_prompt_profile_for_plan,
    load_prompt_profile,
    prompt_profile_doctor_warnings,
)

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

# Default one-question-per-topic prompts surfaced by ``compute_next_action``
# when a configured ``required_question_topics`` entry has no recorded question yet.
_DEFAULT_PLAN_QUESTIONS_BY_TOPIC: dict[str, str] = {
    "scope": (
        "Should this plan include only the minimal implementation path, "
        "or also documentation and migration cleanup?"
    ),
    "tests": (
        "Which validation level is required before handoff: focused tests only, "
        "the full test suite, or manual CLI smoke checks as well?"
    ),
    "rollback": (
        "What rollback or repair path should the implementation preserve if "
        "the change fails?"
    ),
    "risks": (
        "Which risk should be optimized for first: compatibility, "
        "implementation speed, or completeness?"
    ),
}


def _default_question_for_topic(topic: str) -> str:
    """Return the default question text for a configured required-question topic."""
    return _DEFAULT_PLAN_QUESTIONS_BY_TOPIC.get(
        topic,
        f"What open decision remains for the '{topic}' topic before this plan can be done?",
    )


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
    return utc_now_iso()


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
    try:
        atomic_write_text(path, content, normalize=True)
    except AtomicWriteError as exc:
        raise PlanledgerError(
            "storage_error",
            f"Failed to write {path}.",
        ) from exc


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    try:
        write_yaml(path, data, sort_keys=False)
    except (AtomicWriteError, YamlStoreError) as exc:
        raise PlanledgerError(
            "storage_error",
            f"Failed to write YAML file {path}.",
        ) from exc


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PlanledgerError(
            "not_found",
            f"Required file does not exist: {path}",
        )
    try:
        loaded = load_yaml_object(path, label=f"YAML file {path}")
    except YamlStoreError as exc:
        raise PlanledgerError(
            "invalid_yaml",
            f"Expected a mapping in {path}.",
        ) from exc
    return dict(loaded)


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
    locator = locate_config(start, PLANLEDGER_CONFIG_FILENAMES)
    if locator is None:
        return None
    return locator.workspace_root, locator.config_path


def _resolve_planledger_dir(root: Path, configured_dir: str) -> Path:
    configured_path = Path(configured_dir).expanduser()
    if configured_path.is_absolute():
        return configured_path.resolve()
    return (root / configured_path).resolve()


def discover_workspace(app_ctx: AppContext) -> Workspace | None:
    start = workspace_root_from_context(app_ctx)
    locator = locate_project(start)
    if locator is None:
        return None
    return load_canonical_workspace(start)


def load_workspace(app_ctx: AppContext) -> Workspace:
    return load_canonical_workspace(workspace_root_from_context(app_ctx))


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
    data = _load_yaml(workspace.storage_path)
    if data.get("schema_version") != 4:
        raise PlanledgerError(
            "PLANLEDGER_STATE_SCHEMA_OLD",
            "Planledger runtime requires storage schema 4; run migration.",
        )
    if any(key in data for key in ("project_uuid", "next_plan_id", "next_workshop_id")):
        raise PlanledgerError(
            "PLANLEDGER_STATE_INVALID",
            "Schema-4 state must not contain project identity or persisted ID counters.",
        )
    return data


def save_storage_data(workspace: Workspace, data: dict[str, Any]) -> None:
    _write_yaml(workspace.storage_path, data)


def preview_plan_id(workspace: Workspace) -> str:
    return scan_plan_allocations(workspace).next_id


def allocate_plan_id(workspace: Workspace) -> str:
    plan_id, _ = reserve_plan_directory(workspace)
    return plan_id


def get_active_plan_id(workspace: Workspace) -> str | None:
    data = storage_data(workspace)
    return data.get("active_plan_id") or None


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
    raw = explicit if explicit is not None else positional
    if raw is not None:
        return _normalize_plan_id(workspace, raw)
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


def _write_toml(path: Path, document: dict[str, Any]) -> None:
    _atomic_write(path, toml_dumps(document))


def _canonical_manifest(project_uuid: str, project_name: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "project": {"uuid": project_uuid, "name": project_name},
        "storage": {
            "workspace": {"default_provider": "user-data", "namespace": "ledgerwerk"},
            "cache": {"default_provider": "user-cache", "namespace": "ledgerwerk"},
        },
        "ledgers": {
            "planledger": {
                "config": {"location": "project", "path": "plan/config.toml"},
                "mounts": {
                    "data": {
                        "storage": "workspace",
                        "scope": "project",
                        "path": "plan/planledger",
                    },
                },
            },
        },
    }


def _canonical_stable_config() -> dict[str, Any]:
    return {
        "config_version": 1,
        "ledger": {"code": DEFAULT_LEDGER_CODE, "name": DEFAULT_LEDGER_NAME},
        "prompt_profiles": {
            "planning_workshop": {
                "enabled": True,
                "activation": "always",
                "question_policy": "ask_one_at_a_time",
                "codebase_first": True,
                "include_recommended_answer": True,
                "max_required_questions": 10,
                "required_question_topics": ["scope", "tests", "rollback", "risks"],
            },
        },
    }


def _ensure_sibling_store(store_root: Path, *, create: bool) -> bool:
    created = False
    if store_root.exists():
        if store_root.is_symlink() or not store_root.is_dir():
            raise PlanledgerError(
                "PLANLEDGER_SIBLING_ROOT_NOT_DIRECTORY",
                f"Canonical sibling store is not a directory: {store_root}.",
            )
    elif create:
        store_root.mkdir(parents=True)
        created = True
    else:
        raise PlanledgerError(
            "PLANLEDGER_SIBLING_ROOT_MISSING",
            "The canonical sibling Ledger store does not exist or is not marked.",
            remediation=["Run: planledger init --create-sibling-store"],
        )
    marker = store_root / ".ledger-store"
    if marker.exists() or marker.is_symlink():
        if marker.is_symlink() or not marker.is_file():
            raise PlanledgerError(
                "PLANLEDGER_SIBLING_MARKER_INVALID",
                f"Sibling store marker must be a regular file: {marker}.",
            )
    else:
        entries = list(store_root.iterdir())
        if entries and not created:
            raise PlanledgerError(
                "PLANLEDGER_SIBLING_ROOT_NOT_EMPTY",
                f"Cannot mark non-empty sibling directory: {store_root}.",
            )
        if not create:
            raise PlanledgerError(
                "PLANLEDGER_SIBLING_ROOT_UNMARKED",
                f"Sibling store marker is missing: {marker}.",
            )
        marker.touch(exist_ok=False)
        created = True
    return created


def initialize_project(
    root: Path,
    project_name: str,
    *,
    create_sibling_store: bool = False,
) -> Workspace:
    resolved_root = root.resolve()
    ledger_dir = resolved_root / ".ledger"
    manifest_path = ledger_dir / "ledger.toml"
    local_path = ledger_dir / "ledger.local.toml"
    stable_path = ledger_dir / "plan" / "config.toml"
    if manifest_path.exists() or local_path.exists() or stable_path.exists():
        try:
            return load_canonical_workspace(resolved_root)
        except PlanledgerError as exc:
            raise PlanledgerError(
                "PLANLEDGER_INITIALIZATION_CONFLICT",
                "Existing canonical Ledger configuration is incomplete or conflicting.",
                remediation=["Run: planledger doctor", "Run: planledger migrate"],
            ) from exc
    for legacy in PLANLEDGER_CONFIG_FILENAMES:
        if (resolved_root / legacy).exists():
            raise PlanledgerError(
                "PLANLEDGER_MIGRATION_REQUIRED",
                f"Legacy Planledger configuration found: {resolved_root / legacy}.",
                remediation=["Run: planledger migrate"],
            )
    project_uuid = str(uuid4())
    store_root = resolved_root.parent / "ledger"
    _ensure_sibling_store(store_root, create=create_sibling_store)
    data_root = store_root / "plan" / "planledger"
    data_root.mkdir(parents=True, exist_ok=True)
    if not directory_is_effectively_empty(data_root):
        raise PlanledgerError(
            "PLANLEDGER_DATA_ROOT_UNBOUND",
            f"Non-empty unbound Planledger data exists: {data_root}.",
            remediation=["Run: planledger migrate"],
        )
    ledger_dir.mkdir(parents=True, exist_ok=True)
    _write_toml(manifest_path, _canonical_manifest(project_uuid, project_name))
    _write_toml(
        local_path,
        {"schema_version": 1, "storage": {"workspace": {"provider": "sibling-ledger"}}},
    )
    stable_path.parent.mkdir(parents=True, exist_ok=True)
    _write_toml(stable_path, _canonical_stable_config())
    binding = create_project_binding(data_root, project_uuid=project_uuid)
    timestamp = now_iso()
    _write_yaml(
        data_root / STORAGE_FILENAME,
        {
            "schema_version": 4,
            "active_plan_id": None,
            "active_workshop_id": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )
    for directory in (
        "allocations/plans",
        "allocations/workshops",
        "migrations",
        "plans",
        "workshops",
    ):
        (data_root / directory).mkdir(parents=True, exist_ok=True)
    workspace = load_canonical_workspace(resolved_root)
    if workspace.binding != binding:
        raise PlanledgerError(
            "PLANLEDGER_BINDING_INVALID", "Created binding did not validate."
        )
    return workspace


def _toml_dump(data: dict[str, Any]) -> str:
    return toml_dumps(data)


def _hash_text(content: str) -> str:
    return content_hash(content)


def _normalize_plan_id(workspace: Workspace, value: str) -> str:
    try:
        return normalize_plan_selector(
            value,
            ledger_code=ledger_code_from_config(workspace.config),
        )
    except IdFormatError as exc:
        raise PlanledgerError(
            "invalid_plan_ref",
            f"Invalid plan reference {value!r}.",
            remediation=[
                "Use a local plan id such as plan-0001.",
                "Or use a Planledger global ref such as pl:plan-0001.",
            ],
        ) from exc


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


def save_plan_metadata(plan: Plan) -> None:
    _write_plan_metadata(plan)


def load_plan(workspace: Workspace, plan_id: str) -> Plan:
    plan_id = _normalize_plan_id(workspace, plan_id)
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


def _profile_done_errors(
    workspace: Workspace,
    plan: Plan,
    contents: dict[str, str],
) -> list[str]:
    """Block done when an active profile requires resolved questions.

    Returns no errors when no profile is active or the configured minimum is 0,
    preserving the default permissive behavior.
    """
    profile = active_prompt_profile_for_plan(
        workspace, plan, request_text=contents.get("request", "")
    )
    if profile is None or not profile.active:
        # A configured-but-inactive profile still enforces its minimum only
        # when active, because the resolved-question gate is plan-scoped.
        configured = load_prompt_profile(
            workspace.config, request_text=contents.get("request", "")
        )
        if not configured.enabled:
            return []
        profile = configured

    required_count = profile.min_resolved_required_questions_before_done
    if required_count <= 0:
        return []

    resolved = count_resolved_required_questions(contents.get("open_questions", ""))
    if resolved < required_count:
        return [
            "Prompt profile 'planning_workshop' requires "
            f"{required_count} resolved required question(s) before done; "
            f"found {resolved}."
        ]
    return []


def validate_plan(
    plan: Plan,
    *,
    for_done: bool = False,
    workspace: Workspace | None = None,
) -> list[str]:
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
        if workspace is not None:
            errors.extend(_profile_done_errors(workspace, plan, contents))
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
        done_errors.extend(_profile_done_errors(workspace, provisional_plan, contents))
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
        "kind": PLAN_KIND,
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
        errors.extend(_profile_done_errors(workspace, plan, next_contents))
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


def plan_to_dict(
    plan: Plan,
    *,
    ledger_code: str = DEFAULT_LEDGER_CODE,
) -> dict[str, Any]:
    ref = plan_ref(plan.plan_id, ledger_code=ledger_code)
    return {
        "plan_id": plan.plan_id,
        "id": plan.plan_id,
        "kind": PLAN_KIND,
        "ledger_code": ref.ledger,
        "global_ref": ref.global_ref,
        "file_ref": ref.file_ref,
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
    if (
        not workspace.store_marker_path.is_file()
        or workspace.store_marker_path.is_symlink()
    ):
        errors.append(f"Invalid sibling store marker: {workspace.store_marker_path}.")
    if not workspace.storage_path.exists():
        errors.append(f"Missing storage file: {workspace.storage_path}.")
    else:
        data = storage_data(workspace)
        if data.get("schema_version") != 4:
            errors.append("Unsupported storage schema; expected schema_version 4.")
        for key in ("project_uuid", "next_plan_id", "next_workshop_id"):
            if key in data:
                errors.append(f"State must not contain {key}.")
    for directory in (
        plans_dir(workspace),
        workshops_dir(workspace),
        workspace.planledger_dir / "allocations" / "plans",
        workspace.planledger_dir / "allocations" / "workshops",
    ):
        if not directory.is_dir():
            errors.append(f"Missing required directory: {directory}.")
    if not errors:
        for plan in list_plans(workspace):
            for item in validate_plan(plan):
                errors.append(f"{plan.plan_id}: {item}")
        for workshop in list_workshops(workspace):
            for item in validate_workshop(workshop):
                errors.append(f"{workshop.workshop_id}: {item}")
    warnings.extend(prompt_profile_doctor_warnings(workspace.config))
    return {
        "healthy": not errors,
        "errors": errors,
        "warnings": warnings,
        "workspace": {
            "root": str(workspace.root),
            "config_path": str(workspace.config_path),
            "manifest_path": str(workspace.manifest_path),
            "local_config_path": str(workspace.local_config_path),
            "planledger_dir": str(workspace.planledger_dir),
            "storage_path": str(workspace.storage_path),
            "workspace_provider": workspace.workspace_provider,
            "store_root": str(workspace.store_root),
            "store_marker_path": str(workspace.store_marker_path),
            "binding_path": str(workspace.binding_path),
            "active_mount": workspace.active_mount_name,
        },
    }


def _compute_active_workshop_next_action(workspace: Workspace) -> dict[str, Any] | None:
    active_workshop_id = get_active_workshop_id(workspace)
    if active_workshop_id is None:
        return None

    workshop = load_workshop(workspace, active_workshop_id)
    contents = load_workshop_component_contents(workshop)
    workshop_errors = validate_workshop(workshop, for_shaped=True)
    unresolved = unresolved_required_questions(contents.get("open_questions", ""))
    base = {
        "workspace_initialized": True,
        "workshop_id": workshop.workshop_id,
        "workshop_status": workshop.status,
        "plan_id": None,
        "status": None,
        "blockers": [],
        "validation_errors": workshop_errors,
    }
    if unresolved:
        return {
            **base,
            "next_item": "answer_required_workshop_question",
            "next_command": None,
            "question": unresolved[0],
        }
    profile = load_prompt_profile(workspace.config, name="planning_workshop")
    if (
        profile.enabled
        and profile.active
        and workshop.status
        not in {
            "shaped",
            "planned",
            "cancelled",
        }
    ):
        return {
            **base,
            "next_item": "ask_workshop_question",
            "next_command": None,
            "prompt_profile": profile.to_dict(),
            "agent_instruction": (
                "Ask exactly one planning-workshop question, include a "
                "recommended answer, record it in open_questions, and stop."
            ),
        }
    if not contents.get("examples", "").strip():
        return {
            **base,
            "next_item": "add_concrete_example",
            "component": "examples",
            "next_command": (
                f"planledger workshop component set examples "
                f"--workshop {workshop.workshop_id} --file examples.md"
            ),
        }
    if not workshop_errors and workshop.status == "exploring":
        return {
            **base,
            "next_item": "mark_workshop_shaped",
            "next_command": (
                f"planledger workshop status {workshop.workshop_id} shaped "
                '--reason "Examples, scope, and scenarios are clear."'
            ),
        }
    if workshop.status == "shaped" and not workshop.metadata.get("linked_plans"):
        return {
            **base,
            "next_item": "create_plan_from_workshop",
            "next_command": (
                f"planledger plan create --from-workshop {workshop.workshop_id} "
                f'--title "Implement: {workshop.title}"'
            ),
        }
    return None


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

    if plan_id is None:
        workshop_action = _compute_active_workshop_next_action(workspace)
        if workshop_action is not None:
            return workshop_action

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
                    "blockers": ["Multiple non-done plans exist; specify a plan id."],
                    "validation_errors": [],
                }
            else:
                return {
                    "workspace_initialized": True,
                    "plan_id": None,
                    "status": None,
                    "next_item": "create_plan",
                    "next_command": (
                        'planledger plan create --title "TITLE" '
                        "--request-file /tmp/request.md"
                    ),
                    "blockers": [],
                    "validation_errors": [],
                }

    contents = load_component_contents(plan)
    request_text = contents.get("request", "")
    configured_profile = load_prompt_profile(
        workspace.config, request_text=request_text
    )
    profile_payload = (
        configured_profile.to_dict() if configured_profile.enabled else None
    )

    def attach(result: dict[str, Any]) -> dict[str, Any]:
        if profile_payload is not None:
            result["prompt_profile"] = profile_payload
        return result

    errors = validate_plan(plan, for_done=True, workspace=workspace)

    empty_required = [
        key
        for key in ordered_component_keys(plan.components)
        if plan.components[key].required and not contents.get(key, "").strip()
    ]

    if empty_required:
        first_empty = empty_required[0]
        return attach(
            {
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
        )

    unresolved = unresolved_required_questions(contents.get("open_questions", ""))
    if unresolved:
        first_question = unresolved[0]
        return attach(
            {
                "workspace_initialized": True,
                "plan_id": plan.plan_id,
                "status": plan.status,
                "next_item": "answer_required_question",
                "next_command": None,
                "question": first_question,
                "agent_instruction": (
                    "Ask this one required question, include your recommended "
                    "answer, and stop."
                ),
                "blockers": [],
                "validation_errors": errors,
            }
        )

    # While the planning-workshop / planning-interview profile is active, the
    # configured required-question topics form a deterministic interview queue.
    # Surface the next unmet topic as an explicit question before falling back
    # to the generic plan-quality prompt. This drives the content that resolves
    # most validation findings, so it takes priority over remaining fixes.
    if (
        configured_profile.enabled
        and configured_profile.active
        and plan.status not in ("done", "cancelled")
    ):
        open_questions_text = contents.get("open_questions", "")
        resolved_topics = resolved_required_question_topics(open_questions_text)
        unresolved_topics = unresolved_required_question_topics(open_questions_text)
        resolved_required_count = count_resolved_required_questions(open_questions_text)
        topics_remaining = [
            topic
            for topic in configured_profile.required_question_topics
            if topic not in resolved_topics and topic not in unresolved_topics
        ]
        all_configured_topics_resolved = bool(
            configured_profile.required_question_topics
        ) and set(configured_profile.required_question_topics).issubset(resolved_topics)
        max_reached = (
            resolved_required_count >= configured_profile.max_required_questions
        )

        if topics_remaining:
            topic = topics_remaining[0]
            question = _default_question_for_topic(topic)
            return attach(
                {
                    "workspace_initialized": True,
                    "plan_id": plan.plan_id,
                    "status": plan.status,
                    "next_item": "ask_plan_question",
                    "topic": topic,
                    "question": question,
                    "next_command": None,
                    "resolved_required_questions_count": resolved_required_count,
                    "questions_remaining_count": len(topics_remaining),
                    "agent_instruction": (
                        f"Record this as '- [ ] REQUIRED({topic}): ...', ask exactly "
                        "this one question, include a recommended answer, and stop."
                    ),
                    "blockers": [],
                    "validation_errors": errors,
                }
            )

        # Generic plan-quality prompt: only when no configured topics remain
        # unresolved and the resolved-question budget has not been spent.
        if not all_configured_topics_resolved and not max_reached:
            return attach(
                {
                    "workspace_initialized": True,
                    "plan_id": plan.plan_id,
                    "status": plan.status,
                    "next_item": "ask_plan_question",
                    "next_command": None,
                    "agent_instruction": (
                        "Inspect the codebase first. Then ask exactly one unresolved "
                        "plan-quality question, include your recommended answer, "
                        "and stop."
                    ),
                    "blockers": [],
                    "validation_errors": errors,
                }
            )

    if errors:
        return attach(
            {
                "workspace_initialized": True,
                "plan_id": plan.plan_id,
                "status": plan.status,
                "next_item": "fix_validation",
                "next_command": f"planledger plan validate {plan.plan_id}",
                "blockers": errors,
                "validation_errors": errors,
            }
        )

    if plan.status == "done":
        rendered = latest_rendered_path(plan)
        return attach(
            {
                "workspace_initialized": True,
                "plan_id": plan.plan_id,
                "status": plan.status,
                "next_item": "handoff_ready",
                "next_command": f"planledger plan show {plan.plan_id} --rendered",
                "blockers": [],
                "validation_errors": [],
                "rendered_path": str(rendered),
            }
        )

    return attach(
        {
            "workspace_initialized": True,
            "plan_id": plan.plan_id,
            "status": plan.status,
            "next_item": "mark_done_after_human_approval",
            "next_command": (
                f"planledger plan status {plan.plan_id} "
                'done --reason "Ready for handoff."'
            ),
            "blockers": [],
            "validation_errors": [],
        }
    )


VALID_WORKSHOP_STATUSES: set[WorkshopStatus] = {
    "new",
    "exploring",
    "shaped",
    "planned",
    "cancelled",
}
VALID_WORKSHOP_TRANSITIONS: dict[WorkshopStatus, set[WorkshopStatus]] = {
    "new": {"exploring", "shaped", "cancelled"},
    "exploring": {"shaped", "cancelled"},
    "shaped": {"exploring", "planned", "cancelled"},
    "planned": {"exploring", "cancelled"},
    "cancelled": set(),
}
WORKSHOP_COMPONENT_DEFINITIONS: tuple[tuple[str, str, str, int, bool], ...] = (
    ("request", "components/request.md", "Original request", 0, True),
    ("story", "components/story.md", "Story / intent", 10, True),
    ("context", "components/context.md", "Repository / product context", 20, False),
    ("examples", "components/examples.md", "Concrete examples", 30, True),
    ("rules", "components/rules.md", "Business rules", 40, False),
    ("open_questions", "components/open_questions.md", "Open questions", 50, False),
    ("decisions", "components/decisions.md", "Decisions", 60, True),
    ("scope", "components/scope.md", "Scope", 70, True),
    (
        "acceptance_scenarios",
        "components/acceptance_scenarios.md",
        "Accepted scenarios",
        80,
        True,
    ),
    ("plan_hints", "components/plan_hints.md", "Plan hints", 90, False),
    ("risks", "components/risks.md", "Risks", 100, False),
    ("notes", "components/notes.md", "Notes", 110, False),
)


def _ensure_workshop_storage_defaults(workspace: Workspace) -> dict[str, Any]:
    data = storage_data(workspace)
    if data.get("schema_version") != 4:
        raise PlanledgerError(
            "PLANLEDGER_STATE_SCHEMA_OLD",
            "Planledger runtime requires storage schema 4; run migration.",
        )
    return data


def workshops_dir(workspace: Workspace) -> Path:
    return workspace.planledger_dir / "workshops"


def workshop_dir(workspace: Workspace, workshop_id: str) -> Path:
    return workshops_dir(workspace) / workshop_id


def workshop_metadata_path_from_dir(path: Path) -> Path:
    return path / "workshop.yaml"


def workshop_metadata_path(workspace: Workspace, workshop_id: str) -> Path:
    return workshop_metadata_path_from_dir(workshop_dir(workspace, workshop_id))


def workshop_rendered_dir(workshop: Workshop) -> Path:
    return workshop.path / "rendered"


def latest_rendered_workshop_path(workshop: Workshop) -> Path:
    return workshop_rendered_dir(workshop) / "latest.md"


def versioned_rendered_workshop_path(
    workshop: Workshop, version: int | None = None
) -> Path:
    selected = version if version is not None else workshop.version
    return (
        workshop_rendered_dir(workshop)
        / f"{workshop.workshop_id}-{version_label(selected)}.md"
    )


def workshop_versions_dir(workshop: Workshop) -> Path:
    return workshop.path / "versions"


def workshop_version_snapshot_dir(workshop: Workshop, version: int) -> Path:
    return workshop_versions_dir(workshop) / version_label(version)


def default_plan_component_specs() -> dict[str, ComponentSpec]:
    return default_component_specs()


def default_workshop_component_specs() -> dict[str, ComponentSpec]:
    return {
        k: ComponentSpec(k, path, title, order, required)
        for k, path, title, order, required in WORKSHOP_COMPONENT_DEFINITIONS
    }


def plan_component_spec(key: str) -> ComponentSpec:
    return component_spec(key)


def workshop_component_spec(key: str) -> ComponentSpec:
    specs = default_workshop_component_specs()
    if key not in specs:
        raise PlanledgerError(
            "invalid_component",
            f"Unknown workshop component key {key!r}.",
            remediation=["Use one of: " + ", ".join(ordered_component_keys(specs))],
        )
    return specs[key]


def preview_workshop_id(workspace: Workspace) -> str:
    return scan_workshop_allocations(workspace).next_id


def allocate_workshop_id(workspace: Workspace) -> str:
    workshop_id, _ = reserve_workshop_directory(workspace)
    return workshop_id


def get_active_workshop_id(workspace: Workspace) -> str | None:
    data = storage_data(workspace)
    return data.get("active_workshop_id") or None


def set_active_workshop_id(workspace: Workspace, workshop_id: str | None) -> None:
    data = _ensure_workshop_storage_defaults(workspace)
    data["active_workshop_id"] = workshop_id or ""
    data["updated_at"] = now_iso()
    save_storage_data(workspace, data)


def _normalize_workshop_id(workspace: Workspace, value: str) -> str:
    try:
        return normalize_workshop_selector(
            value, ledger_code=ledger_code_from_config(workspace.config)
        )
    except IdFormatError as exc:
        raise PlanledgerError(
            "invalid_workshop_ref",
            f"Invalid workshop reference {value!r}.",
            remediation=["Use workshop-0001, pl:workshop-0001, or pl-workshop-0001."],
        ) from exc


def resolve_workshop_id(
    workspace: Workspace, selector: str | None = None, positional: str | None = None
) -> str:
    raw = selector if selector is not None else positional
    if raw is not None:
        return _normalize_workshop_id(workspace, raw)
    active = get_active_workshop_id(workspace)
    if active:
        return active
    raise PlanledgerError(
        "no_active_workshop", "No active workshop and no workshop selector provided."
    )


def _workshop_from_metadata(path: Path, metadata: dict[str, Any]) -> Workshop:
    raw = metadata.get("components")
    if not isinstance(raw, dict):
        raise PlanledgerError(
            "invalid_workshop", f"Workshop metadata at {path} is missing components."
        )
    comps: dict[str, ComponentSpec] = {}
    for key, spec in raw.items():
        if not isinstance(spec, dict):
            raise PlanledgerError(
                "invalid_workshop", f"Component metadata for {key!r} must be a mapping."
            )
        comps[key] = ComponentSpec(
            key=key,
            path=str(spec.get("path")),
            title=str(spec.get("title")),
            order=int(spec.get("order", 0)),
            required=bool(spec.get("required", False)),
            sha256=str(spec["sha256"]) if isinstance(spec.get("sha256"), str) else None,
        )
    return Workshop(str(metadata.get("id") or path.name), path, metadata, comps)


def _write_workshop_metadata(workshop: Workshop) -> None:
    workshop.metadata["components"] = {
        k: _component_metadata(v)
        for k, v in sorted(
            workshop.components.items(), key=lambda item: (item[1].order, item[0])
        )
    }
    _write_yaml(workshop_metadata_path_from_dir(workshop.path), workshop.metadata)


def save_workshop_metadata(workshop: Workshop) -> None:
    _write_workshop_metadata(workshop)


def load_workshop(workspace: Workspace, workshop_id: str) -> Workshop:
    workshop_id = _normalize_workshop_id(workspace, workshop_id)
    path = workshop_dir(workspace, workshop_id)
    if not path.exists():
        raise PlanledgerError("not_found", f"Workshop {workshop_id} does not exist.")
    return _workshop_from_metadata(
        path, _load_yaml(workshop_metadata_path(workspace, workshop_id))
    )


def list_workshops(workspace: Workspace, status: str | None = None) -> list[Workshop]:
    _ensure_workshop_storage_defaults(workspace)
    result: list[Workshop] = []
    if not workshops_dir(workspace).exists():
        return result
    for candidate in sorted(workshops_dir(workspace).iterdir()):
        meta = workshop_metadata_path_from_dir(candidate)
        if candidate.is_dir() and meta.exists():
            workshop = _workshop_from_metadata(candidate, _load_yaml(meta))
            if status is None or workshop.status == status:
                result.append(workshop)
    return result


def activate_workshop(workspace: Workspace, workshop_id: str) -> Workshop:
    workshop = load_workshop(workspace, workshop_id)
    set_active_workshop_id(workspace, workshop.workshop_id)
    return workshop


def load_workshop_component_content(workshop: Workshop, component: str) -> str:
    spec = workshop.components.get(component)
    if spec is None:
        workshop_component_spec(component)
        raise AssertionError("unreachable")
    try:
        return (workshop.path / spec.path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PlanledgerError(
            "not_found", f"Component file does not exist: {workshop.path / spec.path}"
        ) from exc


def load_workshop_component_contents(workshop: Workshop) -> dict[str, str]:
    return {
        k: load_workshop_component_content(workshop, k)
        for k in ordered_component_keys(workshop.components)
    }


def _validate_workshop_status(status: str) -> WorkshopStatus:
    if status not in VALID_WORKSHOP_STATUSES:
        raise PlanledgerError(
            "invalid_status",
            f"Invalid workshop status {status!r}.",
            remediation=["Use one of: " + ", ".join(sorted(VALID_WORKSHOP_STATUSES))],
        )
    return status


def validate_workshop(workshop: Workshop, *, for_shaped: bool = False) -> list[str]:
    errors: list[str] = []
    try:
        _validate_workshop_status(workshop.status)
    except PlanledgerError as exc:
        errors.append(exc.message)
    specs = default_workshop_component_specs()
    for key in specs:
        if key not in workshop.components:
            errors.append(f"Missing component metadata for {key!r}.")
    for key in workshop.components:
        if key not in specs:
            errors.append(f"Unknown component metadata for {key!r}.")
    if for_shaped:
        errors.extend(
            validate_workshop_contents(load_workshop_component_contents(workshop))
        )
    return errors


def create_workshop(
    workspace: Workspace,
    title: str,
    request: str,
    status: str = "new",
    *,
    components: dict[str, str] | None = None,
) -> Workshop:
    if not title.strip():
        raise PlanledgerError("invalid_title", "Workshop title must not be empty.")
    validated = _validate_workshop_status(status)
    values = components or {}
    for key in values:
        workshop_component_spec(key)
    wid = allocate_workshop_id(workspace)
    created = now_iso()
    path = workshop_dir(workspace, wid)
    path.mkdir(parents=True, exist_ok=True)
    specs = default_workshop_component_specs()
    contents = {k: "" for k in specs}
    contents["request"] = request
    contents.update(values)
    if validated == "shaped":
        errs = validate_workshop_contents(contents)
        if errs:
            raise PlanledgerError(
                "invalid_workshop",
                "Cannot create a shaped workshop: validation failed.",
                remediation=errs,
            )
    for key in ordered_component_keys(specs):
        spec = specs[key]
        spec.sha256 = _hash_text(contents[key])
        _atomic_write(path / spec.path, contents[key])
    meta: dict[str, Any] = {
        "schema_version": 3,
        "id": wid,
        "kind": WORKSHOP_KIND,
        "type": "workshop",
        "title": title,
        "status": validated,
        "version": 1,
        "created_at": created,
        "updated_at": created,
        "linked_plans": [],
        "components": {
            k: _component_metadata(v)
            for k, v in sorted(specs.items(), key=lambda item: (item[1].order, item[0]))
        },
        "history": [
            {
                "version": 1,
                "status": validated,
                "created_at": created,
                "reason": "Initial workshop",
            }
        ],
    }
    workshop = Workshop(wid, path, meta, specs)
    _write_workshop_metadata(workshop)
    snapshot_workshop_version(workshop)
    set_active_workshop_id(workspace, wid)
    return load_workshop(workspace, wid)


def apply_workshop_mutations(
    workspace: Workspace,
    workshop_id: str,
    *,
    component_updates: dict[str, str] | None = None,
    append_components: set[str] | None = None,
    status: str | None = None,
    reason: str | None = None,
    force: bool = False,
) -> Workshop:
    workshop = load_workshop(workspace, workshop_id)
    updates = component_updates or {}
    append_keys = append_components or set()
    for key in updates:
        workshop_component_spec(key)
    if workshop.status == "cancelled" and (updates or status) and not force:
        raise PlanledgerError(
            "cancelled_workshop",
            f"Workshop {workshop.workshop_id} is cancelled and cannot be edited.",
        )
    current = load_workshop_component_contents(workshop)
    nxt = dict(current)
    changed = []
    for key, value in updates.items():
        content = _append_text(current[key], value) if key in append_keys else value
        if content != current[key]:
            nxt[key] = content
            changed.append(key)
    next_status = workshop.status
    status_changed = False
    if status is not None:
        validated = _validate_workshop_status(status)
        if (
            validated != workshop.status
            and validated not in VALID_WORKSHOP_TRANSITIONS[workshop.status]
        ):
            raise PlanledgerError(
                "invalid_status_transition",
                f"Cannot change workshop status from {workshop.status!r} to {validated!r}.",
            )
        if validated != workshop.status:
            next_status = validated
            status_changed = True
    if next_status == "shaped":
        errs = validate_workshop_contents(nxt)
        if errs:
            raise PlanledgerError(
                "invalid_workshop",
                "Cannot set workshop status to shaped: validation failed.",
                remediation=errs,
            )
    if not changed and not status_changed:
        return workshop
    ts = now_iso()
    for key in changed:
        spec = workshop.components[key]
        spec.sha256 = _hash_text(nxt[key])
        _atomic_write(workshop.path / spec.path, nxt[key])
    workshop.metadata["status"] = next_status
    workshop.metadata["version"] = workshop.version + 1
    workshop.metadata["updated_at"] = ts
    history = workshop.metadata.setdefault("history", [])
    if isinstance(history, list):
        history.append(
            {
                "version": workshop.metadata["version"],
                "status": next_status,
                "created_at": ts,
                "reason": reason.strip()
                if isinstance(reason, str) and reason.strip()
                else "Updated workshop.",
            }
        )
    _write_workshop_metadata(workshop)
    snapshot_workshop_version(workshop)
    return load_workshop(workspace, workshop_id)


def set_workshop_component(
    workspace: Workspace,
    workshop_id: str,
    component: str,
    content: str,
    reason: str | None = None,
    *,
    force: bool = False,
) -> Workshop:
    return apply_workshop_mutations(
        workspace,
        workshop_id,
        component_updates={component: content},
        reason=reason,
        force=force,
    )


def append_workshop_component(
    workspace: Workspace,
    workshop_id: str,
    component: str,
    content: str,
    reason: str | None = None,
    *,
    force: bool = False,
) -> Workshop:
    return apply_workshop_mutations(
        workspace,
        workshop_id,
        component_updates={component: content},
        append_components={component},
        reason=reason,
        force=force,
    )


def set_workshop_status(
    workspace: Workspace,
    workshop_id: str,
    status: str,
    reason: str,
    *,
    force: bool = False,
) -> Workshop:
    if not reason.strip():
        raise PlanledgerError("missing_reason", "Status changes require --reason.")
    return apply_workshop_mutations(
        workspace, workshop_id, status=status, reason=reason, force=force
    )


def snapshot_workshop_version(workshop: Workshop) -> Path:
    target = workshop_version_snapshot_dir(workshop, workshop.version)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        workshop_metadata_path_from_dir(workshop.path), target / "workshop.yaml"
    )
    shutil.copytree(workshop.path / "components", target / "components")
    _write_yaml(
        target / "manifest.yaml",
        {
            "workshop_id": workshop.workshop_id,
            "version": workshop.version,
            "status": workshop.status,
            "generated_at": now_iso(),
            "components": {
                k: {"path": v.path, "sha256": v.sha256}
                for k, v in sorted(
                    workshop.components.items(),
                    key=lambda item: (item[1].order, item[0]),
                )
            },
        },
    )
    return target


def list_workshop_versions(workshop: Workshop) -> list[str]:
    d = workshop_versions_dir(workshop)
    return [i.name for i in sorted(d.iterdir()) if i.is_dir()] if d.exists() else []


def diff_workshop_versions(
    workspace: Workspace, workshop_id: str, from_version: str, to_version: str
) -> str:
    workshop = load_workshop(workspace, workshop_id)
    fd = workshop_version_snapshot_dir(workshop, parse_version(from_version))
    td = workshop_version_snapshot_dir(workshop, parse_version(to_version))
    if not fd.exists():
        raise PlanledgerError(
            "not_found", f"Snapshot {from_version} does not exist for {workshop_id}."
        )
    if not td.exists():
        raise PlanledgerError(
            "not_found", f"Snapshot {to_version} does not exist for {workshop_id}."
        )
    import difflib

    lines: list[str] = []
    before = _snapshot_files(fd)
    after = _snapshot_files(td)
    for rel in sorted(set(before) | set(after)):
        lines.extend(
            difflib.unified_diff(
                before.get(rel, []),
                after.get(rel, []),
                fromfile=f"{from_version}/{rel}",
                tofile=f"{to_version}/{rel}",
            )
        )
    return "".join(lines) if lines else "No differences.\n"


def workshop_to_dict(
    workshop: Workshop, *, ledger_code: str = DEFAULT_LEDGER_CODE
) -> dict[str, Any]:
    ref = workshop_ref(workshop.workshop_id, ledger_code=ledger_code)
    return {
        "workshop_id": workshop.workshop_id,
        "id": workshop.workshop_id,
        "kind": WORKSHOP_KIND,
        "ledger_code": ref.ledger,
        "global_ref": ref.global_ref,
        "file_ref": ref.file_ref,
        "title": workshop.title,
        "status": workshop.status,
        "version": workshop.version,
        "path": str(workshop.path),
        "rendered_path": str(versioned_rendered_workshop_path(workshop)),
        "latest_rendered_path": str(latest_rendered_workshop_path(workshop)),
        "linked_plans": workshop.metadata.get("linked_plans", []),
        "components": {
            k: {
                "title": v.title,
                "path": v.path,
                "order": v.order,
                "required": v.required,
                "sha256": v.sha256,
            }
            for k, v in sorted(
                workshop.components.items(), key=lambda item: (item[1].order, item[0])
            )
        },
        "history": workshop.metadata.get("history", []),
    }


def workshop_status_counts(workspace: Workspace) -> dict[str, int]:
    counts: dict[str, int] = {}
    for w in list_workshops(workspace):
        counts[w.status] = counts.get(w.status, 0) + 1
    return counts


def create_plan_from_workshop(
    workspace: Workspace,
    workshop_id: str,
    *,
    title: str | None = None,
    allow_unshaped: bool = False,
    update_workshop_status: bool = True,
) -> tuple[Plan, Workshop]:
    workshop = load_workshop(workspace, workshop_id)
    contents = load_workshop_component_contents(workshop)
    if workshop.status != "shaped" and not allow_unshaped:
        raise PlanledgerError(
            "unshaped_workshop",
            f"Workshop {workshop.workshop_id} must be shaped before creating a plan.",
        )
    errors = validate_workshop(workshop, for_shaped=True)
    if errors and not allow_unshaped:
        raise PlanledgerError(
            "invalid_workshop",
            f"Workshop {workshop.workshop_id} is not shaped enough for planning.",
            remediation=errors,
        )
    ref = workshop_ref(workshop.workshop_id, ledger_code=workspace.ledger_code)
    plan_components = {
        "summary": f"Implementation plan derived from planning workshop `{workshop.workshop_id}` / `{ref.global_ref}`.\n\nWorkshop status: `{workshop.status}`.\n",
        "context": f"## Source workshop\n\n- Workshop: `{workshop.workshop_id}`\n- Ref: `{ref.global_ref}`\n- Title: {workshop.title}\n\n## Story\n\n{contents.get('story', '').strip()}\n\n## Accepted scenarios\n\n{contents.get('acceptance_scenarios', '').strip()}\n",
        "open_questions": "No unresolved required workshop questions at plan creation time.\n",
        "approach": "Draft from workshop scope and accepted scenarios. The coding agent must inspect repository files before finalizing target files.\n",
        "risks": contents.get("risks", ""),
    }
    plan = create_plan(
        workspace,
        title or f"Implement: {workshop.title}",
        f"Create an implementation plan from workshop {workshop.workshop_id} / {ref.global_ref}.",
        components=plan_components,
    )
    plan.metadata["source_workshop_id"] = workshop.workshop_id
    plan.metadata["source_workshop_ref"] = ref.global_ref
    save_plan_metadata(plan)
    pref = plan_ref(plan.plan_id, ledger_code=workspace.ledger_code)
    linked = workshop.metadata.setdefault("linked_plans", [])
    if isinstance(linked, list):
        linked.append(
            {
                "plan_id": plan.plan_id,
                "global_ref": pref.global_ref,
                "created_at": now_iso(),
                "reason": "Created implementation plan from shaped workshop.",
            }
        )
    save_workshop_metadata(workshop)
    if update_workshop_status and workshop.status == "shaped":
        workshop = set_workshop_status(
            workspace,
            workshop.workshop_id,
            "planned",
            "Created linked implementation plan.",
        )
    return load_plan(workspace, plan.plan_id), load_workshop(
        workspace, workshop.workshop_id
    )


# ---------------------------------------------------------------------------
# Inventory (read-only overview of everything planledger has stored)
# ---------------------------------------------------------------------------


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _component_fill_state(
    record_dir: Path, components: dict[str, ComponentSpec]
) -> tuple[dict[str, bool], int]:
    """Return ``({component_key: filled_bool}, filled_count)``.

    A component counts as filled when its component file is non-empty
    (``st_size > 0``). Missing files are treated as not filled, never raised.
    Component keys are emitted in canonical order.
    """
    filled: dict[str, bool] = {}
    filled_count = 0
    for key in ordered_component_keys(components):
        spec = components[key]
        is_filled = _file_size(record_dir / spec.path) > 0
        filled[key] = is_filled
        if is_filled:
            filled_count += 1
    return filled, filled_count


def _record_size_bytes(
    record_dir: Path,
    *,
    manifest_path: Path,
    components: dict[str, ComponentSpec],
    rendered_directory: Path,
) -> int:
    """Sum bytes for component files + rendered artifacts + the manifest.

    Version snapshots under ``versions/`` are intentionally excluded so the
    reported size stays stable as history grows. Missing files contribute 0.
    """
    total = _file_size(manifest_path)
    for spec in components.values():
        total += _file_size(record_dir / spec.path)
    if rendered_directory.exists():
        for path in sorted(rendered_directory.iterdir()):
            if path.is_file():
                total += _file_size(path)
    return total


def _iter_workshops_readonly(workspace: Workspace) -> list[Workshop]:
    """List workshops without triggering storage schema migration writes.

    Mirrors :func:`list_workshops` but walks the workshops directory directly
    and reads each manifest, so :func:`collect_inventory` stays read-only.
    """
    result: list[Workshop] = []
    directory = workshops_dir(workspace)
    if not directory.exists():
        return result
    for candidate in sorted(directory.iterdir()):
        metadata_path = workshop_metadata_path_from_dir(candidate)
        if not (candidate.is_dir() and metadata_path.exists()):
            continue
        try:
            metadata = _load_yaml(metadata_path)
            result.append(_workshop_from_metadata(candidate, metadata))
        except PlanledgerError:
            continue
    return result


def _status_counts_readonly(records: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
    return counts


def collect_inventory(workspace: Workspace) -> dict[str, Any]:
    """Build a read-only inventory of everything stored in this workspace.

    Reports workspace/config/storage paths, storage counters, status counts,
    a per-plan and per-workshop entry list (status, version, component
    fill-state, rendered artifact path, disk size), and the total disk
    footprint. Purely read-only: it never writes storage or migrates the
    schema, and tolerates missing components, unreadable storage, and empty
    workshops without raising.
    """
    ledger_code = ledger_code_from_config(workspace.config)

    try:
        data = storage_data(workspace)
        storage_readable = True
    except PlanledgerError:
        data = {}
        storage_readable = False

    project_name = workspace.project_name or workspace.root.name
    project_uuid = workspace.project_uuid

    plan_entries: list[dict[str, Any]] = []
    plans_total_size = 0
    for plan in list_plans(workspace):
        latest = latest_rendered_path(plan)
        fill_state, filled_count = _component_fill_state(plan.path, plan.components)
        base = plan_to_dict(plan, ledger_code=ledger_code)
        size = _record_size_bytes(
            plan.path,
            manifest_path=plan_metadata_path_from_dir(plan.path),
            components=plan.components,
            rendered_directory=rendered_dir(plan),
        )
        plans_total_size += size
        plan_entries.append(
            {
                "plan_id": base["plan_id"],
                "id": base["id"],
                "global_ref": base["global_ref"],
                "file_ref": base["file_ref"],
                "title": base["title"],
                "status": base["status"],
                "version": base["version"],
                "path": base["path"],
                "latest_rendered_path": str(latest),
                "latest_rendered_exists": latest.exists(),
                "components": fill_state,
                "filled_components": filled_count,
                "total_components": len(fill_state),
                "versions": list_versions(plan),
                "size_bytes": size,
            }
        )

    workshops = _iter_workshops_readonly(workspace)
    workshop_entries: list[dict[str, Any]] = []
    workshops_total_size = 0
    for workshop in workshops:
        latest = latest_rendered_workshop_path(workshop)
        fill_state, filled_count = _component_fill_state(
            workshop.path, workshop.components
        )
        base = workshop_to_dict(workshop, ledger_code=ledger_code)
        size = _record_size_bytes(
            workshop.path,
            manifest_path=workshop_metadata_path_from_dir(workshop.path),
            components=workshop.components,
            rendered_directory=workshop_rendered_dir(workshop),
        )
        workshops_total_size += size
        workshop_entries.append(
            {
                "workshop_id": base["workshop_id"],
                "id": base["id"],
                "global_ref": base["global_ref"],
                "file_ref": base["file_ref"],
                "title": base["title"],
                "status": base["status"],
                "version": base["version"],
                "path": base["path"],
                "latest_rendered_path": str(latest),
                "latest_rendered_exists": latest.exists(),
                "components": fill_state,
                "filled_components": filled_count,
                "total_components": len(fill_state),
                "versions": list_workshop_versions(workshop),
                "size_bytes": size,
            }
        )

    total_size = plans_total_size + workshops_total_size

    return {
        "initialized": True,
        "workspace": {
            "root": str(workspace.root),
            "project_root": str(workspace.project_root),
            "config_path": str(workspace.config_path),
            "manifest_path": str(workspace.manifest_path),
            "local_config_path": str(workspace.local_config_path),
            "planledger_dir": str(workspace.planledger_dir),
            "storage_path": str(workspace.storage_path),
            "project_name": project_name,
            "project_uuid": project_uuid,
            "ledger_code": ledger_code,
            "workspace_provider": workspace.workspace_provider,
            "store_root": str(workspace.store_root),
            "store_marker_path": str(workspace.store_marker_path),
            "active_mount": workspace.active_mount_name,
            "mount_storage": workspace.mount_storage,
            "mount_scope": workspace.mount_scope,
            "mount_source": workspace.mount_source,
            "binding_path": str(workspace.binding_path),
        },
        "storage": {
            "readable": storage_readable,
            "schema_version": data.get("schema_version"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "active_plan_id": data.get("active_plan_id") or None,
            "active_workshop_id": data.get("active_workshop_id") or None,
        },
        "allocations": {
            "highest_plan_id": scan_plan_allocations(workspace).allocations[-1].local_id
            if scan_plan_allocations(workspace).allocations
            else None,
            "next_plan_id": scan_plan_allocations(workspace).next_id,
            "highest_workshop_id": scan_workshop_allocations(workspace)
            .allocations[-1]
            .local_id
            if scan_workshop_allocations(workspace).allocations
            else None,
            "next_workshop_id": scan_workshop_allocations(workspace).next_id,
        },
        "plan_status_counts": plan_status_counts(workspace),
        "workshop_status_counts": _status_counts_readonly(workshops),
        "plan_count": len(plan_entries),
        "workshop_count": len(workshop_entries),
        "plans": plan_entries,
        "workshops": workshop_entries,
        "size_bytes": {
            "plans": plans_total_size,
            "workshops": workshops_total_size,
            "total": total_size,
        },
        "total_size_bytes": total_size,
    }
