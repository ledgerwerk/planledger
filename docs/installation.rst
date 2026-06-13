Installation
============

Prerequisites
-------------

- Python 3.10 or later.
- Ledgercore 0.1.x (installed automatically as a runtime dependency).

Editable install
----------------

Clone the repository and install in development mode:

.. code-block:: bash

   git clone <repo-url>
   cd planledger
   pip install -e .

Documentation build
-------------------

To build the documentation locally:

.. code-block:: bash

   pip install -r docs/requirements.txt
   pip install -e .
   sphinx-build -b html docs docs/_build/html

The HTML output will be at ``docs/_build/html/index.html``.
