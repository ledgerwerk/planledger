# planledger

Planledger stores independent, structured, versioned implementation plans and renders each plan into one standalone rendered Markdown handoff file.

## Product contract

- Planledger stores plans only.
- Each plan is independent.
- The main user is a coding agent through `skills/planledger/SKILL.md`.
- A done plan must contain todo items, acceptance criteria, target files, and validation commands.
- Planledger has no external task-manager integration.

## What it does

- stores independent plans under `.planledger/plans/plan-0001/`;
- versions every meaningful plan change;
- keeps each plan as modular component files;
- renders a standalone Markdown artifact for human or coding-agent handoff;
- enforces handoff quality guardrails before a plan can be marked `done`.

planledger is not a task manager, does not store goals, and has no external task-manager integration.

## Install

```bash
pip install -e .
```

## Quick start for coding agents

```bash
planledger init
planledger plan create --title "Add feature A" --request "Please review how we can add feature A. Ask me questions when something is not clear."
planledger plan component set plan-0001 context --file context.md
planledger plan component set plan-0001 approach --file approach.md
planledger plan component set plan-0001 todo_items --file todos.md
planledger plan component set plan-0001 target_files --file target_files.md
planledger plan component set plan-0001 validation --file validation.md
planledger plan component set plan-0001 risks --file risks.md
planledger plan build plan-0001 --print
planledger plan validate plan-0001
planledger plan status plan-0001 done --reason "Ready for coding agent handoff."
```

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
```

## Handoff quality guardrails

A plan cannot be marked `done` unless:

- `todo_items` contains at least one `### TODO-NNN` heading.
- Every todo item has an **Acceptance criteria** section with at least one checkbox.
- Every todo item has a **Target files** section with at least one file reference.
- `target_files` contains at least one repo-relative file path or Markdown link.
- `validation` contains at least one validation command.
- No required component contains placeholder content (`TBD`, `TODO:`, `<fill>`, etc.).

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
.planledger/
  storage.yaml
  plans/
    plan-0001/
      plan.yaml
      components/
      rendered/
      versions/
```

## CLI surface

```text
planledger init [--project-name NAME] [--planledger-dir .planledger] [--hidden-config]
planledger status [--json]
planledger doctor [--json]

planledger plan create --title TITLE [--request TEXT | --request-file PATH] [--status new|in_progress]
planledger plan list [--status STATUS] [--json]
planledger plan show PLAN_ID [--component KEY] [--rendered] [--json]
planledger plan status PLAN_ID STATUS --reason TEXT
planledger plan cancel PLAN_ID --reason TEXT
planledger plan component list PLAN_ID [--json]
planledger plan component show PLAN_ID COMPONENT
planledger plan component set PLAN_ID COMPONENT (--text TEXT | --file PATH) [--reason TEXT]
planledger plan component append PLAN_ID COMPONENT (--text TEXT | --file PATH) [--reason TEXT]
planledger plan build PLAN_ID [--out PATH] [--print] [--include-empty] [--json]
planledger plan validate PLAN_ID [--json]
planledger plan versions PLAN_ID [--json]
planledger plan diff PLAN_ID --from v0001 --to v0002
planledger plan apply --file plan.json [--dry-run]
```

## Structured bundle workflow

Agents can create or update plans through `planledger.structured_plan.v1` bundles:

```bash
planledger plan apply --file plan.json --dry-run
planledger plan apply --file plan.json
```

## Development

```bash
python -m pytest
python -m ruff check .
python -m mypy planledger
```
