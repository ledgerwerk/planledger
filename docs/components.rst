Plan components
===============

Each plan stores modular component files under the canonical sibling mount,
for example ``../ledger/planledger/<project-uuid>/plans/PLAN_ID/components/``. Some
components are required for the plan to pass validation; others are optional.

Component reference
-------------------

.. list-table::
   :header-rows: 1
   :widths: 20 10 70

   * - Component
     - Required
     - Description
   * - ``request``
     - yes
     - Original human request.
   * - ``summary``
     - yes
     - Executive verdict.
   * - ``context``
     - yes
     - Repository context and evidence.
   * - ``open_questions``
     - no
     - Unresolved questions.
   * - ``assumptions``
     - no
     - Assumed facts.
   * - ``approach``
     - yes
     - Proposed implementation approach.
   * - ``todo_items``
     - yes
     - Structured todo items.
   * - ``target_files``
     - yes
     - Files that will change.
   * - ``validation``
     - yes
     - Validation plan and commands.
   * - ``risks``
     - yes
     - Risks and mitigations.
   * - ``rollback``
     - no
     - Rollback or repair strategy.
   * - ``notes``
     - no
     - Additional notes.

Setting components
------------------

Use ``planledger plan component set`` to replace a component, or
``planledger plan component append`` to append content:

.. code-block:: bash

   planledger plan component set plan-0001 approach --file approach.md
   planledger plan component append plan-0001 notes --text "Added scope note."

Todo item template
------------------

Every todo item in the ``todo_items`` component should follow this structure:

.. code-block:: md

   ### TODO-001: <action-oriented title>

   **Target files**

   - [`path/to/file.py`](path/to/file.py) — why this file changes.

   **Acceptance criteria**

   - [ ] Observable outcome.
   - [ ] Regression or edge case covered.

   **Validation**

   - `python -m pytest path/to/test_file.py -q`
