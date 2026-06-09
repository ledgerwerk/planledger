---
name: planledger
description: Use planledger for independent structured plans and standalone Markdown handoff artifacts.
license: Apache-2.0
compatibility: opencode
metadata:
  audience: coding-agents
  workflow: planning
---

## skill_version: planledger-skill-v3

# Planledger Skill

Use planledger only for structured, versioned plans. The rendered Markdown artifact is the deliverable.

## Mandatory execution contract

When the user asks for planning work with planledger, the agent must use the planledger CLI.

Recommended first steps:

1. Run `planledger --json status`.
2. If the workspace is not initialized, run `planledger init`.
3. Create a new independent plan unless the user names an existing `plan-000X`.

## Core rules

1. For every new planning request, create a new independent plan unless the user names an existing plan id.
2. Inspect repository files before filling the `context` component.
3. Ask clarifying questions in chat when needed, but store unresolved ones in the `open_questions` component.
4. Do not create goals, milestones, slices, or external task records.
5. Keep each plan component focused:
   - `request` = original human request
   - `summary` = executive verdict
   - `context` = repository facts and evidence
   - `open_questions` = unresolved issues
   - `assumptions` = assumed facts
   - `approach` = recommended architecture or design
   - `todo_items` = structured todo items with acceptance criteria
   - `target_files` = files that will change
   - `validation` = commands and checks
   - `risks` = risks and mitigations
   - `rollback` = repair strategy
6. Every todo item in `todo_items` must use this template:

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

7. Never set status to `done` until:
   - required components are complete;
   - `plan validate` passes;
   - `plan build` succeeds;
   - the human has approved or the request explicitly asks for a finished handoff.
8. When the user asks for a change, update only the affected component, provide a reason, build the plan, and report the new version.
9. The final answer to the user must include:
   - plan id;
   - version;
   - status;
   - rendered Markdown path;
   - validation command result.

## Common workflow

```bash
planledger init
planledger plan create --title "Add feature A" --request-file /tmp/request.md
planledger plan component set plan-0001 context --file /tmp/context.md
planledger plan component set plan-0001 approach --file /tmp/approach.md
planledger plan component set plan-0001 todo_items --file /tmp/todos.md
planledger plan component set plan-0001 target_files --file /tmp/target_files.md
planledger plan component set plan-0001 validation --file /tmp/validation.md
planledger plan component set plan-0001 risks --file /tmp/risks.md
planledger plan build plan-0001
```

When revising a plan:

```bash
planledger plan status plan-0001 rework --reason "Human requested changes"
planledger plan component set plan-0001 todo_items --file /tmp/reworked-todos.md --reason "Split migration from UI change"
planledger plan build plan-0001
```

When the human signs off:

```bash
planledger plan validate plan-0001
planledger plan status plan-0001 done --reason "Human accepted the plan"
planledger plan build plan-0001
```

## Bundle workflow

```bash
planledger plan apply --file plan.json --dry-run
planledger plan apply --file plan.json
```

## Handoff quality guardrails

A plan cannot be marked `done` unless:

- `todo_items` contains at least one `### TODO-NNN` heading.
- Every todo item has an **Acceptance criteria** section with at least one checkbox.
- Every todo item has a **Target files** section with at least one file reference.
- `target_files` contains at least one repo-relative file path.
- `validation` contains at least one command.
- No required component contains placeholder content like `TBD`, `TODO:`, or `<fill>`.

These are enforced by the CLI. The agent does not need to implement them, but must provide content that satisfies them.
