Contributing
============

Development setup
-----------------

.. code-block:: bash

   pip install -e .

Running tests
-------------

.. code-block:: bash

   python -m pytest

Linting
-------

.. code-block:: bash

   python -m ruff check .

Type checking
-------------

.. code-block:: bash

   python -m mypy planledger

Building documentation
----------------------

.. code-block:: bash

   pip install -r docs/requirements.txt
   sphinx-build -W -b html docs docs/_build/html

The ``-W`` flag treats warnings as errors, ensuring the docs stay clean.

Release readiness checklist
---------------------------

Planledger releases remain beta releases unless the project metadata is changed
deliberately. The current classifier is ``Development Status :: 4 - Beta``.
Do not add CI automation as part of the manual release gate; automation can be
introduced separately without changing the required checks.

Before publishing a release, run this gate from a clean checkout with the
release documentation dependencies installed:

.. code-block:: bash

   python -m pytest -q
   python -m ruff check .
   python -m mypy planledger
   python -m pip install -r docs/requirements.txt
   sphinx-build -W -b html docs docs/_build/html
   python -m build --sdist --wheel
   python -m twine check dist/*

Then install the built wheel in an isolated environment and confirm that the
console script is exposed:

.. code-block:: bash

   python -m venv /tmp/planledger-release-check
   /tmp/planledger-release-check/bin/python -m pip install dist/*.whl
   /tmp/planledger-release-check/bin/planledger --help

Any remaining release gap must be documented as either a blocker or an explicit
non-blocker before publication. The release notes must stay within the product
contract: Planledger stores independent plans and renders standalone Markdown
handoffs. It is not a task manager and has no external task-manager integration.
