from __future__ import annotations

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
    "event": "event",
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
    "event": 1,
}

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


def append_event(
    workspace: Workspace,
    command: str,
    object_type: str,
    object_id: str,
    event_type: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_id = allocate_id(workspace, "event")
    payload: dict[str, Any] = {
        "id": event_id,
        "timestamp": now_iso(),
        "actor": "human",
        "command": command,
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
    _dump_yaml(_record_path(workspace, "event", event_id, ext="yaml"), payload)
    return payload


def write_config(
    root: Path,
    project_name: str,
    project_uuid: str,
    planledger_dir: str = ".planledger",
) -> None:
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
    (root / "planledger.toml").write_text(config_text, encoding="utf-8")


def initialize_project(
    root: Path,
    project_name: str,
    planledger_dir: str = ".planledger",
) -> Workspace:
    config_path = root / "planledger.toml"
    if config_path.exists():
        raise PlanledgerError(
            "already_initialized",
            f"planledger is already initialized at {root}.",
            remediation=["Run: planledger status"],
        )

    project_uuid = str(uuid4())
    write_config(root, project_name, project_uuid, planledger_dir=planledger_dir)

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
        if (candidate / "planledger.toml").exists():
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
    if not (root / "planledger.toml").exists():
        raise PlanledgerError(
            "not_initialized",
            f"No planledger.toml found under {root}.",
            remediation=['Run: planledger init --project-name "Your Project"'],
        )


def load_workspace_from_root(root: Path) -> Workspace:
    _validate_workspace_files(root)
    config_path = root / "planledger.toml"
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


def set_active_initiative(workspace: Workspace, initiative_id: str) -> None:
    initiatives = list_records(workspace, "initiative")
    found = False
    for initiative in initiatives:
        is_active = initiative.record_id == initiative_id
        if is_active:
            found = True
        if initiative.front_matter.get("active") != is_active:
            initiative.front_matter["active"] = is_active
            update_record_timestamp(initiative)
            save_record(initiative)
    if not found:
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
    if "## Context" not in body:
        issues.append("Missing section: Context")
    if "## Objectives" not in body:
        issues.append("Missing section: Objectives")

    milestones = [
        item
        for item in list_records(workspace, "milestone")
        if item.front_matter.get("plan") == plan.record_id
    ]
    if not milestones:
        issues.append("Plan has no milestones.")

    slices = [
        item
        for item in list_records(workspace, "slice")
        if item.front_matter.get("plan") == plan.record_id
    ]
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
        issues.append("Missing planledger.toml")
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

    return {
        "kind": "planledger_doctor",
        "healthy": not issues,
        "issues": issues,
    }
