CLI reference
=============

Planledger exposes one ``planledger`` command with resource subcommands.

Project setup and inspection
----------------------------

.. code-block:: text

   planledger init [--project-name NAME] [--data-storage external|user-data|project] [--external-root PATH] [--create-external-store]
   planledger migrate [--source PATH] [--data-storage external|user-data|project] [--external-root PATH]
   planledger migrate apply [--source PATH] [--mode copy|move] [--data-storage KIND] [--external-root PATH] [--local-storage-override] [--backup-dir PATH] [--adopt-external-store]
   planledger status [--check]
   planledger info [--plan PLAN_ID | --workshop WORKSHOP_ID] [--paths-only] [--no-components]
   planledger doctor

``status``, ``info``, ``doctor``, and ``storage where`` are read-only. They use
one project inspection path and report canonical, legacy, partial, malformed,
and migration-required states without activating legacy configuration.

.. code-block:: bash

   planledger --json status
   planledger storage where
   planledger storage validate
   planledger storage set external --root ../ledger --local-storage-override
   planledger storage set user-data --local-storage-override
   planledger storage set project --project
   planledger storage clear-override
   planledger storage migration-status
   planledger storage recover

The storage object uses ``mount``, ``kind``, ``source``, ``external_root``,
``path``, ``binding_path``, and ``binding_status``. The returned paths are the
authoritative paths and must not be reconstructed by clients.

Plan management
---------------

.. code-block:: text

   planledger plan create --title TITLE [--request TEXT | --request-file PATH | --stdin] [--status new|in_progress]
   planledger plan list [--status STATUS]
   planledger plan show PLAN_ID [--component KEY] [--rendered]
   planledger plan activate PLAN_ID
   planledger plan status STATUS [PLAN_ID] [--plan PLAN_ID] --reason TEXT
   planledger plan cancel PLAN_ID --reason TEXT

Component editing
-----------------

.. code-block:: text

   planledger plan component list PLAN_ID
   planledger plan component show PLAN_ID COMPONENT
   planledger plan component set PLAN_ID COMPONENT (--text TEXT | --file PATH | --stdin) [--reason TEXT]
   planledger plan component append PLAN_ID COMPONENT (--text TEXT | --file PATH | --stdin) [--reason TEXT]

Build, validate, and version
-----------------------------

.. code-block:: text

   planledger plan build PLAN_ID [--out PATH] [--print] [--include-empty]
   planledger plan export [PLAN_ID] [--plan PLAN_ID] [--out PATH] [--include-empty]
   planledger plan validate PLAN_ID
   planledger plan versions PLAN_ID
   planledger plan diff PLAN_ID --from v0001 --to v0002

Structured bundles use ``planledger.structured_plan.v1``:

.. code-block:: text

   planledger plan apply --file PATH_OR_DASH [--dry-run]

Workshop commands use the corresponding ``workshop`` and
``workshop component`` subcommands. Plan selectors accept local ids such as
``plan-0001``, canonical refs such as ``pl:plan-0001``, and file aliases.

Prompt profile
--------------

Planledger ships the canonical ``planning_workshop`` profile. The deprecated
``planning_interview`` name remains an isolated compatibility alias and never
overrides an existing canonical table. Configure the canonical profile in
``.ledger/planledger/config.toml``:

.. code-block:: toml

   [prompt_profiles.planning_workshop]
   enabled = true
   activation = "always"          # or "triggered"
   question_policy = "ask_one_at_a_time"
   codebase_first = true
   include_recommended_answer = true
   max_required_questions = 20
   min_resolved_required_questions_before_done = 0
   required_question_topics = ["scope", "tests", "rollback", "risks"]

The CLI parses and exposes the policy. The Planledger skill asks questions and
records them in ``open_questions``.

Storage contract
----------------

Ledgercore 0.5 owns schema-3 discovery, manifest parsing, bindings, external
markers, and resolved paths. Planledger uses the single ``data`` mount with
``external``, ``user-data``, or ``project`` storage. The default external root
is ``../ledger`` and the default data path is
``../ledger/planledger/<project-uuid>/data``. Legacy layouts and
``.planledger.toml`` are migration inputs only. Use ``planledger migrate`` and
``planledger migrate apply`` for them. No normal-runtime command uses provider
terminology or performs Git operations.
