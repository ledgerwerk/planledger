Quick start
===========

The following sequence creates a plan, populates its components, builds the
rendered Markdown, validates guardrails, and marks the plan done.

.. code-block:: bash

   # Initialize the project (run once)
   planledger init

   # Create a new plan
   planledger plan create --title "Add feature A" \
       --request "Please review how we can add feature A."

   # Set each component from a file
   planledger plan component set plan-0001 context --file context.md
   planledger plan component set plan-0001 approach --file approach.md
   planledger plan component set plan-0001 todo_items --file todos.md
   planledger plan component set plan-0001 target_files --file target_files.md
   planledger plan component set plan-0001 validation --file validation.md
   planledger plan component set plan-0001 risks --file risks.md

   # Build and print the rendered Markdown
   planledger plan build plan-0001 --print

   # Validate guardrails
   planledger plan validate plan-0001

   # Mark the plan done
   planledger plan status plan-0001 done --reason "Ready for coding agent handoff."

After ``done``, the rendered Markdown artifact lives under
``.planledger/plans/plan-0001/rendered/``.
