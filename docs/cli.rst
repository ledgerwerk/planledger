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

.. code-block:: text

   planledger plan create --title TITLE [--request TEXT | --request-file PATH] [--status new|in_progress]
   planledger plan list [--status STATUS] [--json]
   planledger plan show PLAN_ID [--component KEY] [--rendered] [--json]
   planledger plan status PLAN_ID STATUS --reason TEXT
   planledger plan cancel PLAN_ID --reason TEXT

Component editing
-----------------

.. code-block:: text

   planledger plan component list PLAN_ID [--json]
   planledger plan component show PLAN_ID COMPONENT
   planledger plan component set PLAN_ID COMPONENT (--text TEXT | --file PATH) [--reason TEXT]
   planledger plan component append PLAN_ID COMPONENT (--text TEXT | --file PATH) [--reason TEXT]

Build, validate, and version
-----------------------------

.. code-block:: text

   planledger plan build PLAN_ID [--out PATH] [--print] [--include-empty] [--json]
   planledger plan validate PLAN_ID [--json]
   planledger plan versions PLAN_ID [--json]
   planledger plan diff PLAN_ID --from v0001 --to v0002

Structured bundles
------------------

Agents can create or update plans through ``planledger.structured_plan.v1``
bundles:

.. code-block:: text

   planledger plan apply --file plan.json [--dry-run]
