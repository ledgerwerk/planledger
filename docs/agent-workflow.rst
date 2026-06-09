Agent workflow
==============

Planledger is designed for coding-agent use. The typical workflow follows this
loop.

Step 1: Initialize
------------------

.. code-block:: bash

   planledger init

This creates ``.planledger/`` and ``planledger.toml`` at the project root.

Step 2: Create a plan
----------------------

.. code-block:: bash

   planledger plan create --title "Short description" \
       --request "Full request text"

Step 3: Populate components
----------------------------

Read the repository, collect evidence, and set each component:

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

   planledger plan build plan-0001 --print
   planledger plan validate plan-0001

If validation fails, fix the reported issues and re-run.

Step 5: Mark done and hand off
-------------------------------

.. code-block:: bash

   planledger plan status plan-0001 done --reason "Ready for implementation."

The rendered Markdown artifact is the handoff deliverable.

Structured bundle workflow
--------------------------

Agents can also use the ``planledger.structured_plan.v1`` JSON bundle format
to create or update plans in one step:

.. code-block:: bash

   planledger plan apply --file plan.json --dry-run
   planledger plan apply --file plan.json
