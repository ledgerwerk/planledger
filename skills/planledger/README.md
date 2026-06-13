# Planledger Agent Skill

This skill teaches a coding harness how to use planledger as a plan-only CLI for structured, versioned implementation handoffs.

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
- using local ``plan-000X`` ids for CLI work and ``pl:plan-000X`` when a plan
  needs a global cross-ledger reference.
