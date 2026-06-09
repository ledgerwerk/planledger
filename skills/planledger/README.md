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
- filling todo items with target files, acceptance criteria, and validation commands;
- building the latest rendered Markdown handoff after changes;
- setting plan status to `done` only when guardrails pass and the human approves;
- reporting plan id, version, status, rendered Markdown path, and validation result.
