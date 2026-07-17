"""Import-boundary enforcement for Ledgercore 0.5 adapter usage."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLANLEDGER_DIR = REPO_ROOT / "planledger"
TESTS_DIR = REPO_ROOT / "tests"

ALLOWED_MODULES = {
    "planledger/ledgercore_backend.py",
    "planledger/migration.py",
    "planledger/initialization.py",
}

ALLOWED_TESTS_MODULES = {
    "tests/test_ledgercore_backend.py",
    "tests/test_ledgercore_import_boundaries.py",
    "tests/test_planledger_ledgercore_050_context.py",
    "tests/test_planledger_domain_migration.py",
    "tests/test_init.py",
    "tests/test_sibling_storage_migration.py",
}

GENERIC_LEDGERCORE_SUBPACKAGES = {
    "ledgercore.atomic",
    "ledgercore.errors",
    "ledgercore.ids",
    "ledgercore.io",
    "ledgercore.refs",
    "ledgercore.time",
    "ledgercore.yamlio",
    "ledgercore.frontmatter",
    "ledgercore.hashing",
    "ledgercore.jsonio",
    "ledgercore.jsonl",
    "ledgercore.path_text",
    "ledgercore.paths",
    "ledgercore.config",
    "ledgercore.overrides",
}

ALLOWED_LEGACY_MODULES = {
    "planledger/legacy_binding.py",
}


def _iter_python_files(base: Path) -> list[Path]:
    return list(base.rglob("*.py"))


@pytest.mark.parametrize("path", _iter_python_files(PLANLEDGER_DIR))
def test_planledger_modules_use_only_allowed_ledgercore_imports(path: Path) -> None:
    relative = path.relative_to(REPO_ROOT).as_posix()
    if relative in ALLOWED_MODULES or relative in ALLOWED_LEGACY_MODULES:
        return
    source = path.read_text(encoding="utf-8")
    if "from ledgercore" not in source and "import ledgercore" not in source:
        return
    imports = re.findall(r"^(?:from|import)\s+(ledgercore\S*)", source, flags=re.MULTILINE)
    for name in imports:
        if name == "ledgercore":
            continue
        top = name.split(".")[1] if name.startswith("ledgercore.") else None
        if top and f"ledgercore.{top}" in GENERIC_LEDGERCORE_SUBPACKAGES:
            continue
        pytest.fail(
            f"{relative}: direct Ledgercore import {name!r} outside the adapter or generic utilities"
        )


@pytest.mark.parametrize("path", _iter_python_files(TESTS_DIR))
def test_test_modules_can_import_ledgercore(path: Path) -> None:
    relative = path.relative_to(REPO_ROOT).as_posix()
    if relative in ALLOWED_TESTS_MODULES:
        return
    source = path.read_text(encoding="utf-8")
    if "from ledgercore" not in source and "import ledgercore" not in source:
        return
    imports = re.findall(r"^(?:from|import)\s+(ledgercore\S*)", source, flags=re.MULTILINE)
    for name in imports:
        if name == "ledgercore":
            continue
        top = name.split(".")[1] if name.startswith("ledgercore.") else None
        if top and f"ledgercore.{top}" in GENERIC_LEDGERCORE_SUBPACKAGES:
            continue
        pytest.fail(
            f"{relative}: direct Ledgercore import {name!r} in tests; "
            "use planledger.ledgercore_backend or fixture helpers"
        )
