Overview
========

Planledger is a Python CLI that stores independent, structured, versioned
implementation plans and renders each plan into one standalone Markdown handoff
file suitable for human or coding-agent consumption.

Product contract
----------------

- Planledger stores plans only. It is not a task manager.
- Each plan is independent.
- The primary user is a coding agent interacting through ``planledger`` CLI
  commands or the bundled skill file.
- A done plan must contain todo items, acceptance criteria, target files, and
  validation commands.
- Planledger has no external task-manager integration.

What it does
------------

- Stores independent plans under the canonical sibling mount ``../ledger/plan/planledger`` through ``sibling-ledger``.
- Versions every meaningful plan change.
- Keeps each plan as modular component files.
- Renders a standalone Markdown artifact for human or coding-agent handoff.
- Enforces handoff quality guardrails before a plan can be marked ``done``.

Planledger is not a task manager, does not store goals, and has no external
task-manager integration.

Plan identity
-------------

A plan stores a local id such as ``plan-0001``. Planledger derives the canonical
global ref ``pl:plan-0001`` and file ref ``pl-plan-0001`` from the configured
ledger code. Global refs follow ``<ledger>:<kind>-<number>``. Uppercase file
aliases are accepted as input compatibility, but canonical output is lowercase.
These refs are identifiers only and do not add task-manager integration.

Storage is selected in the shared machine-local ``.ledger/ledger.local.toml`` and
project metadata is committed in ``.ledger/ledger.toml``. Legacy layouts are handled
only by ``planledger migrate``; Planledger does not use arbitrary external roots or
execute Git commands.
