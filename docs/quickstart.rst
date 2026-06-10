Quick start
===========

The CLI is the only supported mutation path. The rendered Markdown artifact is the
deliverable.

.. code-block:: bash

   # Check workspace state
   planledger --json status

   # Initialize the project (run once)
   planledger init

   # Create a new independent plan
   planledger plan create --title "Add feature A" \
       --request "Please review how we can add feature A."

   # Set each component from a file
   planledger plan component set plan-0001 context --file context.md
   planledger plan component set plan-0001 approach --file approach.md
   planledger plan component set plan-0001 todo_items --file todos.md
   planledger plan component set plan-0001 target_files --file target_files.md
   planledger plan component set plan-0001 validation --file validation.md
   planledger plan component set plan-0001 risks --file risks.md

   # Build and validate
   planledger plan build plan-0001
   planledger plan validate plan-0001

   # Mark the plan done
   planledger plan status plan-0001 done --reason "Ready for coding agent handoff."

After ``done``, the rendered Markdown artifact lives under the configured
Planledger storage directory, for example
``.planledger/plans/plan-0001/rendered/`` or
``../planledger-state/planledger/plans/plan-0001/rendered/``.

Export the rendered plan to the workspace root so the coding harness can read it:

.. code-block:: bash

   # Writes ./plan-0001.md in the workspace root
   planledger plan export

New planning request equals new independent plan unless the user names an existing
``plan-000X``. The ``done`` status means the handoff artifact is structurally ready,
not that implementation has been completed.
