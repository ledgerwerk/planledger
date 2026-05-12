---
name: planledger
description: Use planledger as a hidden durable project-intent ledger before taskledger handoff.
license: Apache-2.0
compatibility: opencode
metadata:
  audience: coding-agents
  workflow: task-management
---

## skill_version: planledger-skill-v1

# Planledger Skill

Use planledger as a hidden durable project-intent ledger. The human does not need to read plan Markdown.

## Mandatory execution contract

When this skill is loaded for planning, architecture, cross-module changes, ADR work, migration work, or taskledger handoff, the agent MUST use the planledger CLI. Reading this skill is not sufficient.

First action after loading this skill:

1. Run `planledger --json status`.
2. If the workspace is not initialized and the user asked for planning in the current project, run `planledger init --project-name "<project>"`, then run `planledger --json status` again.
3. Run `planledger --json context export --include-bodies --max-body-chars 4000` before drafting a bundle.
4. Inspect active, exploring, and recently closed goals before deciding what to do next.

The agent MUST NOT skip planledger when the user explicitly asks to use planledger, asks for a planledger bundle, asks for taskledger handoff, or the request involves architecture, cross-module workflow, migrations, ADRs, backfill, or repair.

## Default workflow

1. `planledger --json status`
2. `planledger --json context export --include-bodies --max-body-chars 4000`
3. Classify the request before mutating anything:
   - shaping or clarifying goals;
   - lifecycle update for existing work;
   - implementation planning;
   - taskledger handoff;
   - repair or stale-state evolution.
4. If the user is unsure of the goal, create or reuse an `exploring` goal, then add questions or assumptions. Do not create taskledger tasks.
5. If the user says a goal is fulfilled, cancelled, obsolete, or superseded, record that lifecycle change directly. Do not create new implementation tasks unless asked.
6. If implementation planning is requested, write a `planledger.plan_bundle.v1` JSON file.
7. `planledger --json bundle validate --file bundle.json`
8. `planledger --json bundle apply --file bundle.json --dry-run`
9. `planledger --json bundle apply --file bundle.json`
10. Read `result.plan_id` from the apply output. Never hardcode `plan-0001` unless it is actually the returned id.
11. Push to taskledger only if slices are ready and the user explicitly asked for handoff:
    - `planledger --json taskledger detect`
    - `planledger --json taskledger push-plan <result.plan_id> --create-tasks`
    - If the result has zero created tasks, report that handoff did not complete and why. Do not claim taskledger handoff succeeded.
12. If state is stale or contradictory, use the repair or evolution flow:
    - `planledger --json evolution validate --file evolution.json`
    - `planledger --json evolution apply --file evolution.json --dry-run`
    - `planledger --json evolution apply --file evolution.json`

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

Use `planledger --json context export` to get a snapshot of project intent including active goals, exploring goals, recently closed goals, open questions, assumptions, constraints, handoff blockers, and next action.

## Bundle commands

```bash
planledger --json bundle validate --file bundle.json
planledger --json bundle apply --file bundle.json --dry-run
planledger --json bundle apply --file bundle.json
```

## Evolution commands

```bash
planledger --json evolution validate --file evolution.json
planledger --json evolution apply --file evolution.json --dry-run
planledger --json evolution apply --file evolution.json
```

## Taskledger handoff

```bash
planledger --json taskledger detect
planledger --json taskledger push-plan <plan-id-from-apply-result> --create-tasks
planledger --json taskledger push-plan <plan-id-from-apply-result> --dry-run
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

## Final response evidence checklist

Before answering the human, verify and report:

- status/context export was run
- goal state was classified as shaping, lifecycle update, planning, handoff, or repair
- bundle validate passed when plan bundling was used
- bundle apply dry-run passed when plan bundling was used
- bundle apply passed when plan bundling was used
- returned plan id was captured when plan bundling was used
- taskledger detect was run when handoff was requested
- taskledger push-plan was run with `--create-tasks` when handoff was requested
- taskledger push-plan created tasks, or the response explicitly says why none were created

## Explicit lifecycle rules

- Never treat `cancelled`, `fulfilled`, or `superseded` goals as pending work.
- Before planning new work, inspect active, exploring, and recently closed goals.
- If the human says a goal is no longer useful, record cancellation rather than silently dropping it.
- If the human is unsure of the goal, create an `exploring` goal and open questions instead of forcing a plan.
- Do not resurrect cancelled goals as pending work.
- Do not push to taskledger during shaping.
