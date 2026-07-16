Storage layout
==============

Planledger uses Ledgercore 0.4.0's fixed ``sibling-ledger`` workspace provider.
The canonical topology is deliberately narrow and has no runtime fallback:

.. code-block:: text

   <project-root>/.ledger/ledger.toml
   <project-root>/.ledger/ledger.local.toml
   <project-root>/.ledger/plan/config.toml
   <project-root>/../ledger/.ledger-store
   <project-root>/../ledger/plan/planledger/
     .ledger-project.toml
     storage.yaml
     allocations/plans/
     allocations/workshops/
     plans/
     workshops/

The shared manifest contains a project-scoped workspace mount:

.. code-block:: toml

   [ledgers.planledger.config]
   location = "project"
   path = "plan/config.toml"

   [ledgers.planledger.mounts.data]
   storage = "workspace"
   scope = "project"
   path = "plan/planledger"

The machine-local shared provider selection is:

.. code-block:: toml

   schema_version = 1

   [storage.workspace]
   provider = "sibling-ledger"

The sibling root must exist, be a directory, and contain a regular
``.ledger-store`` marker. Plain ``planledger init`` validates an existing store.
Use ``planledger init --create-sibling-store`` to explicitly create an absent
store. Planledger never runs Git commands.

Project binding
---------------

The direct data mount contains ``.ledger-project.toml``. Its UUID must match the
project UUID in ``.ledger/ledger.toml``. Non-empty unbound data and a binding for
a different project are fatal errors.

State and allocation
--------------------

``storage.yaml`` uses schema 4:

.. code-block:: yaml

   schema_version: 4
   active_plan_id: null
   active_workshop_id: null
   created_at: "..."
   updated_at: "..."

Project identity and next-ID counters are not stored in this file. Plan and
workshop IDs are derived from strict inventories of record directories and
allocation tombstones. New record directories are reserved with exclusive
creation, so a check-then-create race cannot allocate the same ID locally.
Legacy high-water marks are preserved as tombstones during migration.

Workspace discovery
-------------------

Normal runtime discovery locates ``.ledger/ledger.toml``, validates the exact
Planledger registration, loads ``.ledger/ledger.local.toml`` and resolves the
mount through Ledgercore. It rejects legacy locators, ``root`` overrides,
non-``sibling-ledger`` providers, ``LEDGER_WORKSPACE_ROOT``, missing markers,
foreign bindings, and missing data. It does not use platform user-data fallback.

Migration
---------

``planledger migrate`` is read-only. It classifies repository-local, legacy
external, namespaced workspace, direct sibling, old canonical, partial, and
invalid sources. The destination is always ``../ledger/plan/planledger``.

``planledger migrate apply`` performs a fresh inspection, mandatory backup,
same-store staging, conflict-safe copying, schema/config transformation,
binding creation, verification, and a migration receipt. Differing files,
symlinks, malformed records, unknown entries, and UUID conflicts block the
operation. Sources are preserved by default; ``--retire-source`` only renames
a source after verification and never deletes it. Taskledger data is never
migrated or modified.

Read-only inventory
-------------------

``planledger info`` reports the provider, store marker, direct authoritative
path, binding, schema, derived next IDs, record status, rendered artifacts, and
disk footprint. ``doctor`` checks the same invariants without changing files.
Repository mounts for Archledger and Releaseledger remain below
``<project-root>/.ledger``; selecting the workspace provider does not redirect
them.
