Storage layout
==============

Planledger stores all data under a ``.planledger/`` directory at the project
root. The location is configured in ``planledger.toml``.

Directory structure
-------------------

.. code-block:: text

   .planledger/
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
- ``title``: human-readable title.
- ``status``: current lifecycle status.
- ``version``: integer version counter, incremented on each component change.

storage.yaml
------------

Tracks the next available plan number. Modified atomically when a new plan is
created.

Workspace discovery
-------------------

``planledger.storage.discover_workspace`` walks upward from the current
directory to find a ``planledger.toml`` file. This identifies the project root
and the ``.planledger/`` data directory.

Version snapshots
-----------------

Each time a component is set or appended, the previous component content is
saved as a versioned snapshot under ``versions/``. This enables ``plan diff``
and history inspection.
