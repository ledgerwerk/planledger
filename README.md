# planledger

Durable project intent and planning ledger for AI-assisted software work.

## When to use it

Use planledger when:

- you are not sure what the right goal is yet;
- goals may change after implementation feedback;
- you need to remember why work was cancelled or superseded;
- you want an agent to see current project intent before planning;
- you want a clean handoff from shaped planning into taskledger tasks.

## Install

```bash
pip install -e .
```

## Quick start

```bash
planledger init --project-name "My Project"
planledger goal create "Improve planning" --status exploring
planledger question add "What exact outcome matters?" --goal goal-0001 --priority high
planledger view
planledger goal activate goal-0001 --reason "Outcome is clear enough to plan."
planledger initiative create "Evolving goal memory" --goal goal-0001
planledger initiative activate init-0001
planledger --json context export
```

## Core model

Planledger records:

- goals and their lifecycle (`exploring`, `active`, `fulfilled`, `cancelled`, `superseded`, `parked`)
- initiatives, plans, milestones, and slices
- questions, assumptions, constraints, and reviews
- decisions, risks, taskledger bindings, runs, and events

Taskledger remains the task execution system. Planledger is the system of record for what the project is trying to achieve, what changed, and why.

## Harness workflow

1. Export current machine context:
   ```bash
   planledger --json context export --include-bodies --max-body-chars 4000
   ```
2. Agent classifies the request:
   - shaping or uncertain goal work;
   - lifecycle update for existing goals;
   - implementation planning;
   - taskledger handoff;
   - repair or evolution of stale state.
3. For shaping or lifecycle updates, use goal, question, assumption, constraint, review, and evolution commands first. Do not create taskledger tasks during shaping.
4. For implementation planning, emit `planledger.plan_bundle.v1` JSON.
5. Validate:
   ```bash
   planledger --json bundle validate --file bundle.json
   ```
6. Dry-run:
   ```bash
   planledger --json bundle apply --file bundle.json --dry-run
   ```
7. Apply:
   ```bash
   planledger --json bundle apply --file bundle.json
   ```
8. If the user asked for handoff and slices are ready:
   ```bash
   planledger --json taskledger detect
   planledger --json taskledger push-plan <result.plan_id> --create-tasks
   ```

## Goal lifecycle examples

```bash
planledger goal complete goal-0001 --reason "Feature A implemented and validated."
planledger goal cancel goal-0002 --reason "Feature A removed the need for feature B." --because-goal goal-0001
planledger goal supersede goal-0003 --new-title "Remember evolving project intent" --reason "The old wording was too implementation-specific."
planledger goal park goal-0004 --reason "Valid, but deferred."
```

Closed goals remain visible in `planledger view` and `planledger --json context export`, but they are not treated as actionable work.

## Skill installation

```bash
mkdir -p ~/.agents/skills
cp -R ./skills/planledger ~/.agents/skills/planledger
```

## Bundle workflow

- Validate and apply planning bundles through `planledger bundle validate/apply`.
- Use `--dry-run` before apply in automation.
- Keep schema fixed to `planledger.plan_bundle.v1`.
- Use `planledger evolution validate/apply` for lifecycle updates, cancellations, and related review/question/assumption creation.

## Taskledger integration

```bash
planledger --json taskledger detect
planledger --json taskledger push-plan plan-0001 --create-tasks
planledger --json taskledger pull
planledger --json taskledger reconcile
```

## Backfill workflow

Use backfill for existing projects:

```bash
planledger --json backfill apply --file baseline.json \
  --evidence README.md:Project\ purpose
planledger --json backfill review
```

## Data model overview

Records are stored in `.planledger/ledgers/<ledger_ref>/` as Markdown/YAML records.
Core kinds:

- goal, initiative, plan, milestone, slice
- question, assumption, constraint, review
- decision, option, risk
- binding, run, event

## JSON command envelope

All `--json` commands follow:

```json
{
  "ok": true,
  "command": "planledger.command",
  "result": {},
  "events": []
}
```

## Development

```bash
python -m pytest -q
```
