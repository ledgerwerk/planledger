# Planledger Agent Skill

This directory contains the planledger agent skill. Install it into your agent harness skills directory.

## Installation

```bash
mkdir -p ~/.agents/skills
cp -R ./skills/planledger ~/.agents/skills/planledger
```

## Usage

After installation, ask the harness or agent to load the `planledger` skill before planning or taskledger handoff work.

The skill teaches the agent how to use planledger as a hidden durable project-intent ledger: inspect active, exploring, and closed goals; record questions, assumptions, and lifecycle changes; validate and apply planning bundles; use evolution bundles for repairs and direction changes; and push work to taskledger only when slices are ready and handoff was requested.

## What this skill provides

- Default harness workflow for shaping, lifecycle updates, planning, handoff, and repair
- Planning mode guidance (skip, light, full, repair)
- Required bundle properties for `planledger.plan_bundle.v1`
- Evolution flow guidance for lifecycle repairs and direction changes
- Human interaction rules to avoid unnecessary questions
- Command reference for context export, bundle apply, evolution apply, taskledger push-plan, ADR, and backfill
