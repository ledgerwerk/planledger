Agent workflow
==============

Planledger is designed for coding-agent use. The typical workflow follows this
loop.

Step 1: Check status and initialize
--------------------------------------

.. code-block:: bash

   planledger --json status
   planledger init

This creates a configured Planledger storage directory and a config file at the project root. The config file may be ``planledger.toml`` or ``.planledger.toml``; the storage directory may be outside the source repository when ``storage.planledger_dir`` points there.

Step 2: Create a plan
----------------------

For every new planning request, create a new independent plan unless the user
names an existing ``plan-000X``:

.. code-block:: bash

   planledger plan create --title "Short description" \
       --request "Full request text"

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
to create or update plans in one step:

.. code-block:: bash

   planledger plan apply --file plan.json --dry-run
   planledger plan apply --file plan.json
