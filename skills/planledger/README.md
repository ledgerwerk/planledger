# Planledger Agent Skill

This directory contains the planledger agent skill. Install it into your agent harness skills directory.

## Installation

```bash
mkdir -p ~/.agents/skills
cp -R ./skills/planledger ~/.agents/skills/planledger
```

## Usage

After installation, ask the harness or agent to load the `planledger` skill before planning or taskledger handoff work.

The skill teaches the agent how to use planledger as a hidden durable project-intent ledger: inspect active, exploring, and closed goals; record project language and rationale; validate and apply planning bundles; run deterministic baseline/discovery and challenge flows; use evolution or implementation-closeout reports for repairs and direction changes; and push work to taskledger only when slices are ready and handoff was requested.

## What this skill provides

- Default harness workflow for shaping, lifecycle updates, planning, handoff, and repair
- Project Language and rationale guidance with compatibility aliases
- Deterministic baseline/discovery and challenge-session workflow guidance
- Planning mode guidance (skip, light, full, repair)
- Required bundle properties for `planledger.plan_bundle.v1`
- Evolution and implementation-closeout guidance for lifecycle repairs and direction changes
- Human interaction rules to avoid unnecessary questions
- Command reference for snapshot/context export, bundle apply, evolution apply, implementation report apply, taskledger push-plan, rationale/ADR, and baseline/backfill
