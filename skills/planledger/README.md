# Planledger Agent Skill

This skill teaches a coding harness how to use Planledger as a workshop-first CLI for planning workshops and structured implementation handoffs.

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

## Canonical storage

Ledgercore 0.5 schema-3 owns project discovery and storage resolution. Use
`planledger --json status` or `planledger storage where` and treat the returned
`config_path` and data `storage.path` as authoritative. Never calculate data
paths manually or edit Planledger data directly.

The normal manifest is `.ledger/ledger.toml`, the stable Planledger config is
`.ledger/planledger/config.toml`, and the data mount uses `external`,
`user-data`, or `project`. The default external target is
`../ledger/planledger/<project-uuid>/data`. Use `planledger migrate` for
schema-2 and legacy projects. `external` does not imply Git behavior. Rendered
or exported Markdown remains the deliverable.
