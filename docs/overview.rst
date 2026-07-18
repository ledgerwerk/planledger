Overview
========

Planledger is a Python CLI that stores independent, structured, versioned
implementation plans and renders each plan into one standalone Markdown handoff
file suitable for human or coding-agent consumption.

Product contract
----------------

- Planledger stores plans, not tasks.
- Each plan is independent.
- The primary user is a coding agent using the ``planledger`` CLI or skill.
- A done plan contains todo items, acceptance criteria, target files, and
  validation commands.
- Planledger has no external task-manager integration.

What it does
------------

- Stores plans below the resolved schema-3 data mount
  ``../ledger/planledger/<project-uuid>/data`` by default.
- Versions every meaningful plan change.
- Keeps each plan as modular component files.
- Renders a standalone Markdown artifact for handoff.
- Enforces handoff quality guardrails before a plan can be marked ``done``.

Storage and discovery
---------------------

Ledgercore 0.5 owns manifest discovery, bindings, external markers, and path
resolution. Planledger uses the ``external``, ``user-data``, or ``project``
data storage kinds. Use ``planledger --json status`` or ``planledger storage
where`` for authoritative paths. Legacy layouts and ``.planledger.toml`` are
migration inputs only and are handled by ``planledger migrate``.

Plan identity
-------------

A plan stores a local id such as ``plan-0001``. Planledger derives the canonical
global ref ``pl:plan-0001`` and file ref ``pl-plan-0001`` from the configured
ledger code. These refs are identifiers only and do not add task-manager
integration.
