Architecture
============

Package structure
-----------------

.. code-block:: text

   planledger/
   ├── __init__.py
   ├── _version.py
   ├── launcher.py      # Console script entry point
   ├── cli.py           # Typer CLI application
   ├── models.py        # Data classes for Plan, Workspace, ComponentSpec
   ├── storage.py       # Record files, state, and inventory
   ├── project_context.py # Ledgercore project and mount resolution
   ├── project_binding.py # Direct sibling project ownership
   ├── id_inventory.py  # Strict derived allocations
   ├── migration.py     # Read-only inspect and verified migration
   ├── render.py        # Markdown rendering engine
   ├── guardrails.py    # Handoff quality validation
   ├── bundle.py        # Structured plan bundle loader and applier
   ├── errors.py        # PlanledgerError exception
   └── py.typed         # PEP 561 marker

Data flow
---------

1. **CLI** parses arguments and resolves the canonical project context through
   ``project_context.load_workspace`` and Ledgercore.
2. **Project context** validates the shared manifest, local sibling provider,
   direct mount, marker, binding, and schema-4 state.
3. **Storage** reads and writes component files and plan metadata under
   ``../ledger/planledger/<project-uuid>``.
3. **Render** assembles components into a single Markdown document with YAML
   front matter.
4. **Guardrails** inspects the rendered output to enforce done criteria.
5. **Bundle** loads a JSON bundle and applies mutations through storage.

Error handling
---------------

All business errors raise ``PlanledgerError`` with a structured ``code``,
``message``, and optional ``remediation`` list. The CLI catches these and
exits with the specified ``exit_code``.
