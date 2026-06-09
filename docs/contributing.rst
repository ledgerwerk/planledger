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
