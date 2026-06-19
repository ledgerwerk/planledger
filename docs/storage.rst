Storage layout
==============

Planledger stores all data under the configured Planledger storage directory.
The location is configured in ``planledger.toml`` or ``.planledger.toml`` under
``[storage].planledger_dir``. Relative storage paths are resolved from the config
root, so storage can live outside the source repository, for example
``../planledger-state/planledger``.

New configs include ledger identity:

.. code-block:: toml

   [ledger]
   code = "pl"
   name = "planledger"

Configs without this block remain valid and use those defaults. Absolute paths
and sibling paths containing ``..`` remain supported.

Directory structure
-------------------

.. code-block:: text

   <configured planledger_dir>/
     storage.yaml            # Next plan number counter
     plans/
       plan-0001/
         plan.yaml           # Plan metadata (title, status, version)
         components/         # One Markdown file per component
         rendered/           # Built Markdown artifacts
         versions/           # Versioned snapshots of component state

plan.yaml
---------

Each plan directory contains a ``plan.yaml`` with:

- ``id``: plan identifier (e.g. ``plan-0001``).
- ``kind``: normalized resource kind, always ``plan``.
- ``title``: human-readable title.
- ``status``: current lifecycle status.
- ``version``: integer version counter, incremented on each component change.

``global_ref`` and ``file_ref`` are derived for JSON and rendered Markdown.
They are not stored in ``plan.yaml`` or ``storage.yaml``.

storage.yaml
------------

Tracks the next available plan number. Modified atomically when a new plan is
created.

Workspace discovery
-------------------

``planledger.storage.discover_workspace`` walks upward from the current
directory to find ``planledger.toml`` or ``.planledger.toml``. This identifies
the project root and the configured Planledger storage directory.

Read-only inventory
-------------------

``planledger info`` renders a read-only inventory of everything stored under
the configured Planledger directory. It is backed by
``planledger.storage.collect_inventory(workspace)``, which reports workspace
and storage paths, the ``storage.yaml`` counters, plan and workshop status
counts, and a per-plan/per-workshop entry list (status, version, component
fill-state, rendered artifact path, versions, and disk size) plus a total disk
footprint.

Component fill-state is computed from the component files: a component counts
as filled when its file is non-empty (``st_size > 0``). Reported sizes are
scoped to component files, rendered artifacts, and the plan/workshop manifest;
version snapshots under ``versions/`` are intentionally excluded so the
footprint stays stable as history grows. ``collect_inventory`` never writes or
migrates storage.

Version snapshots
-----------------

Each time a component is set or appended, the previous component content is
saved as a versioned snapshot under ``versions/``. This enables ``plan diff``
and history inspection.
