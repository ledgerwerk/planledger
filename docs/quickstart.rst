Quick start
===========

The CLI is the only supported mutation path. The rendered Markdown artifact is
the deliverable.

.. code-block:: bash

   # Check workspace state and resolved paths
   planledger --json status
   planledger storage where

   # Initialize with the default external target ../ledger
   planledger init --project-name "Demo" --create-external-store

   # Create a new independent plan
   planledger plan create --title "Add feature A" \
       --request "Please review how we can add feature A."

   # Set components from files
   planledger plan component set plan-0001 context --file context.md
   planledger plan component set plan-0001 approach --file approach.md
   planledger plan component set plan-0001 todo_items --file todos.md
   planledger plan component set plan-0001 target_files --file target_files.md
   planledger plan component set plan-0001 validation --file validation.md
   planledger plan component set plan-0001 risks --file risks.md

   # Build, validate, and complete the handoff
   planledger plan build plan-0001
   planledger plan validate plan-0001
   planledger plan status plan-0001 done --reason "Ready for coding agent handoff."

After ``done``, the rendered Markdown artifact is stored below
``../ledger/planledger/<project-uuid>/data/plans/plan-0001/rendered/``.

Export the rendered plan to the workspace root:

.. code-block:: bash

   planledger plan export

A new planning request creates a new independent plan unless the user names an
existing ``plan-000X``. The ``done`` status means the handoff artifact is
structurally ready, not that implementation has completed.

Legacy layouts are migration inputs only. Inspect them with ``planledger migrate``
and apply a reviewed migration with ``planledger migrate apply``.
