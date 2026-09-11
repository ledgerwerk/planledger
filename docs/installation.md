# Installation

## Prerequisites

- Python 3.10 or later.
- Ledgercore 0.6.1 or later within the supported `<0.7.0` major range, installed automatically as a runtime dependency.
- `tomlkit` 0.12 or later (installed automatically for shared Ledger config mutation).

## Editable install

Clone the repository and install in development mode:

```bash
git clone <repo-url>
cd planledger
pip install -e .
```

## Documentation build

To build the documentation locally:

```bash
pip install -r docs/requirements.txt
pip install -e .
sphinx-build -b html docs docs/_build/html
```

The HTML output will be at `docs/_build/html/index.html`.
