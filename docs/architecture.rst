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
   ├── storage.py       # Filesystem read/write and workspace discovery
   ├── render.py        # Markdown rendering engine
   ├── guardrails.py    # Handoff quality validation
   ├── bundle.py        # Structured plan bundle loader and applier
   ├── errors.py        # PlanledgerError exception
   └── py.typed         # PEP 561 marker

Data flow
---------

1. **CLI** parses arguments and resolves the workspace via
   ``storage.discover_workspace``.
2. **Storage** reads and writes component files and plan metadata under
   ``.planledger/``.
3. **Render** assembles components into a single Markdown document with YAML
   front matter.
4. **Guardrails** inspects the rendered output to enforce done criteria.
5. **Bundle** loads a JSON bundle and applies mutations through storage.

Error handling
---------------

All business errors raise ``PlanledgerError`` with a structured ``code``,
``message``, and optional ``remediation`` list. The CLI catches these and
exits with the specified ``exit_code``.
