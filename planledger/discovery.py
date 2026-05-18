from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

DISCOVERY_IGNORED_DIRS = {
    ".git",
    ".hg",
    ".idea",
    ".mypy_cache",
    ".nox",
    ".planledger",
    ".pytest_cache",
    ".ruff_cache",
    ".taskledger",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
DISCOVERY_IGNORED_SUFFIXES = {".pyc", ".pyo"}
DISCOVERY_SOURCE_SUFFIXES = {
    ".go",
    ".java",
    ".js",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}
DISCOVERY_STOPWORDS = {
    "api",
    "app",
    "base",
    "build",
    "cli",
    "common",
    "config",
    "core",
    "data",
    "default",
    "file",
    "helper",
    "impl",
    "main",
    "manager",
    "model",
    "service",
    "test",
    "tests",
    "type",
    "utils",
    "view",
}


def should_skip_discovery_path(path: Path) -> bool:
    if path.name in DISCOVERY_IGNORED_DIRS:
        return True
    if path.suffix in DISCOVERY_IGNORED_SUFFIXES:
        return True
    return False


def iter_repository_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if any(should_skip_discovery_path(parent) for parent in path.parents if parent != root):
            continue
        if should_skip_discovery_path(path):
            continue
        if path.suffix and path.suffix not in DISCOVERY_SOURCE_SUFFIXES:
            continue
        files.append(path)
    return files


def split_identifier(value: str) -> list[str]:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    normalized = normalized.replace("-", " ").replace("_", " ")
    parts = [part.strip() for part in normalized.split() if part.strip()]
    return parts


def titleize_identifier(value: str) -> str:
    parts = split_identifier(value)
    return " ".join(part[:1].upper() + part[1:] for part in parts)


def collect_candidate_nouns(files: list[Path], root: Path) -> list[str]:
    counts: Counter[str] = Counter()
    pattern = re.compile(r"\b(class|def)\s+([A-Za-z_][A-Za-z0-9_]*)")
    for path in files:
        stem = path.stem
        for part in split_identifier(stem):
            token = part.casefold()
            if len(token) < 3 or token in DISCOVERY_STOPWORDS:
                continue
            counts[part[:1].upper() + part[1:]] += 1
        if path.suffix != ".py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for _, name in pattern.findall(text):
            for part in split_identifier(name):
                token = part.casefold()
                if len(token) < 3 or token in DISCOVERY_STOPWORDS:
                    continue
                counts[part[:1].upper() + part[1:]] += 1
    return [token for token, _ in counts.most_common(20)]


def infer_area_paths(files: list[Path], root: Path) -> list[dict[str, object]]:
    area_map: dict[str, dict[str, object]] = {}
    for path in files:
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) < 2:
            continue
        if parts[0] == "src":
            area_path = Path(parts[0]) / parts[1]
        elif parts[0] in {"docs", "tests"}:
            continue
        else:
            area_path = Path(parts[0])
        area_key = str(area_path)
        area = area_map.setdefault(
            area_key,
            {
                "title": titleize_identifier(area_path.name),
                "paths": [area_key],
                "source_context": [],
            },
        )
        source_context = area["source_context"]
        if isinstance(source_context, list) and len(source_context) < 3:
            source_context.append(
                {
                    "path": str(rel),
                    "reason": "Representative file for the inferred area.",
                }
            )
    if area_map:
        return list(area_map.values())
    return [
        {
            "title": "Project",
            "paths": [],
            "source_context": [],
        }
    ]


def _relative(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def _discover_rationales(files: list[Path], root: Path) -> list[dict[str, Any]]:
    rationales: list[dict[str, Any]] = []
    for path in files:
        rel = _relative(root, path)
        lower = rel.casefold()
        if "adr" not in lower and "rationale" not in lower and "decision" not in lower:
            continue
        title = titleize_identifier(path.stem)
        if path.suffix in {".md", ".rst"}:
            try:
                first_line = path.read_text(encoding="utf-8").splitlines()[0].strip()
            except (UnicodeDecodeError, IndexError):
                first_line = ""
            if first_line.startswith("# "):
                title = first_line[2:].strip() or title
        rationales.append(
            {
                "title": title,
                "summary": "Inferred rationale candidate from repository documentation.",
                "decision_type": "rationale",
                "status": "open",
                "provenance": "inferred",
                "confidence": "low",
                "rationale_gate": {
                    "hard_to_reverse": True,
                    "surprising_without_context": True,
                    "real_tradeoff": True,
                },
                "evidence": [
                    {
                        "path": rel,
                        "reason": "Existing repository rationale-like documentation.",
                    }
                ],
            }
        )
    return rationales


def discover_repo(root: Path) -> dict[str, Any]:
    files = iter_repository_files(root)
    areas = infer_area_paths(files, root)
    area_file_map: dict[str, list[Path]] = {}
    for area in areas:
        paths = [str(item) for item in area.get("paths", [])]
        if not paths:
            area_file_map[str(area.get("title", "Project"))] = files
            continue
        matched = []
        for path in files:
            rel = _relative(root, path)
            if any(rel == base or rel.startswith(base + "/") for base in paths):
                matched.append(path)
        area_file_map[str(area.get("title", "Project"))] = matched or files

    terms: list[dict[str, Any]] = []
    for area in areas:
        title = str(area.get("title", "Project"))
        area_terms = collect_candidate_nouns(area_file_map.get(title, files), root)[:5]
        evidence = list(area.get("source_context", []))
        for term in area_terms:
            terms.append(
                {
                    "canonical": term,
                    "area": title,
                    "definition": "Inferred project term from repository sources.",
                    "aliases": [term.casefold()],
                    "avoid": [],
                    "provenance": "inferred",
                    "confidence": "low",
                    "status": "candidate",
                    "evidence": evidence[:1],
                }
            )

    docs = [
        _relative(root, path)
        for path in files
        if "docs/" in _relative(root, path) or path.name.casefold().startswith("readme")
    ]
    configs = [
        _relative(root, path)
        for path in files
        if path.name in {"pyproject.toml", "package.json", "planledger.toml", "taskledger.toml"}
    ]
    test_clusters = sorted(
        {
            _relative(root, path.parent)
            for path in files
            if "test" in path.parts or path.name.startswith("test_")
        }
    )

    return {
        "schema": "planledger.baseline.v1",
        "kind": "planledger_discovery",
        "root": str(root),
        "areas": [
            {
                "title": str(area.get("title", "Project")),
                "paths": list(area.get("paths", [])),
                "summary": "Inferred language area from repository structure.",
                "status": "candidate",
                "provenance": "inferred",
                "confidence": "medium",
                "source_context": list(area.get("source_context", [])),
            }
            for area in areas
        ],
        "terms": terms,
        "rationales": _discover_rationales(files, root),
        "docs": docs,
        "configs": configs,
        "test_clusters": test_clusters,
    }
