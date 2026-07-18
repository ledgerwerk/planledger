Storage layout
==============

Planledger uses Ledgercore 0.5 schema-3 storage. The canonical topology is
deliberately narrow: a single ``data`` mount with one of three storage
kinds (``external``, ``user-data``, or ``project``).

.. code-block:: text

   <project-root>/.ledger/ledger.toml
   <project-root>/.ledger/ledger.local.toml         # machine-local, normally ignored
   <project-root>/.ledger/planledger/config.toml
   <project-root>/../ledger/.ledger-store.toml
   <project-root>/../ledger/planledger/<project-uuid>/data/
     .ledger-project.toml
     storage.yaml
     allocations/plans/
     allocations/workshops/
     plans/
     workshops/
     migrations/

The shared manifest contains exactly one Planledger mount:

.. code-block:: toml

   [project]
   uuid = "..."
   name = "..."

   [ledgers.planledger.mounts.data]
   storage = "external"
   root = "../ledger"

The optional local override is stored in ``.ledger/ledger.local.toml``:

.. code-block:: toml

   schema_version = 3

   [ledgers.planledger.mounts.data]
   storage = "user-data"

The external root must exist, be a directory, and contain a structured
``.ledger-store.toml`` marker (or be a freshly created external store).
A legacy weak ``.ledger-store`` marker is accepted during explicit
migration. ``planledger init --create-external-store`` creates an absent
store. Planledger never runs Git commands.

Project binding
---------------

The data mount contains ``.ledger-project.toml``. Its UUID must match
the project UUID in ``.ledger/ledger.toml``. Non-empty unbound data and
a binding for a different project are fatal errors.

State and allocation
--------------------

``storage.yaml`` uses schema 4:

.. code-block:: yaml

   schema_version: 4
   active_plan_id: null
   active_workshop_id: null
   created_at: "..."
   updated_at: "..."

Project identity and next-ID counters are not stored in this file. Plan
and workshop IDs are derived from strict inventories of record
directories and allocation tombstones. New record directories are
reserved with exclusive creation, so a check-then-create race cannot
allocate the same ID locally. Legacy high-water marks are preserved as
tombstones during migration.

Workspace discovery
-------------------

Normal runtime discovery locates ``.ledger/ledger.toml``, validates the
Planledger registration, optionally loads ``.ledger/ledger.local.toml``,
and resolves the mount through Ledgercore. It rejects legacy locators, missing markers, foreign bindings, and missing
data. Relative external roots are resolved against the project root; absolute
and home-relative roots are resolved by Ledgercore. It does not use a fallback
``cache`` storage.

Migration
---------

``planledger migrate`` is read-only. It classifies repository-local,
legacy external, old direct sibling, old canonical, partial, and invalid
sources. The destination is always
``../ledger/planledger/<project-uuid>/data`` for an external target.

``planledger migrate apply`` performs a fresh inspection, exclusive write
guard, same-store staging outside the source UUID directory,
conflict-safe copying, schema/config transformation, binding creation,
verification, and a migration receipt. Differing files, symlinks,
malformed records, unknown entries, and UUID conflicts block the
operation. Sources are preserved in ``copy`` mode; ``move`` mode renames
the old source only after post-validation succeeds. Other tools'
registrations and unrelated local overrides survive.

Read-only inventory
-------------------

``planledger info`` and ``planledger storage where`` report the generic
storage object (``mount``, ``kind``, ``source``, ``path``,
``binding_path``, ``binding_status``) and the schema-4 state. ``doctor``
checks the same invariants without changing files. Repository mounts
for Archledger and Releaseledger remain below ``<project-root>/.ledger``;
selecting the data storage kind does not redirect them.
