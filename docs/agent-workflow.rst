Agent workflow
==============

Planledger is designed for coding-agent use. The typical workflow follows this
loop.

Step 1: Check status and initialize
--------------------------------------

.. code-block:: bash

   planledger --json status
   planledger init
   # Create the default external root when it is absent
   planledger init --create-external-store

This creates or validates the canonical ``.ledger`` project metadata and resolves
Planledger data through Ledgercore at ``../ledger/planledger/<project-uuid>/data``.

Step 2: Route to workshop or plan
---------------------------------

Use a **workshop** when the request is about shaping a feature, finding
examples, clarifying behavior, product rules, BDD scenarios, acceptance
scenarios, or requirement exploration. Prefer workshop-first when the
``planning_workshop`` prompt profile is enabled and the request is product or
behavior shaping.

Use a **plan** directly when the request is already implementation-oriented,
asks for a coding-agent handoff, names target files, asks to revise an existing
``plan-000X``, or explicitly says "create/update PLAN.md". Do not ask the user
which mode to use unless both paths are equally valid and the request cannot be
safely interpreted.

.. code-block:: bash

   # Requirement shaping path
   planledger workshop create --title "Shape: <feature>" --request "Full request text"
   planledger workshop component set story --stdin --reason "Capture user intent."
   planledger workshop component set examples --stdin --reason "Capture concrete examples."
   planledger workshop status workshop-000X shaped --reason "Scope and examples are clear."
   planledger plan create --from-workshop workshop-000X --title "Implement: <feature>"

   # Direct implementation-handoff path
   planledger plan create --title "Short description" \
       --request "Full request text"
Use local ids in normal CLI examples. Global selectors such as
``pl:plan-0001`` are accepted when a plan is referenced across ledgers. The
canonical global ref is derived and does not create task-manager integration.

Step 3: Populate components
----------------------------

Inspect the repository, collect evidence, and set each component:

.. code-block:: bash

   # Set components individually using stdin or files
   cat <<'MD' | planledger plan component set plan-0001 context --stdin
   Repository evidence...
   MD

   # Or populate many components in one versioned update
   cat <<'JSON' | planledger plan apply --file -
   {
     "schema": "planledger.structured_plan.v1",
     "operation": "update",
     "plan_id": "plan-0001",
     "reason": "Populate required components.",
     "components": {
       "summary": "Ready for implementation.",
       "context": "Repository evidence...",
       "approach": "Implementation sequence...",
       "todo_items": "### TODO-001: ...",
       "target_files": "- [`src/file.py`](src/file.py)",
       "validation": "- `python -m pytest -q`",
       "risks": "- Risk: ..."
     }
   }
   JSON

Step 4: Build and validate
---------------------------

.. code-block:: bash

   planledger plan build plan-0001
   planledger plan validate plan-0001

Plan validation means the plan artifact is structurally ready for handoff.
It does not mean implementation tests have passed.

If validation fails, fix the reported issues and re-run.

Step 5: Mark done and hand off
-------------------------------

.. code-block:: bash

   planledger plan status plan-0001 done --reason "Ready for implementation."

The ``done`` status means the handoff artifact is structurally ready.
The rendered Markdown artifact is the handoff deliverable.

Step 6: Export the rendered plan
---------------------------------

Export the rendered plan to a workspace-root-relative path so the
coding harness can find it without knowing the Planledger storage directory:

.. code-block:: bash

   planledger plan export --plan plan-0001
   # writes: ./plan-0001.md

Structured bundle workflow
--------------------------

Agents can also use the ``planledger.structured_plan.v1`` JSON bundle format
to create or update plans in one step. Use ``plan apply --file - --dry-run``
before large multi-component updates or when the JSON is hand-written. For
small targeted updates, direct ``plan apply --file -`` is acceptable and does
not require a temporary file:

.. code-block:: bash

   cat <<'JSON' | planledger plan apply --file - --dry-run
   { "schema": "planledger.structured_plan.v1", "operation": "update", "plan_id": "plan-0001", "components": { "summary": "..." } }
   JSON

   cat <<'JSON' | planledger plan apply --file -
   { "schema": "planledger.structured_plan.v1", "operation": "update", "plan_id": "plan-0001", "components": { "summary": "..." } }
   JSON

Step 7: Optional planning interview
------------------------------------

When the project enables the ``planning_workshop`` prompt profile, the coding
agent (driven by the Planledger skill) asks one plan-quality question at a
time, includes a recommended answer, inspects the repository first when
possible, records required questions in ``open_questions``, and stops after
each question. Planledger itself only parses and exposes the policy; it does
not interview the user.

.. code-block:: toml

   # .ledger/planledger/config.toml
   [prompt_profiles.planning_workshop]
   enabled = true
   activation = "always"   # or "triggered"
   trigger_phrases = ["shape", "shape this feature", "shape this feature"]

.. code-block:: bash

   planledger --json next-action
   # next_item == "ask_plan_question" or "answer_required_question"
   # result.prompt_profile.active == true

Required questions are recorded as ``- [ ] REQUIRED:`` lines and resolved as
``- [x] REQUIRED:`` lines in ``open_questions``. ``planning_workshop`` is the
canonical feature name; ``shape this feature`` is only a trigger phrase.

Storage and migration
---------------------
Ledgercore owns the manifest, optional local override, bindings, external marker,
and resolved paths. Use ``planledger --json status`` or ``planledger storage where``
instead of calculating paths. For legacy layouts, run ``planledger migrate`` first
and apply only after reviewing the read-only report with ``planledger migrate apply``.
The source is preserved by default and other ledger data is never modified.
