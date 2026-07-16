# Planledger Agent Skill

This skill teaches a coding harness how to use planledger as a workshop-first CLI for planning workshops and structured implementation handoffs.

## Installation

```bash
mkdir -p ~/.agents/skills
cp -R ./skills/planledger ~/.agents/skills/planledger
```

## What this skill covers

- creating a new independent plan for each new planning request unless the user names an existing plan id;
- inspecting repository files before filling plan context;
- using `--stdin`, `--file -`, or `plan apply --file -` to avoid temporary files;
- filling todo items with target files, acceptance criteria, and validation commands;
- building the latest rendered Markdown handoff after changes;
- exporting the rendered plan to the workspace root with `plan export`;
- setting plan status to `done` only when guardrails pass and the human approves;
- reporting plan id, version, status, rendered storage path, workspace export path, and validation result.
- using local `plan-000X` ids for CLI work and `pl:plan-000X` when a plan
  needs a global cross-ledger reference.

## Canonical storage

Planledger uses Ledgercore's `sibling-ledger` provider. Authoritative data is always `<project-root>/../ledger/plan/planledger`, with the shared provider selection in `.ledger/ledger.local.toml`, stable config in `.ledger/plan/config.toml`, and a `.ledger-project.toml` binding. Legacy repository-local, arbitrary external, and namespaced layouts are migration inputs only.
