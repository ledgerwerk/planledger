Architecture
============

Ownership boundary
------------------

Ledgercore 0.5 owns the cross-cutting Ledger mechanics:

- canonical Ledger project discovery
- schema-2 and schema-3 manifest parsing and writing
- optional ``ledger.local.toml`` parsing, overlay, mutation, and cleanup
- canonical config-path derivation
- mount-path derivation
- external-store root markers
- config and mount ``.ledger-project.toml`` binding markers
- generic migration planning
- safe copy/move staging
- hashing and verification
- configuration activation
- migration journals, recovery, and rollback

Planledger owns the plan/workshop domain behavior:

- the required ``data`` mount
- data storage kind validation (``project``, ``external``, or ``user-data``)
- the Planledger config schema
- ``storage.yaml`` schema 4
- plan and workshop record formats
- active plan and active workshop state
- plan/workshop ID inventory and reservation
- legacy counter conversion to tombstones
- Planledger-specific legacy source discovery
- Planledger-specific domain migration and post-migration validation
- CLI/API presentation
- the Planledger write guard
- the skill and documentation contract

The only module that imports detailed Ledgercore storage, TOML, binding,
layout, or migration APIs is ``planledger/ledgercore_backend.py``. Domain
modules import only this adapter.

Package structure
-----------------

.. code-block:: text

   planledger/
   ├── __init__.py
   ├── _version.py
   ├── launcher.py         # Console script entry point
   ├── cli.py              # Typer CLI application
   ├── cli_storage.py      # ``storage`` command group
   ├── cli_writes.py       # write-guard wiring for mutating commands
   ├── models.py           # Data classes for Plan, Workspace, ComponentSpec
   ├── storage.py          # Domain record and allocation behavior
   ├── initialization.py   # Schema-3 init flow (canonical init)
   ├── project_context.py  # Ledgercore project and mount resolution
   ├── project_binding.py  # Legacy compatibility binding reader
   ├── ledgercore_backend.py  # Sole Ledgercore integration point
   ├── legacy_layout.py    # Planledger-only legacy source discovery
   ├── domain_migration.py # State, counter, and tombstone transformations
   ├── migration.py        # Read-only inspect and verified migration
   ├── write_lock.py       # Planledger exclusive write guard
   ├── id_inventory.py     # Strict derived allocations
   ├── render.py           # Markdown rendering engine
   ├── guardrails.py       # Handoff quality validation
   ├── bundle.py           # Structured plan bundle loader and applier
   ├── errors.py           # PlanledgerError exception
   ├── prompt_profiles.py  # ``prompt_profiles`` config parsing
   └── py.typed            # PEP 561 marker

Data flow
---------

1. **CLI** parses arguments and resolves the canonical project context
   through ``project_context.load_workspace`` and Ledgercore.
2. **Project context** validates the shared manifest, the optional
   local overlay, the mount binding, and the schema-4 state.
3. **Storage** reads and writes component files and plan metadata
   inside the resolved data root.
4. **Render** assembles components into a single Markdown document
   with YAML front matter.
5. **Guardrails** inspects the rendered output to enforce done criteria.
6. **Bundle** loads a JSON bundle and applies mutations through storage.

Error handling
--------------

All business errors raise ``PlanledgerError`` with a structured ``code``,
``message``, optional ``remediation`` list, and ``details`` mapping. The
CLI catches these and exits with the specified ``exit_code``. Errors
wrapping a Ledgercore failure preserve ``ledgercore_code`` and
``ledgercore_error_type`` in ``details``.
