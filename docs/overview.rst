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

- Stores independent plans under ``.planledger/plans/plan-0001/``.
- Versions every meaningful plan change.
- Keeps each plan as modular component files.
- Renders a standalone Markdown artifact for human or coding-agent handoff.
- Enforces handoff quality guardrails before a plan can be marked ``done``.

Planledger is not a task manager, does not store goals, and has no external
task-manager integration.
