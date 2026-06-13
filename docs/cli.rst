CLI reference
=============

Planledger exposes a single ``planledger`` command with subcommands grouped by
resource.

Project setup
-------------

.. code-block:: text

   planledger init [--project-name NAME] [--planledger-dir .planledger] [--hidden-config]
   planledger status [--json]
   planledger doctor [--json]

Plan management
---------------

Plan selectors accept local ids (``plan-0001``), canonical global refs
(``pl:plan-0001``), file aliases (``pl-plan-0001``), and uppercase file aliases.
Output always uses lowercase canonical refs. Foreign refs such as
``tl:task-0001`` are rejected.

.. code-block:: text

   planledger plan create --title TITLE [--request TEXT | --request-file PATH | --stdin] [--status new|in_progress]
   planledger plan list [--status STATUS] [--json]
   planledger plan show PLAN_ID [--component KEY] [--rendered] [--json]
   planledger plan status PLAN_ID STATUS --reason TEXT
   planledger plan cancel PLAN_ID --reason TEXT

Component editing
-----------------

.. code-block:: text

   planledger plan component list PLAN_ID [--json]
   planledger plan component show PLAN_ID COMPONENT
   planledger plan component set PLAN_ID COMPONENT (--text TEXT | --file PATH | --stdin) [--reason TEXT]
   planledger plan component append PLAN_ID COMPONENT (--text TEXT | --file PATH | --stdin) [--reason TEXT]

Build, validate, and version
-----------------------------

.. code-block:: text

   planledger plan build PLAN_ID [--out PATH] [--print] [--include-empty] [--json]
   planledger plan export [PLAN_ID] [--plan PLAN_ID] [--out PATH] [--include-empty] [--json]
   planledger plan validate PLAN_ID [--json]
   planledger plan versions PLAN_ID [--json]
   planledger plan diff PLAN_ID --from v0001 --to v0002

Structured bundles
------------------

Agents can create or update plans through ``planledger.structured_plan.v1``
bundles:

.. code-block:: text

   planledger plan apply --file PATH_OR_DASH [--dry-run]

For update bundles, ``plan_id`` accepts either a local id or a Planledger ref.
The schema and field name remain unchanged.

Stdin input
------------

Component commands and ``plan create`` accept ``--stdin`` and ``--file -`` for
multiline input without temporary files:

.. code-block:: bash

   cat <<'MD' | planledger plan component set context --stdin --reason "Record evidence."
   Repository evidence...
   MD

   cat <<'JSON' | planledger plan apply --file -
   { "schema": "planledger.structured_plan.v1", ... }
   JSON

Export
------

``planledger plan export`` writes the rendered Markdown to a workspace-root-relative
path (default ``WORKSPACE_ROOT/PLAN_ID.md``). This is the recommended final handoff
step because the configured Planledger storage directory may be outside the source
workspace.

.. code-block:: bash

   planledger plan export --plan plan-0004
   # writes: ./plan-0004.md
