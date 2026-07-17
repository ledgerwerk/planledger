---
name: planledger
description: Shape planning workshops first, then create structured implementation plans and standalone Markdown handoff artifacts
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
- Do not omit the plan id, version, status, rendered Markdown path, workspace export path, or validation result in the final response.
- Treat `.ledger/ledger.toml` as the only normal project locator. Legacy config files and arbitrary external roots are migration inputs only.
- Do not skip `plan export` after marking a plan done when the rendered Markdown must be read by the coding harness.
- Do not create temporary files for multiline component content when `--stdin` or `--file -` is available.
- Do not store or recommend a `global_id`; Planledger derives global references.

## Canonical storage contract

Planledger authoritative data is resolved through Ledgercore 0.5 schema-3.
Stable Planledger config is `.ledger/planledger/config.toml`. The shared
manifest is `.ledger/ledger.toml`. The optional local override is
`.ledger/ledger.local.toml`. Default data storage is `external` with root
`../ledger`; the resolved data path ends in `/data` (for example
`../ledger/planledger/<project-uuid>/data`). Use `planledger migrate` for
legacy layouts.

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
plan export
plan validate
plan status
plan versions | plan diff
plan apply
```

## Fresh context entry protocol

1. Run `planledger --json status` or `planledger storage where`. Treat `result.config_path`, `result.storage.path`, and `result.state` as authoritative when present.
2. If no canonical project is found, run `planledger init` and provision the external store explicitly when appropriate. If a legacy locator or layout is found, run `planledger migrate` and review the report before applying it. The default external data path is `../ledger/planledger/<project-uuid>/data`.
3. Run `planledger --json next-action [--plan PLAN_ID]` to get the recommended next step for the active plan. Use this root `--json` form; the flag may also be placed after the subcommand.
4. Run `planledger --json plan list` when you need a workspace-wide plan overview.
5. If the user named a plan id, inspect it with `planledger --json plan show --plan PLAN_ID`.
6. If the user did not name a plan id and requested new planning work, create a new independent plan. The new plan becomes active.
7. If revising an existing plan, inspect the active plan with `planledger plan show` or use `--plan PLAN_ID` for a specific plan.
8. Use repository inspection before writing `context`.

## Plan reference protocol

- Use local `plan-000X` ids for normal CLI commands and storage paths.
- Use canonical `pl:plan-000X` refs when referencing a plan globally.
- Plan selectors also accept `pl-plan-000X` and uppercase file aliases.
- Treat uppercase aliases as input compatibility only; canonical output is lowercase.
- Global refs follow `<ledger>:<kind>-<number>`, for example `tl:task-0001`,
  `al:adr-0002`, `sw:spec-0003`, and `pl:plan-0004`.
- Cross-ledger refs are identifiers or links only. They do not make Planledger
  a task manager or external task-manager integration.

## Routing protocol: workshop vs plan

Use a workshop first when the user is shaping a feature, exploring requirements,
asking for examples, discussing behavior, or the implementation scope is not yet
clear.

Use a plan directly when the user explicitly asks for an implementation plan, a
coding-agent handoff, a `PLAN.md`-style artifact, a revision of an existing
`plan-000X`, or provides enough scope that the next useful step is implementation
planning.

Do not ask the user which mode to use unless both paths are equally valid and the
request cannot be safely interpreted. Prefer workshop-first when
`prompt_profiles.planning_workshop.enabled = true` and the request is product or
behavior shaping.

Workshop-first skeleton (when shaping):

```bash
planledger workshop create --title "Shape: <feature>" --request "..."
planledger workshop component set story --stdin --reason "Capture user intent."
planledger workshop component set examples --stdin --reason "Capture concrete examples."
planledger --json next-action
planledger workshop status workshop-000X shaped --reason "Scope and examples are clear."
planledger plan create --from-workshop workshop-000X --title "Implement: <feature>"
```

Plan-direct skeleton (when the request is already implementation-oriented):

```bash
planledger plan create --title "Short title" --request "Original request"
```

## Planning protocol

1. Create the plan:
   `planledger plan create --title "Short title" --request "Original request"`
   Or use stdin for the request:
   `cat <<'MD' | planledger plan create --title "Short title" --stdin`
2. Inspect repository files relevant to the request.
3. Populate required components. Prefer `--stdin` or `--file -` for multiline content:
   - `cat <<'MD' | planledger plan component set summary --stdin --reason "Define summary."`
   - Or use `plan apply --file -` for multi-component population in one versioned update.
4. Set required components:
   - `summary`
   - `context`
   - `approach`
   - `todo_items`
   - `target_files`
   - `validation`
   - `risks`
5. Set optional components when useful:
   - `open_questions`
   - `assumptions`
   - `rollback`
   - `notes`
6. Build and validate:
   - `planledger plan build`
   - `planledger plan validate`
7. If validation fails, fix the named component and rerun build/validate.
8. Set status to `done` only after guardrails pass and the human has approved, unless the user explicitly requested a finished handoff artifact now.
9. Export the rendered plan to the workspace root:
   - `planledger plan export`
   - Include the exported workspace path in the final response.

## next-action checkpoint protocol

After every state-changing Planledger command group (create, apply, build, component
set, answer), run the canonical checkpoint and treat it as the control point:

```bash
planledger --json next-action --plan PLAN_ID
```

Map the returned `next_item` to behavior:

- `fill_component`: populate the named component.
- `answer_required_question`: ask only the surfaced `question` and stop.
- `ask_plan_question`: when it carries a `topic`, record `- [ ] REQUIRED(topic): ...`, ask exactly that one question with a recommended answer, and stop. When it has no `topic`, ask exactly one unresolved plan-quality question and stop.
- `fix_validation`: fix the named blocker, then rebuild and revalidate.
- `mark_done_after_human_approval`: only then run the done gate (after validation passes and the human has approved or explicitly requested a finished handoff).
- `handoff_ready`: export/report the rendered artifact.
- `create_plan` / `specify_plan` / `init`: follow the surfaced `next_command`.

Do not mark a plan `done` until `next-action` indicates done-readiness (`mark_done_after_human_approval` or `handoff_ready`) after `plan build` and `plan validate` both pass and the human has approved.

## Question protocol

- If required decisions are missing, write them to `open_questions`, ask the user in chat, and stop.
- Do not invent answers to required questions from inference.
- When the user answers, update `open_questions`, `assumptions`, `approach`, and `todo_items` with a reason.
- If proceeding under assumptions, state the assumptions explicitly in the `assumptions` component.
- Mark resolved required questions with `- [x] REQUIRED:` syntax so the guardrail allows `done`.

## Planning interview profile protocol

When `planledger --json next-action` returns `prompt_profile.name == "planning_workshop" (deprecated alias: prompt_profile.name == "planning_interview")` and `prompt_profile.active == true`, ask exactly one question, include a recommended answer, then stop and wait for the user.

Rules:

- If the question can be answered by inspecting repository files, inspect the repository instead of asking the user.
- Record each required question in the `open_questions` component as a `- [ ] REQUIRED:` line before or when you ask it.
- Ask exactly one unresolved plan-quality question per turn and include a recommended answer immediately below it.
- Do not ask multiple questions in one response.
- When the user answers, update the line to `- [x] REQUIRED: <question> — Answer: <answer>`, then reflect the answer in `assumptions`, `approach`, `todo_items`, `target_files`, or `validation` when relevant.
- Run `planledger --json next-action --plan PLAN_ID` again and ask the next question only if it reports another question is needed (`next_item == "ask_plan_question"` or `next_item == "answer_required_question"`).
- When `next_item == "answer_required_question"`, ask only the surfaced `question`, include your recommended answer, and stop.

This profile is an optional Planledger prompt profile obeyed by this single skill. It does not create a separate skill, it does not make the CLI interview the user itself, and it does not replace the `open_questions` component.

Chat question format:

```text
Question: Should the new behavior be opt-in first, or become the default immediately?

Recommended answer: Make it opt-in first to preserve compatibility and reduce release risk.
```

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

Use `planledger plan apply --file - --dry-run` before large multi-component updates or when the JSON is hand-written. For small targeted updates, direct `planledger plan apply --file -` is acceptable.

Use bundles for batch creation/update only when they make the operation clearer than individual component commands. Do not force temporary files just to dry-run JSON; prefer stdin with `--file -`.

Prefer `planledger plan apply --file -` for multi-component population without temporary files:

```bash
cat <<'JSON' | planledger plan apply --file -
{
  "schema": "planledger.structured_plan.v1",
  "operation": "update",
  "plan_id": "plan-0004",
  "reason": "Populate implementation handoff plan.",
  "components": {
    "summary": "...",
    "context": "...",
    "approach": "...",
    "todo_items": "...",
    "target_files": "...",
    "validation": "...",
    "risks": "..."
  }
}
JSON
```

## Which read command to use

| Need                  | Command                                                   |
| --------------------- | --------------------------------------------------------- |
| Workspace overview    | `planledger --json status`                                |
| Health check          | `planledger --json doctor` or `planledger status --check` |
| Recommended next step | `planledger --json next-action [--plan PLAN_ID]`          |
| List plans            | `planledger --json plan list`                             |
| Show active plan      | `planledger --json plan show`                             |
| Show specific plan    | `planledger --json plan show --plan PLAN_ID`              |
| Show rendered handoff | `planledger plan show --rendered`                         |
| List components       | `planledger --json plan component list`                   |
| Read component        | `planledger plan component show COMPONENT`                |
| Show versions         | `planledger --json plan versions`                         |
| Compare versions      | `planledger plan diff --from v0001 --to v0002`            |
| Export to workspace   | `planledger plan export [--plan PLAN_ID] [--out PATH]`    |

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
Global ref: pl:plan-000X
Version: v000Y
Status: done|in_progress|rework
Rendered storage artifact: PATH
Workspace export: PATH
Validation: COMMAND exited STATUS
Next: approval needed | ready for coding-agent handoff | answer open questions
```

Run `planledger plan export` before the final response so the workspace export path is available. Do not paste the entire plan unless the user asks; point to the rendered Markdown artifact and workspace export.

## Minimal command examples

```bash
planledger --json status
planledger next-action          # human-readable next step (TTY)
planledger --json next-action --plan plan-0001   # machine-readable checkpoint
planledger status --check
planledger init
planledger --json plan list
planledger plan create --title "Short title" --request "Original request"
cat <<'MD' | planledger plan component set summary --stdin --reason "Define summary."
Summary from stdin.
MD
cat <<'MD' | planledger plan component set context --stdin
Context from stdin.
MD
planledger plan component set approach --file approach.md
planledger plan component set todo_items --file todos.md
planledger plan component set target_files --file target_files.md
planledger plan component set validation --file validation.md
planledger plan component set risks --file risks.md
cat <<'JSON' | planledger plan apply --file -
{ "schema": "planledger.structured_plan.v1", "operation": "update", "plan_id": "plan-0001", "reason": "Batch update.", "components": { "summary": "..." } }
JSON
planledger plan build
planledger plan validate
planledger plan status done --reason "Ready for handoff."
planledger plan export
planledger plan show --rendered
planledger plan show --plan plan-0001
planledger plan activate plan-0001
planledger plan versions
planledger plan diff --from v0001 --to v0002
planledger plan apply --file plan.json --dry-run
```
