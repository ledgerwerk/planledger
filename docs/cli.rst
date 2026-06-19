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
   planledger plan export --plan plan-0004
   # writes: ./plan-0004.md

Planning interview profile
--------------------------

Planledger ships an optional prompt profile named ``planning_workshop``.
When enabled, the existing Planledger skill (the single
``skills/planledger/SKILL.md``) asks the user one plan-quality question at a
time, includes a recommended answer, inspects the repository first when
possible, records required questions in ``open_questions``, and stops after
each question. The CLI only parses, persists, and exposes the policy; it does
not interview the user itself.

Configure it in ``planledger.toml`` or ``.planledger.toml``:

.. code-block:: toml

   [prompt_profiles.planning_workshop]
   enabled = true
   activation = "always"          # or "triggered"
   question_policy = "ask_one_at_a_time"
   codebase_first = true
   include_recommended_answer = true
   max_required_questions = 20
   min_resolved_required_questions_before_done = 0
   trigger_phrases = ["shape", "shape this feature", "shape this feature"]
   required_question_topics = ["scope", "tests", "rollback", "risks"]

With the profile active, the profile metadata and an agent instruction appear
in the machine-readable steering command:

.. code-block:: text

   planledger status --json            # result.prompt_profiles lists the profile
   planledger next-action --json       # result.prompt_profile + result.agent_instruction

``next_item`` is one of:

- ``ask_plan_question`` when the profile is active and no required component is empty.
- ``answer_required_question`` when ``open_questions`` already holds an unresolved
  ``- [ ] REQUIRED:`` line (only the first such question is surfaced).

The phrase ``shape this feature`` is supported only as a trigger phrase for
``activation = "triggered"``; ``planning_workshop`` is the canonical feature
name. The profile does not create planning-workshop records, does not replace
``open_questions``, and does not change Planledger's workshop-first, plan-second scope.
