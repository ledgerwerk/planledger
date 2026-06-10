---
name: planledger
description: Create independent structured implementation plans and standalone Markdown handoff artifacts
license: Apache-2.0
compatibility: opencode
metadata:
  audience: coding-agents
  workflow: planning
---

## skill_version: planledger-skill-v4

# Planledger Skill

Use Planledger only for structured, versioned planning. The rendered Markdown artifact is the deliverable.

## When to use this skill

Use Planledger when the user asks for a durable implementation plan, a repository-informed planning review, a plan revision, or a standalone Markdown handoff for a coding agent.

Do not use Planledger for implementation tracking, task management, release notes, branch workflow, locks, validation runs, or changelog generation.

## Never do these things

- Do not answer with a chat-only plan when the user asked to use Planledger.
- Do not create goals, milestones, slices, external task records, implementation runs, validation runs, locks, or handoff records.
- Do not create more than one plan for one user request unless the user explicitly asks.
- Do not reuse an old plan for a new planning request unless the user names the existing `plan-000X`.
- Do not edit the configured Planledger storage directory directly. Use the Planledger CLI.
- Do not fill the `context` component without inspecting repository files.
- Do not invent answers to required user questions.
- Do not set a plan to `done` while required questions are unresolved.
- Do not set a plan to `done` until required components are complete, `plan build` succeeds, and `plan validate` passes.
- Do not claim implementation tests passed unless you actually ran them.
- Do not omit the plan id, version, status, rendered Markdown path, or validation result in the final response.
- Do not infer that Planledger is uninitialized just because `.planledger/` is absent; `.planledger.toml` and external `storage.planledger_dir` paths are valid.

## Core agent command path

Use this path for normal planning work:

```text
status
doctor
next-action
plan list | plan show
plan create
plan component list | plan component show
plan component set | plan component append
plan build
plan validate
plan status
plan versions | plan diff
plan apply
```

## Fresh context entry protocol

1. Run `planledger --json status`. Treat `result.config_path`, `result.planledger_dir`, and `result.storage_path` as authoritative when present.
2. If no config is found, run `planledger init`. If config exists but storage is missing, run `planledger doctor` and report the configured missing path; do not claim the config filename is invalid merely because it is `.planledger.toml`.
3. Run `planledger next-action [--json]` to get the recommended next step for the active plan.
4. Run `planledger --json plan list` when you need a workspace-wide plan overview.
5. If the user named a plan id, inspect it with `planledger --json plan show --plan PLAN_ID`.
6. If the user did not name a plan id and requested new planning work, create a new independent plan. The new plan becomes active.
7. If revising an existing plan, inspect the active plan with `planledger plan show` or use `--plan PLAN_ID` for a specific plan.
8. Use repository inspection before writing `context`.

## Planning protocol

1. Save the user request to a temporary file.
2. Create the plan:
   `planledger plan create --title "Short title" --request-file /tmp/request.md`
3. Inspect repository files relevant to the request.
4. Write component files outside the configured Planledger storage directory.
5. Set required components:
   - `summary`
   - `context`
   - `approach`
   - `todo_items`
   - `target_files`
   - `validation`
   - `risks`
6. Set optional components when useful:
   - `open_questions`
   - `assumptions`
   - `rollback`
   - `notes`
7. Build and validate:
   - `planledger plan build`
   - `planledger plan validate`
8. If validation fails, fix the named component and rerun build/validate.
9. Set status to `done` only after guardrails pass and the human has approved, unless the user explicitly requested a finished handoff artifact now.

## Question protocol

- If required decisions are missing, write them to `open_questions`, ask the user in chat, and stop.
- Do not invent answers to required questions from inference.
- When the user answers, update `open_questions`, `assumptions`, `approach`, and `todo_items` with a reason.
- If proceeding under assumptions, state the assumptions explicitly in the `assumptions` component.
- Mark resolved required questions with `- [x] REQUIRED:` syntax so the guardrail allows `done`.

## Component contract

Each todo item in `todo_items` must use this structure:

```md
### TODO-001: <action-oriented title>

**Target files**

- [`path/to/file.py`](path/to/file.py) — why this file changes.

**Acceptance criteria**

- [ ] Observable outcome.
- [ ] Regression or edge case covered.

**Validation**

- `python -m pytest path/to/test_file.py -q`
```

The `target_files` component must list every expected edit target as a repo-relative path or Markdown link.

The `validation` component must list commands or manual checks that the implementation agent should run. Do not imply those commands already passed unless they were executed.

## Done-gate protocol

Before setting `done`:

1. Run `planledger plan build`.
2. Run `planledger plan validate`.
3. Confirm every required component is non-empty and specific.
4. Confirm every todo has target files, acceptance criteria, and validation commands.
5. Confirm the plan has no unresolved required questions (no `- [ ] REQUIRED:` in `open_questions`).
6. Confirm the human approved the plan or explicitly requested a finished handoff.

Then run:

```bash
planledger plan status done --reason "Ready for coding-agent handoff."
planledger plan build
```

## Revision protocol

When the user asks for a change:

1. Inspect the current plan and rendered output.
2. Change only the affected component(s).
3. Provide a specific `--reason`.
4. Rebuild and validate.
5. Report the new version and rendered path.

Example:

```bash
planledger plan status rework --reason "Human requested a smaller migration step."
planledger plan component set todo_items --file /tmp/todos.md --reason "Split migration from API changes."
planledger plan build
planledger plan validate
```

## Structured bundle protocol

Use `planledger plan apply --file plan.json --dry-run` before applying a bundle.

Use bundles for batch creation/update only when they make the operation clearer than individual component commands.

## Which read command to use

| Need                  | Command                                                |
| --------------------- | ------------------------------------------------------ |
| Workspace overview    | `planledger --json status`                             |
| Health check          | `planledger --json doctor` or `planledger status --check` |
| Recommended next step | `planledger next-action [--json]`                      |
| List plans            | `planledger --json plan list`                          |
| Show active plan      | `planledger --json plan show`                          |
| Show specific plan    | `planledger --json plan show --plan PLAN_ID`           |
| Show rendered handoff | `planledger plan show --rendered`                      |
| List components       | `planledger --json plan component list`                |
| Read component        | `planledger plan component show COMPONENT`             |
| Show versions         | `planledger --json plan versions`                      |
| Compare versions      | `planledger plan diff --from v0001 --to v0002`         |

## CLI failure protocol

If a Planledger command raises a Python traceback:

1. Stop issuing mutating Planledger commands.
2. Run one read-only probe: `planledger --json status`.
3. If the probe fails, report that Planledger CLI startup is broken and no reliable mutation was recorded.
4. If the probe succeeds, inspect command help and retry the failed command once with explicit arguments.

If `plan validate` fails, do not mark the plan done. Fix the reported components, rebuild, and rerun validation.

## Final response contract

After planning or revision, answer with:

```text
Plan: plan-000X
Version: v000Y
Status: done|in_progress|rework
Rendered Markdown: PATH
Validation: COMMAND exited STATUS
Next: approval needed | ready for coding-agent handoff | answer open questions
```

Do not paste the entire plan unless the user asks; point to the rendered Markdown artifact.

## Minimal command examples

```bash
planledger --json status
planledger status --check
planledger init
planledger --json plan list
planledger plan create --title "Short title" --request-file /tmp/request.md
planledger plan component set context --file /tmp/context.md
planledger plan component set approach --file /tmp/approach.md
planledger plan component set todo_items --file /tmp/todos.md
planledger plan component set target_files --file /tmp/target_files.md
planledger plan component set validation --file /tmp/validation.md
planledger plan component set risks --file /tmp/risks.md
planledger plan build
planledger plan validate
planledger plan status done --reason "Ready for handoff."
planledger plan show --rendered
planledger plan show --plan plan-0001
planledger plan activate plan-0001
planledger plan versions
planledger plan diff --from v0001 --to v0002
planledger plan apply --file plan.json --dry-run
```
