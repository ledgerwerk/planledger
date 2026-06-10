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

   planledger plan component set plan-0001 context --file context.md
   planledger plan component set plan-0001 approach --file approach.md
   planledger plan component set plan-0001 todo_items --file todos.md
   planledger plan component set plan-0001 target_files --file targets.md
   planledger plan component set plan-0001 validation --file validation.md
   planledger plan component set plan-0001 risks --file risks.md

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

Structured bundle workflow
--------------------------

Agents can also use the ``planledger.structured_plan.v1`` JSON bundle format
to create or update plans in one step:

.. code-block:: bash

   planledger plan apply --file plan.json --dry-run
   planledger plan apply --file plan.json
