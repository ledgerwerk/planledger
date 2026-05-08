---
name: planledger
description: Use planledger as a hidden durable planning control plane. The human does not need to read plan Markdown.
license: Apache-2.0
compatibility: opencode
metadata:
  audience: coding-agents
  workflow: task-management
---

## skill_version: planledger-skill-v1

# Planledger Skill

Use planledger as a hidden durable planning control plane. The human does not need to read plan Markdown.

## Default workflow

1. Run `planledger --json status` or `planledger --json context export`.
2. Determine planning mode: skip, light, full, or repair.
3. For light/full/repair, read relevant code and prior planledger state.
4. Produce a `planledger.plan_bundle.v1` JSON bundle.
5. Validate it with `planledger --json bundle validate --file bundle.json`.
6. Apply it with `planledger --json bundle apply --file bundle.json`.
7. Push executable slices with `planledger --json taskledger push-plan plan-0001 --create-tasks` when requested or when slices are ready.
8. Stop and report only the concise result and next command.

## Human interaction rules

- Do not ask the human to inspect plan Markdown in the happy path.
- Ask questions only when the request is blocked by missing requirements.
- Prefer recording assumptions as planledger records over asking low-value questions.
- Keep plans compact enough to be useful as future AI memory.

## When to skip planning

Skip planledger for trivial one-file edits with obvious implementation and low risk unless the user explicitly asks for planning.

Use full planledger workflow for architecture, migrations, new workflows, cross-module changes, taskledger handoff, or any request involving ADRs/decisions.

## Planning modes

| Mode   | When to use                                                                     |
| ------ | ------------------------------------------------------------------------------- |
| skip   | Trivial one-file edit, obvious bug, no architecture impact.                     |
| light  | Small feature, 1-3 files, low ambiguity.                                        |
| full   | Cross-module change, schema/API/workflow change, migration, taskledger handoff. |
| repair | Failed previous run, drift, validation failure, unclear state.                  |

## Required bundle properties

Every executable slice in a `planledger.plan_bundle.v1` bundle should include:

- objective
- target files
- implementation steps
- acceptance criteria
- validation commands
- risks or assumptions if relevant
- taskledger readiness flag

## Context export

Use `planledger --json context export` to get a snapshot of current planning state including active goal, initiative, plan, open decisions, risks, ready slices, bindings, and next action.

## Bundle commands

```bash
planledger --json bundle validate --file bundle.json
planledger --json bundle apply --file bundle.json
planledger --json bundle apply --file bundle.json --dry-run
```

## Taskledger handoff

```bash
planledger --json taskledger push-plan plan-0001 --create-tasks
planledger --json taskledger push-plan plan-0001 --dry-run
```

## ADR commands

```bash
planledger adr create "Decision title" --initiative init-0001
planledger --json adr list --initiative init-0001
planledger adr accept dec-0001 --option opt-0001 --rationale "..."
```

## Backfill for existing projects

```bash
planledger --json backfill apply --file baseline.json
planledger --json backfill review
```
