# Plan lifecycle

A plan moves through these statuses:

- **`new`**: Initial state after creation.
- **`in_progress`**: Active editing. Components are being written or updated.
- **`rework`**: Returned to editing after review or failed validation.
- **`done`**: All guardrails pass. The rendered Markdown artifact is ready for handoff. `done` is a handoff-readiness state, not an implementation-completed state.
- **`cancelled`**: Abandoned. The plan is kept but excluded from active queries.

## Status transitions

Use `planledger plan status PLAN_ID STATUS --reason TEXT` to change status.
The reason text is recorded in the plan history.

Typical flow:

```text
new -> in_progress -> done
new -> in_progress -> rework -> done
any -> cancelled
```

## Versions

Every component change creates a new version snapshot. Use these commands to
inspect history:

```bash
planledger plan versions plan-0001
planledger plan diff plan-0001 --from v0001 --to v0002
```

## Done guardrails

A plan cannot be marked `done` unless all of the following pass:

- `todo_items` contains at least one `### TODO-NNN` heading.
- Every todo item has an **Acceptance criteria** section with at least one checkbox.
- Every todo item has a **Target files** section with at least one file reference.
- `target_files` contains at least one repo-relative file path or Markdown link.
- `validation` contains at least one validation command.
- No required component contains placeholder content (`TBD`, `TODO:`, `<fill>`, etc.).
- Every TODO item has a **Validation** section with at least one recognizable validation command.
- `open_questions` contains no unresolved required questions (no `- [ ] REQUIRED:`).

Plan validation means the plan artifact is structurally ready for handoff.
It does not mean implementation tests have passed.
