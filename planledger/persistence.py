"""Planledger-specific wrappers around Ledgercore persistence primitives."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ledgercore.atomic import atomic_write_text
from ledgercore.errors import AtomicWriteError, YamlStoreError
from ledgercore.time import utc_now_iso
from ledgercore.yamlio import load_yaml_object, write_yaml

from planledger.errors import PlanledgerError


def atomic_write_text_file(path: Path, content: str) -> None:
    try:
        atomic_write_text(path, content, normalize=True)
    except AtomicWriteError as exc:
        raise PlanledgerError(
            "storage_error",
            f"Failed to write {path}.",
        ) from exc


def write_yaml_object(path: Path, data: dict[str, Any]) -> None:
    try:
        write_yaml(path, data, sort_keys=False)
    except (AtomicWriteError, YamlStoreError) as exc:
        raise PlanledgerError(
            "storage_error",
            f"Failed to write YAML file {path}.",
        ) from exc


def load_yaml_object_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise PlanledgerError(
            "not_found",
            f"Required file does not exist: {path}",
        )
    try:
        loaded = load_yaml_object(path, label=f"YAML file {path}")
    except YamlStoreError as exc:
        raise PlanledgerError(
            "invalid_yaml",
            f"Expected a mapping in {path}.",
        ) from exc
    return dict(loaded)


def utc_now_iso_string() -> str:
    return utc_now_iso()
