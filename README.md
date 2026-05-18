# planledger

Durable project intent, project language, rationale, challenge, and closeout ledger for AI-assisted software work.

## When to use it

Use planledger when:

- you are not sure what the right goal is yet;
- goals may change after implementation feedback;
- you need to remember why work was cancelled or superseded;
- you want an agent to see current project intent before planning;
- you want a clean handoff from shaped planning into taskledger tasks.
- you want project language and non-obvious rationale stored inside `.planledger`;
- you need deterministic brown-field discovery and baseline review for an existing repo;
- you want a challenge step before taskledger handoff and a closeout step after implementation.

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
planledger language term add "Project Language" --definition "The canonical domain vocabulary for the repo."
planledger rationale create "Use bundle-first planning" --initiative init-0001 --hard-to-reverse --surprising-without-context --real-tradeoff --summary "Bundle-first planning keeps durable intent reviewable before task execution."
planledger --json snapshot export --include-language --include-rationale
```

## Core model

Planledger records:

- goals and their lifecycle (`exploring`, `active`, `fulfilled`, `cancelled`, `superseded`, `parked`)
- initiatives, plans, milestones, and slices
- language areas, terms, and ambiguities
- questions, assumptions, constraints, and reviews
- decisions/rationales, challenge sessions, risks, taskledger bindings, runs, and events

Taskledger remains the task execution system. Planledger is the system of record for what the project is trying to achieve, what changed, and why.

## Harness workflow

1. Export current machine context:
   ```bash
   planledger --json snapshot export --include-language --include-rationale --include-bodies --max-body-chars 4000
   ```
2. Agent classifies the request:
   - discovery or baseline work for an existing repo;
   - shaping or uncertain goal work;
   - lifecycle update for existing goals;
   - implementation planning;
   - challenge flow before handoff;
    - taskledger handoff;
   - closeout or evolution of stale state.
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
8. If the plan requires challenge, complete the challenge session before taskledger handoff:
   ```bash
   planledger challenge start --plan plan-0001
   planledger challenge complete --session challenge-0001
   ```
9. If the user asked for handoff and slices are ready:
   ```bash
   planledger --json taskledger detect
   planledger --json taskledger push-plan <result.plan_id> --create-tasks
   ```
10. After implementation, reconcile closeout:
   ```bash
   planledger implementation report validate --file report.json
   planledger implementation report apply --file report.json
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
- Use `planledger implementation report validate/apply` for post-implementation closeout.

## Taskledger integration

```bash
planledger --json taskledger detect
planledger --json taskledger push-plan plan-0001 --create-tasks
planledger --json taskledger pull
planledger --json taskledger reconcile
```

## Project Language and Rationale

```bash
planledger language area create "Ordering" --paths src/ordering
planledger language term add "Order" --area area-0001 --definition "A customer request for goods or services."
planledger rationale create "Billing remains asynchronous" --initiative init-0001 --hard-to-reverse --surprising-without-context --real-tradeoff --summary "Billing consumes events instead of synchronous calls to keep order placement available."
planledger adr create "Legacy compatibility alias" --initiative init-0001
```

## Baseline workflow

Use baseline for existing projects. `backfill` remains as a compatibility alias:

```bash
planledger --json discover repo --out baseline.json
planledger --json baseline validate --file baseline.json
planledger --json baseline apply --file baseline.json --dry-run
planledger --json baseline apply --file baseline.json
planledger --json baseline review
```

## Challenge workflow

```bash
planledger challenge start --plan plan-0001
planledger challenge record-question "What fails if billing is unavailable?" --session challenge-0001 --priority high
planledger challenge answer q-0001 --answer "Order placement continues; billing retries asynchronously."
planledger challenge complete --session challenge-0001
```

## Closeout workflow

```bash
planledger implementation report validate --file report.json
planledger implementation report apply --file report.json --dry-run
planledger implementation report apply --file report.json
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
