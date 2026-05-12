from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import yaml

from planledger.errors import PlanledgerError
from planledger.models import AppContext, Record, Workspace

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


RECORD_DIRS: dict[str, str] = {
    "goal": "goals",
    "initiative": "initiatives",
    "plan": "plans",
    "milestone": "milestones",
    "slice": "slices",
    "decision": "decisions",
    "option": "options",
    "assumption": "assumptions",
    "risk": "risks",
    "constraint": "constraints",
    "question": "questions",
    "binding": "bindings",
    "review": "reviews",
    "event": "events",
    "run": "runs",
}
ID_PREFIXES: dict[str, str] = {
    "goal": "goal",
    "initiative": "init",
    "plan": "plan",
    "milestone": "ms",
    "slice": "slice",
    "decision": "dec",
    "option": "opt",
    "assumption": "asm",
    "risk": "risk",
    "constraint": "con",
    "question": "q",
    "binding": "bind",
    "review": "review",
    "event": "event",
    "run": "run",
}
DEFAULT_NEXT_IDS: dict[str, int] = {
    "goal": 1,
    "initiative": 1,
    "plan": 1,
    "milestone": 1,
    "slice": 1,
    "decision": 1,
    "option": 1,
    "assumption": 1,
    "risk": 1,
    "constraint": 1,
    "question": 1,
    "binding": 1,
    "review": 1,
    "event": 1,
    "run": 1,
}
PLANLEDGER_CONFIG_FILENAMES: tuple[str, str] = (".planledger.toml", "planledger.toml")
DEFAULT_PLANLEDGER_CONFIG_FILENAME = "planledger.toml"
PLAN_TEMPLATE = """# Plan

## Context

## Objectives

## Non-goals

## Milestones

## Slices

## Decisions

## Risks

## Validation strategy

## Rollback or repair strategy
"""


def _record_reference(record: Record) -> str:
    title = str(record.front_matter.get("title") or "").strip()
    if title:
        return f"{record.record_id} — {title}"
    return record.record_id


def render_plan_template(
    initiative: Record,
    goal: Record | None,
    version: int,
) -> str:
    initiative_title = str(initiative.front_matter.get("title") or initiative.record_id)
    goal_reference = _record_reference(goal) if goal is not None else "not recorded"
    initiative_reference = _record_reference(initiative)
    return f"""# Plan: {initiative_title}

## Context

- Goal: {goal_reference}
- Initiative: {initiative_reference}
- Version: v{version}

## Objectives

- Define the milestones and slices needed to deliver this initiative.

## Non-goals

## Milestones

## Slices

## Decisions

## Risks

## Validation strategy

## Rollback or repair strategy
"""


DECISION_TEMPLATE = """# Decision

## Context

## Chosen option

## Rationale

## Consequences

## Follow-up
"""

OPTION_TEMPLATE = """# Option

## Summary

## Pros

## Cons

## Risks

## Implementation notes
"""
ADR_TEMPLATE = "# Architectural Decision\n\n## Context\n\n## Decision\n\n## Alternatives considered\n\n## Consequences\n\n## Follow-up\n\n## Evidence\n"


@dataclass
class LintResult:
    issues: list[str]

    @property
    def ok(self) -> bool:
        return not self.issues


def now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _dump_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise PlanledgerError(
            "invalid_yaml",
            f"Expected mapping in {path}.",
            remediation=[f"Inspect and repair: {path}"],
        )
    return loaded


def parse_front_matter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n"):
        raise PlanledgerError(
            "invalid_record",
            "Front matter delimiter missing at document start.",
        )
    end = content.find("\n---\n", 4)
    if end == -1:
        raise PlanledgerError(
            "invalid_record", "Closing front matter delimiter not found."
        )
    front_text = content[4:end]
    body = content[end + 5 :]
    front = yaml.safe_load(front_text) or {}
    if not isinstance(front, dict):
        raise PlanledgerError("invalid_record", "Front matter must be a mapping.")
    return front, body


def render_front_matter(front: dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip("\n")
    if body:
        return f"---\n{yaml_text}\n---\n{body}"
    return f"---\n{yaml_text}\n---\n"


def write_markdown(path: Path, front: dict[str, Any], body: str) -> None:
    for field_name in ("id", "type", "created_at", "updated_at"):
        if field_name not in front:
            raise PlanledgerError(
                "invalid_record",
                f"Missing required field '{field_name}' for {path.name}.",
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_front_matter(front, body), encoding="utf-8")


def read_markdown(path: Path, kind: str) -> Record:
    if not path.exists():
        raise PlanledgerError(
            "not_found",
            f"No {kind} found for ref {path.stem}.",
            remediation=[f"Run: planledger {kind} list"],
        )
    front, body = parse_front_matter(path.read_text(encoding="utf-8"))
    record_id = str(front.get("id", path.stem))
    return Record(
        kind=kind, record_id=record_id, path=path, front_matter=front, body=body
    )


def _record_path(
    workspace: Workspace, kind: str, record_id: str, ext: str = "md"
) -> Path:
    dir_name = RECORD_DIRS[kind]
    return workspace.ledger_dir / dir_name / f"{record_id}.{ext}"


def list_records(workspace: Workspace, kind: str) -> list[Record]:
    target_dir = workspace.ledger_dir / RECORD_DIRS[kind]
    if not target_dir.exists():
        return []
    records = [read_markdown(path, kind) for path in sorted(target_dir.glob("*.md"))]
    return records


def load_record(workspace: Workspace, kind: str, record_id: str) -> Record:
    return read_markdown(_record_path(workspace, kind, record_id), kind)


def save_record(record: Record) -> None:
    write_markdown(record.path, record.front_matter, record.body)


def update_record_timestamp(record: Record) -> None:
    record.front_matter["updated_at"] = now_iso()


def create_record(
    workspace: Workspace,
    kind: str,
    front_matter: dict[str, Any],
    body: str,
) -> Record:
    record_id = str(front_matter["id"])
    path = _record_path(workspace, kind, record_id)
    write_markdown(path, front_matter, body)
    return Record(
        kind=kind,
        record_id=record_id,
        path=path,
        front_matter=front_matter,
        body=body,
    )


def storage_data(workspace: Workspace) -> dict[str, Any]:
    return _load_yaml(workspace.storage_path)


def save_storage_data(workspace: Workspace, data: dict[str, Any]) -> None:
    _dump_yaml(workspace.storage_path, data)


def allocate_id(workspace: Workspace, kind: str) -> str:
    if kind not in ID_PREFIXES:
        raise PlanledgerError("invalid_kind", f"Unknown ID kind: {kind}")
    data = storage_data(workspace)
    next_ids = data.setdefault("next_ids", {})
    value = int(next_ids.get(kind, 1))
    prefix = ID_PREFIXES[kind]
    allocated = f"{prefix}-{value:04d}"
    next_ids[kind] = value + 1
    save_storage_data(workspace, data)
    return allocated


def _safe_event_command(command: str, max_chars: int = 600) -> str:
    safe = command.strip()
    if not safe:
        return safe
    safe = re.sub(
        r'(--description)(?:=|\s+)(\"[^\"]*\"|\'[^\']*\'|\S+)',
        r"\1 <omitted>",
        safe,
    )
    if len(safe) > max_chars:
        return safe[:max_chars] + "... (truncated)"
    return safe


def _safe_external_command_metadata(
    metadata: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if metadata is None:
        return None
    safe = dict(metadata)
    command_value = safe.get("command")
    if isinstance(command_value, str):
        safe["command"] = _safe_event_command(command_value)
    args = safe.get("args")
    if isinstance(args, list):
        sanitized: list[Any] = []
        skip_next = False
        for token in args:
            if skip_next:
                sanitized.append("<omitted>")
                skip_next = False
                continue
            if not isinstance(token, str):
                sanitized.append(token)
                continue
            if token == "--description":
                sanitized.append(token)
                skip_next = True
                continue
            if token.startswith("--description="):
                sanitized.append("--description=<omitted>")
                continue
            sanitized.append(token)
        safe["args"] = sanitized
    return safe


def append_event(
    workspace: Workspace,
    command: str,
    object_type: str,
    object_id: str,
    event_type: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    actor: str = "human",
    source_run: str | None = None,
    provenance: str | None = None,
    correlation_id: str | None = None,
    external_command: dict[str, Any] | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    event_id = allocate_id(workspace, "event")
    payload: dict[str, Any] = {
        "id": event_id,
        "timestamp": now_iso(),
        "actor": actor,
        "command": _safe_event_command(command),
        "object_type": object_type,
        "object_id": object_id,
        "event_type": event_type,
    }
    if before is not None:
        payload["before"] = before
    if after is not None:
        payload["after"] = after
    if details is not None:
        payload["details"] = details
    if source_run is not None:
        payload["source_run"] = source_run
    if provenance is not None:
        payload["provenance"] = provenance
    if correlation_id is not None:
        payload["correlation_id"] = correlation_id
    safe_external = _safe_external_command_metadata(external_command)
    if safe_external is not None:
        payload["external_command"] = safe_external
    if duration_ms is not None:
        payload["duration_ms"] = duration_ms
    _dump_yaml(
        _record_path(workspace, "event", event_id, ext="yaml"),
        payload,
    )
    return payload


def list_events(
    workspace: Workspace,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    events_dir = workspace.ledger_dir / "events"
    if not events_dir.exists():
        return []
    events: list[dict[str, Any]] = []
    paths = sorted(events_dir.glob("*.yaml"))
    if limit is not None:
        paths = paths[-limit:]
    for path in paths:
        data = _load_yaml(path)
        data["_path"] = str(path)
        events.append(data)
    return events


def find_config_path(root: Path) -> Path | None:
    for filename in PLANLEDGER_CONFIG_FILENAMES:
        candidate = root / filename
        if candidate.exists():
            return candidate
    return None


def require_config_path(root: Path) -> Path:
    config_path = find_config_path(root)
    if config_path is None:
        names = " or ".join(PLANLEDGER_CONFIG_FILENAMES)
        raise PlanledgerError(
            "not_initialized",
            f"No {names} found under {root}.",
            remediation=['Run: planledger init --project-name "Your Project"'],
        )
    return config_path


def write_config(
    root: Path,
    project_name: str,
    project_uuid: str,
    planledger_dir: str = ".planledger",
    config_filename: str = DEFAULT_PLANLEDGER_CONFIG_FILENAME,
) -> None:
    if config_filename not in PLANLEDGER_CONFIG_FILENAMES:
        raise PlanledgerError(
            "invalid_config_filename",
            f"Unsupported planledger config filename: {config_filename}",
            remediation=[f"Use one of: {', '.join(PLANLEDGER_CONFIG_FILENAMES)}"],
        )
    config_text = (
        "[project]\n"
        f'name = "{project_name}"\n'
        f'uuid = "{project_uuid}"\n\n'
        "[storage]\n"
        f'planledger_dir = "{planledger_dir}"\n'
        'ledger_ref = "main"\n\n'
        "[integrations.taskledger]\n"
        "enabled = true\n"
        'workspace_root = "."\n'
        'command = "taskledger"\n'
    )
    (root / config_filename).write_text(config_text, encoding="utf-8")


def initialize_project(
    root: Path,
    project_name: str,
    planledger_dir: str = ".planledger",
    config_filename: str = DEFAULT_PLANLEDGER_CONFIG_FILENAME,
) -> Workspace:
    if find_config_path(root) is not None:
        raise PlanledgerError(
            "already_initialized",
            f"planledger is already initialized at {root}.",
            remediation=["Run: planledger status"],
        )

    project_uuid = str(uuid4())
    write_config(
        root,
        project_name,
        project_uuid,
        planledger_dir=planledger_dir,
        config_filename=config_filename,
    )

    plan_dir = root / planledger_dir
    ledger_ref = "main"
    ledger_dir = plan_dir / "ledgers" / ledger_ref

    for directory in RECORD_DIRS.values():
        (ledger_dir / directory).mkdir(parents=True, exist_ok=True)

    storage = {
        "schema_version": 1,
        "project_uuid": project_uuid,
        "current_ledger": ledger_ref,
        "next_ids": dict(DEFAULT_NEXT_IDS),
    }
    _dump_yaml(plan_dir / "storage.yaml", storage)
    _dump_yaml(ledger_dir / "indexes" / "active.yaml", {"active_initiative": None})

    return load_workspace_from_root(root)


def discover_project_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if find_config_path(candidate) is not None:
            return candidate
    return None


def workspace_root_from_context(context: AppContext, init_mode: bool = False) -> Path:
    if context.root is not None:
        return context.root.resolve()
    if context.cwd is not None:
        chosen = context.cwd.resolve()
        if init_mode:
            return chosen
        found = discover_project_root(chosen)
        if found is not None:
            return found
        return chosen
    here = Path.cwd().resolve()
    if init_mode:
        return here
    found = discover_project_root(here)
    return found or here


def _validate_workspace_files(root: Path) -> None:
    require_config_path(root)


def load_workspace_from_root(root: Path) -> Workspace:
    _validate_workspace_files(root)
    config_path = require_config_path(root)
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    storage_section = dict(config.get("storage", {}))
    planledger_dir_name = str(storage_section.get("planledger_dir", ".planledger"))
    planledger_dir = root / planledger_dir_name
    ledger_ref = str(storage_section.get("ledger_ref", "main"))
    storage_path = planledger_dir / "storage.yaml"
    if not storage_path.exists():
        raise PlanledgerError(
            "missing_storage",
            f"Missing storage metadata: {storage_path}",
            remediation=["Run: planledger doctor"],
        )
    ledger_dir = planledger_dir / "ledgers" / ledger_ref
    if not ledger_dir.exists():
        raise PlanledgerError(
            "missing_ledger",
            f"Missing ledger directory: {ledger_dir}",
            remediation=["Run: planledger doctor"],
        )
    return Workspace(
        root=root,
        config_path=config_path,
        planledger_dir=planledger_dir,
        storage_path=storage_path,
        ledger_ref=ledger_ref,
        ledger_dir=ledger_dir,
        config=config,
    )


def load_workspace(context: AppContext, init_mode: bool = False) -> Workspace:
    root = workspace_root_from_context(context, init_mode=init_mode)
    if not init_mode:
        root = discover_project_root(root) or root
    return load_workspace_from_root(root)


def active_index_path(workspace: Workspace) -> Path:
    return workspace.ledger_dir / "indexes" / "active.yaml"


def active_initiative(workspace: Workspace) -> str | None:
    path = active_index_path(workspace)
    if path.exists():
        data = _load_yaml(path)
        value = data.get("active_initiative")
        if value:
            return str(value)
    for initiative in list_records(workspace, "initiative"):
        if initiative.front_matter.get("active") is True:
            return initiative.record_id
    return None


def set_active_initiative(workspace: Workspace, initiative_id: str | None) -> None:
    initiatives = list_records(workspace, "initiative")
    found = initiative_id is None
    for initiative in initiatives:
        is_active = initiative_id is not None and initiative.record_id == initiative_id
        if is_active:
            found = True
        if initiative.front_matter.get("active") != is_active:
            initiative.front_matter["active"] = is_active
            update_record_timestamp(initiative)
            save_record(initiative)
    if not found and initiative_id is not None:
        raise PlanledgerError(
            "not_found",
            f"No initiative found for ref {initiative_id}.",
            remediation=["Run: planledger initiative list"],
        )
    _dump_yaml(active_index_path(workspace), {"active_initiative": initiative_id})


def latest_plan_for_initiative(
    workspace: Workspace, initiative_id: str
) -> Record | None:
    plans = [
        plan
        for plan in list_records(workspace, "plan")
        if plan.front_matter.get("initiative") == initiative_id
    ]
    if not plans:
        return None
    plans.sort(key=lambda p: int(p.front_matter.get("version", 0)), reverse=True)
    return plans[0]


def next_plan_version(workspace: Workspace, initiative_id: str) -> int:
    latest = latest_plan_for_initiative(workspace, initiative_id)
    if latest is None:
        return 1
    return int(latest.front_matter.get("version", 0)) + 1


def slugify(text: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in text)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "task"


def milestone_for_slice(workspace: Workspace, milestone_id: str) -> Record:
    return load_record(workspace, "milestone", milestone_id)


def plan_for_milestone(workspace: Workspace, milestone: Record) -> Record:
    plan_id = str(milestone.front_matter.get("plan"))
    return load_record(workspace, "plan", plan_id)


def initiative_for_plan(workspace: Workspace, plan: Record) -> Record:
    initiative_id = str(plan.front_matter.get("initiative"))
    return load_record(workspace, "initiative", initiative_id)


def parse_ref_numeric(record_id: str) -> int:
    suffix = record_id.rsplit("-", 1)[-1]
    try:
        return int(suffix)
    except ValueError:
        return 0


def lint_plan(workspace: Workspace, plan: Record) -> LintResult:
    body = plan.body
    issues: list[str] = []
    slices = [
        item
        for item in list_records(workspace, "slice")
        if item.front_matter.get("plan") == plan.record_id
    ]

    if "## Context" not in body:
        issues.append("Missing section: Context")
    else:
        context_start = body.index("## Context") + len("## Context")
        next_heading = body.find("\n## ", context_start)
        context_text = (
            body[context_start:next_heading]
            if next_heading != -1
            else body[context_start:]
        )
        if "Goal:" not in context_text:
            issues.append("Context section missing goal reference.")
        if "Initiative:" not in context_text:
            issues.append("Context section missing initiative reference.")
    if "## Objectives" not in body:
        issues.append("Missing section: Objectives")
    else:
        obj_start = body.index("## Objectives") + len("## Objectives")
        obj_next = body.find("\n## ", obj_start)
        objectives_text = (
            body[obj_start:obj_next] if obj_next != -1 else body[obj_start:]
        ).strip()
        if not objectives_text:
            issues.append("Objectives section is empty.")

    milestones = [
        item
        for item in list_records(workspace, "milestone")
        if item.front_matter.get("plan") == plan.record_id
    ]
    if not milestones:
        issues.append("Plan has no milestones.")
    else:
        for ms in milestones:
            ms_slices = [
                s for s in slices if s.front_matter.get("milestone") == ms.record_id
            ]
            if not ms_slices:
                issues.append(f"Milestone {ms.record_id} has no slices.")

    if not slices:
        issues.append("Plan has no slices.")

    initiative_id = str(plan.front_matter.get("initiative"))
    open_decisions = [
        item
        for item in list_records(workspace, "decision")
        if item.front_matter.get("initiative") == initiative_id
        and item.front_matter.get("status") == "open"
    ]
    if open_decisions:
        issues.append("Initiative has open decisions.")

    high_risks = [
        risk
        for risk in list_records(workspace, "risk")
        if risk.front_matter.get("initiative") == initiative_id
        and risk.front_matter.get("impact") == "high"
        and risk.front_matter.get("status") == "open"
        and not str(risk.front_matter.get("mitigation") or "").strip()
    ]
    if high_risks:
        issues.append("Open high-impact risks require mitigation.")

    return LintResult(issues=issues)


def record_counts(workspace: Workspace) -> dict[str, int]:
    return {
        kind: len(list_records(workspace, kind))
        for kind in (
            "goal",
            "initiative",
            "plan",
            "milestone",
            "slice",
            "decision",
            "option",
            "risk",
            "binding",
        )
    }


def reindex(workspace: Workspace) -> dict[str, Any]:
    active = active_initiative(workspace)
    _dump_yaml(active_index_path(workspace), {"active_initiative": active})
    counts = record_counts(workspace)
    summary_path = workspace.ledger_dir / "indexes" / "summary.yaml"
    _dump_yaml(summary_path, {"generated_at": now_iso(), "counts": counts})
    return {
        "active_initiative": active,
        "counts": counts,
        "summary_index": str(summary_path.relative_to(workspace.root)),
    }


def doctor(workspace: Workspace) -> dict[str, Any]:
    issues: list[str] = []
    if not workspace.config_path.exists():
        issues.append(f"Missing {workspace.config_path.name}")
    if not workspace.storage_path.exists():
        issues.append("Missing .planledger/storage.yaml")

    for dir_name in RECORD_DIRS.values():
        path = workspace.ledger_dir / dir_name
        if not path.exists():
            issues.append(f"Missing directory: {path.relative_to(workspace.root)}")

    active = active_initiative(workspace)
    if active is not None:
        try:
            load_record(workspace, "initiative", active)
        except PlanledgerError:
            issues.append(f"Active initiative {active} does not exist")

    # Referential integrity checks
    all_records: dict[str, dict[str, Record]] = {}
    for kind in RECORD_DIRS:
        all_records[kind] = {r.record_id: r for r in list_records(workspace, kind)}

    for init_record in all_records["initiative"].values():
        goal_ref = init_record.front_matter.get("goal")
        if goal_ref and goal_ref not in all_records["goal"]:
            issues.append(
                f"Initiative {init_record.record_id} references missing goal {goal_ref}"
            )

    for plan_record in all_records["plan"].values():
        init_ref = plan_record.front_matter.get("initiative")
        if init_ref and init_ref not in all_records["initiative"]:
            issues.append(
                f"Plan {plan_record.record_id} references missing initiative {init_ref}"
            )

    for ms_record in all_records["milestone"].values():
        plan_ref = ms_record.front_matter.get("plan")
        if plan_ref and plan_ref not in all_records["plan"]:
            issues.append(
                f"Milestone {ms_record.record_id} references missing plan {plan_ref}"
            )

    for slice_record in all_records["slice"].values():
        ms_ref = slice_record.front_matter.get("milestone")
        if ms_ref and ms_ref not in all_records["milestone"]:
            issues.append(
                f"Slice {slice_record.record_id} references missing milestone {ms_ref}"
            )

    for opt_record in all_records["option"].values():
        dec_ref = opt_record.front_matter.get("decision")
        if dec_ref and dec_ref not in all_records["decision"]:
            issues.append(
                f"Option {opt_record.record_id} references missing decision {dec_ref}"
            )

    return {
        "kind": "planledger_doctor",
        "healthy": not issues,
        "issues": issues,
    }
