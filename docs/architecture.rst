Architecture
============

Ownership boundary
------------------

Ledgercore 0.5 owns cross-cutting Ledger mechanics:

- canonical project discovery;
- schema-2 and schema-3 manifest parsing and writing;
- local override overlays;
- config and mount path derivation;
- external-store markers and binding markers;
- generic migration planning, staging, verification, journals, and recovery.

Planledger owns the required ``data`` mount, Planledger configuration,
``storage.yaml`` schema 4, plan and workshop records, active state, ID
allocation and tombstones, legacy source discovery, domain migration, CLI
presentation, write guards, and the skill/documentation contract.

The only detailed Ledgercore integration point is
``planledger/ledgercore_backend.py``. Domain modules use this adapter rather
than importing Ledgercore storage, TOML, binding, layout, or migration APIs.

Package structure
-----------------

.. code-block:: text

   planledger/
   ├── cli.py                 # Typer CLI application
   ├── cli_writes.py          # write-guard wiring
   ├── models.py              # domain data classes
   ├── persistence.py         # Planledger persistence wrappers
   ├── project_context.py     # inspection, workspace, and state classification
   ├── ledgercore_backend.py  # sole detailed Ledgercore adapter
   ├── initialization.py      # canonical schema-3 initialization
   ├── storage.py             # compatibility facade and domain operations
   ├── record_store.py        # shared record path/version mechanics
   ├── plan_store.py          # plan storage facade
   ├── workshop_store.py      # workshop storage facade
   ├── diagnostics.py         # read-only diagnostics facade
   ├── inventory.py           # read-only inventory facade
   ├── next_action.py         # next-action facade
   ├── legacy_layout.py       # legacy source discovery
   ├── domain_migration.py    # state and tombstone transformations
   ├── migration.py           # migration inspection and orchestration
   ├── write_lock.py          # exclusive Planledger write guard
   ├── id_inventory.py        # derived ID allocation
   ├── render.py              # Markdown rendering
   ├── guardrails.py          # handoff validation
   ├── bundle.py              # structured bundle handling
   ├── prompt_profiles.py     # prompt profile parsing
   └── errors.py              # structured PlanledgerError

Data flow
---------

1. The CLI resolves a root and asks ``project_context.inspect_project_context``
   for the project state.
2. Canonical contexts use ``ledgercore_backend`` and Ledgercore's resolved
   layout and mounts.
3. Storage facades read and write component files below the resolved data root.
4. Render assembles components into standalone Markdown.
5. Guardrails enforce done criteria.
6. Migration uses Ledgercore staging and verification plus Planledger domain
   transformations.

Error handling
--------------

Business errors raise ``PlanledgerError`` with a structured code, message,
remediation list, and details mapping. Ledgercore failures preserve the
Ledgercore code and exception type. Read-only commands distinguish legacy,
partial, malformed, missing, and invalid states instead of returning a generic
uninitialized result. Mutating commands require a canonical workspace and fail
closed.
