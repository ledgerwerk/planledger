# planledger

Planledger stores independent, structured, versioned implementation plans and renders each plan into one standalone rendered Markdown handoff file.

## Product contract

- Planledger stores plans only.
- Each plan is independent.
- The main user is a coding agent through `skills/planledger/SKILL.md`.
- A done plan must contain todo items, acceptance criteria, target files, and validation commands.
- Planledger has no external task-manager integration.

## What it does

- stores independent plans under the configured Planledger storage directory, for example `.planledger/plans/plan-0001/` or `../planledger-state/planledger/plans/plan-0001/`;
- versions every meaningful plan change;
- keeps each plan as modular component files;
- renders a standalone Markdown artifact for human or coding-agent handoff;
- enforces handoff quality guardrails before a plan can be marked `done`.

planledger is not a task manager, does not store goals, and has no external task-manager integration.

## Release maturity

Planledger is currently a beta package (`Development Status :: 4 - Beta`). It is intended for planning-only workflows and standalone handoff artifacts. Beta status means the project is suitable for early adopter use, but releases should pass the documented maintainer gate before publication.

## Install

```bash
pip install -e .
```

## Quick start for coding agents

The CLI is the only supported mutation path. The rendered Markdown artifact is the deliverable.

````bash
# Check workspace state
planledger status
planledger status --check

# Initialize if needed
planledger init

# Create a new independent plan. The new plan becomes active.
planledger plan create --title "Add feature A" --request "Please review how we can add feature A."

# Populate components on the active plan (inspect repository files first)
planledger plan component set context --file context.md
planledger plan component set approach --file approach.md
planledger plan component set todo_items --file todos.md
planledger plan component set target_files --file target_files.md
planledger plan component set validation --file validation.md
planledger plan component set risks --file risks.md

# Override the active plan when needed
planledger plan show --plan plan-0001
planledger plan activate plan-0001

# Build, validate, mark done
planledger plan build
planledger plan validate
planledger plan status done --reason "Ready for coding agent handoff."

# Export rendered plan to workspace root for the harness
planledger plan export

New planning request equals new independent plan unless the user names an existing `plan-000X`.

## Todo item template

Every todo item in the `todo_items` component should follow this structure:

```md
### TODO-001: <action-oriented title>

**Target files**

- [`path/to/file.py`](path/to/file.py) — why this file changes.

**Acceptance criteria**

- [ ] Observable outcome.
- [ ] Regression or edge case covered.

**Validation**

- `python -m pytest path/to/test_file.py -q`
````

## Handoff quality guardrails

`done` is a handoff-readiness state, not an implementation-completed state. A plan cannot be marked `done` unless:

- `todo_items` contains at least one `### TODO-NNN` heading.
- Every todo item has an **Acceptance criteria** section with at least one checkbox.
- Every todo item has a **Target files** section with at least one file reference.
- `target_files` contains at least one repo-relative file path or Markdown link.
- `validation` contains at least one validation command.
- No required component contains placeholder content (`TBD`, `TODO:`, `<fill>`, etc.).
- `open_questions` contains no unresolved required questions (`- [ ] REQUIRED:`).

Plan validation means the plan artifact is structurally ready for handoff. It does not mean implementation tests have passed.

## Plan components

Each plan stores these components:

| Component        | Required | Description                      |
| ---------------- | -------- | -------------------------------- |
| `request`        | yes      | Original human request           |
| `summary`        | yes      | Executive verdict                |
| `context`        | yes      | Repository context and evidence  |
| `open_questions` | no       | Unresolved questions             |
| `assumptions`    | no       | Assumed facts                    |
| `approach`       | yes      | Proposed implementation approach |
| `todo_items`     | yes      | Structured todo items            |
| `target_files`   | yes      | Files that will change           |
| `validation`     | yes      | Validation plan and commands     |
| `risks`          | yes      | Risks and mitigations            |
| `rollback`       | no       | Rollback or repair strategy      |
| `notes`          | no       | Additional notes                 |

## Rendered Markdown example

```md
---
planledger_schema: planledger.rendered_plan.v1
plan_id: plan-0003
title: Add feature A
status: done
version: 5
generated_at: 2026-06-09T12:00:00Z
---

# Add feature A

Plan: `plan-0003`
Version: `v0005`
Status: `done`

## Executive verdict

**Ready for coding-agent implementation.**

One paragraph summarizing the decision and scope.

## Repository context and evidence

| Area | Finding                                                   | Evidence                                  |
| ---- | --------------------------------------------------------- | ----------------------------------------- |
| CLI  | Current command implementation is in `planledger/cli.py`. | Function `plan_create`, `plan_build`, ... |

## Proposed approach

Explain the design and why it is acceptable.

## Todo items

### TODO-001: Implement feature A

**Target files**

- [`planledger/cli.py`](planledger/cli.py)

**Acceptance criteria**

- [ ] CLI exposes the new behavior.

**Validation**

- `python -m pytest -q`
```

## Filesystem layout

```text
<configured planledger_dir>/
  storage.yaml
  plans/
    plan-0001/
      plan.yaml
      components/
      rendered/
      versions/
```

The config file may be `planledger.toml` or `.planledger.toml`. `storage.planledger_dir` is resolved relative to the config root when it is a relative path, so sibling storage such as `../planledger-state/planledger` is valid.

## CLI surface

```text
planledger init [--project-name NAME] [--planledger-dir .planledger] [--hidden-config]
planledger status [--check] [--json]
planledger doctor [--json]
planledger next-action [PLAN_ID] [--json]

planledger plan create --title TITLE [--request TEXT | --request-file PATH | --stdin] [--status new|in_progress]
planledger plan activate PLAN_ID
planledger plan list [--status STATUS] [--json]
planledger plan show [PLAN_ID] [--plan PLAN_ID] [--component KEY] [--rendered] [--json]
planledger plan status [PLAN_ID] [--plan PLAN_ID] STATUS --reason TEXT
planledger plan cancel [PLAN_ID] [--plan PLAN_ID] --reason TEXT
planledger plan component list [PLAN_ID] [--plan PLAN_ID] [--json]
planledger plan component show COMPONENT [--plan PLAN_ID]
planledger plan component set COMPONENT [--plan PLAN_ID] (--text TEXT | --file PATH | --stdin) [--reason TEXT]
planledger plan component append COMPONENT [--plan PLAN_ID] (--text TEXT | --file PATH | --stdin) [--reason TEXT]
planledger plan build [PLAN_ID] [--plan PLAN_ID] [--out PATH] [--print] [--include-empty] [--json]
planledger plan export [PLAN_ID] [--plan PLAN_ID] [--out PATH] [--include-empty] [--json]
planledger plan validate [PLAN_ID] [--plan PLAN_ID] [--json]
planledger plan versions [PLAN_ID] [--plan PLAN_ID] [--json]
planledger plan diff [PLAN_ID] [--plan PLAN_ID] --from v0001 --to v0002
planledger plan apply --file PATH_OR_DASH [--dry-run]
```

## Structured bundle workflow

Agents can create or update plans through `planledger.structured_plan.v1` bundles:

```bash
planledger plan apply --file plan.json --dry-run
planledger plan apply --file plan.json
```

## Stdin input

Component commands and `plan create` accept `--stdin` and `--file -` for multiline
input without temporary files:

```bash
cat <<'MD' | planledger plan component set context --stdin --reason "Record evidence."
Repository evidence...
MD

cat <<'JSON' | planledger plan apply --file -
{ "schema": "planledger.structured_plan.v1", ... }
JSON
```

## Plan export

`planledger plan export` writes the rendered Markdown to a workspace-root-relative
path (default `WORKSPACE_ROOT/PLAN_ID.md`). This is the recommended final handoff
step because the configured Planledger storage directory may be outside the source
workspace.

```bash
planledger plan export --plan plan-0004
# writes: ./plan-0004.md
```

## Development

```bash
python -m pytest
python -m ruff check .
python -m mypy planledger
```
