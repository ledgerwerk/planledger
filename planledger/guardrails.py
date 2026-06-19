# ruff: noqa: E501
from __future__ import annotations

import re

PLACEHOLDER_RE = re.compile(
    r"(?im)^\s*(?:TBD|TODO:|FIXME|N/A|NONE|UNKNOWN|<[^>]+>)\s*$"
)
TODO_HEADING_RE = re.compile(r"(?im)^###\s+TODO-\d+")
CHECKBOX_ITEM_RE = re.compile(r"(?im)^[-*]\s+\[[ xX]\]")
SECTION_RE_TEMPLATE = r"(?ims){heading}.*?(?=^###\s+TODO-\d+|\Z)"
FILE_REF_RE = re.compile(
    r"(?m)(?:\[[^\]]+\]\((?!https?://)[^)]+\)|`[A-Za-z0-9_./-]+\.[A-Za-z0-9]+`)"
)
COMMAND_RE = re.compile(
    r"(?m)(?:`(?:python|pytest|ruff|mypy|planledger)[^`]+`|"
    r"^\s*(?:python|pytest|ruff|mypy|planledger)\b)"
)
UNRESOLVED_REQUIRED_QUESTION_RE = re.compile(
    r"(?im)^[-*]\s+\[\s\]\s+REQUIRED:\s*(?P<question>.+?)\s*$"
)
RESOLVED_REQUIRED_QUESTION_RE = re.compile(r"(?im)^[-*]\s+\[[xX]\]\s+REQUIRED:")


def split_todo_blocks(text: str) -> list[str]:
    heading_matches = list(TODO_HEADING_RE.finditer(text))
    if heading_matches:
        blocks: list[str] = []
        for index, match in enumerate(heading_matches):
            start = match.start()
            end = (
                heading_matches[index + 1].start()
                if index + 1 < len(heading_matches)
                else len(text)
            )
            blocks.append(text[start:end].strip())
        return blocks
    checkbox_matches = list(CHECKBOX_ITEM_RE.finditer(text))
    if not checkbox_matches:
        return []
    blocks = []
    for index, match in enumerate(checkbox_matches):
        start = match.start()
        end = (
            checkbox_matches[index + 1].start()
            if index + 1 < len(checkbox_matches)
            else len(text)
        )
        blocks.append(text[start:end].strip())
    return blocks


def validate_handoff_contents(contents: dict[str, str]) -> list[str]:
    errors: list[str] = []

    for key in (
        "summary",
        "context",
        "approach",
        "todo_items",
        "target_files",
        "validation",
        "risks",
    ):
        value = contents.get(key, "")
        if PLACEHOLDER_RE.search(value):
            errors.append(f"Component {key!r} contains unresolved placeholder content.")

    todo_text = contents.get("todo_items", "")
    todo_blocks = split_todo_blocks(todo_text)
    if not todo_blocks:
        errors.append(
            "Component 'todo_items' must contain at least one "
            "TODO-001 style item or checkbox item."
        )
    for index, block in enumerate(todo_blocks, start=1):
        label = f"todo item {index}"
        if not re.search(
            r"(?im)^\*\*Acceptance criteria\*\*|^#+\s+Acceptance criteria",
            block,
        ):
            errors.append(f"{label} must contain an Acceptance criteria section.")
        if not re.search(r"(?m)^\s*- \[[ xX]\]\s+\S+", block):
            errors.append(f"{label} must contain at least one acceptance checkbox.")
        if not re.search(r"(?im)^\*\*Target files\*\*|^#+\s+Target files", block):
            errors.append(f"{label} must contain a Target files section.")
        if not FILE_REF_RE.search(block):
            errors.append(f"{label} must reference at least one target file.")

    if not FILE_REF_RE.search(contents.get("target_files", "")):
        errors.append(
            "Component 'target_files' must contain at least one "
            "repo-relative Markdown link or backticked file path."
        )

    if not COMMAND_RE.search(contents.get("validation", "")):
        errors.append(
            "Component 'validation' must contain at least one validation command."
        )

    open_questions = contents.get("open_questions", "")
    if UNRESOLVED_REQUIRED_QUESTION_RE.search(open_questions):
        errors.append(
            "Component 'open_questions' contains unresolved required questions; "
            "answer them or keep the plan out of done."
        )

    return errors


def unresolved_required_questions(text: str) -> list[str]:
    """Return the unresolved (``- [ ] REQUIRED:``) question strings in order."""
    return [
        match.group("question").strip()
        for match in UNRESOLVED_REQUIRED_QUESTION_RE.finditer(text or "")
    ]


def count_resolved_required_questions(text: str) -> int:
    """Count resolved (``- [x] REQUIRED:``) questions in the text."""
    return len(RESOLVED_REQUIRED_QUESTION_RE.findall(text or ""))


EXAMPLE_HEADING_RE = re.compile(r"(?im)^###\s+EXAMPLE-\d+")
SCENARIO_HEADING_RE = re.compile(r"(?im)^###\s+SCENARIO-\d+")
GIVEN_RE = re.compile(r"(?im)^\s*Given\b")
WHEN_RE = re.compile(r"(?im)^\s*When\b")
THEN_RE = re.compile(r"(?im)^\s*Then\b")
IN_SCOPE_RE = re.compile(r"(?im)^#+\s+In scope\b")
OUT_OF_SCOPE_RE = re.compile(r"(?im)^#+\s+Out of scope\b")


def split_example_blocks(text: str) -> list[str]:
    matches = list(EXAMPLE_HEADING_RE.finditer(text or ""))
    blocks: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append(text[match.start() : end].strip())
    return blocks


def split_scenario_blocks(text: str) -> list[str]:
    matches = list(SCENARIO_HEADING_RE.finditer(text or ""))
    blocks: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append(text[match.start() : end].strip())
    return blocks


def _has_placeholder_only(value: str) -> bool:
    stripped = (value or "").strip()
    return not stripped or bool(PLACEHOLDER_RE.fullmatch(stripped))


def validate_workshop_contents(contents: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for key in ("story", "examples", "decisions", "scope", "acceptance_scenarios"):
        if _has_placeholder_only(contents.get(key, "")):
            errors.append(
                f"Component {key!r} must be non-empty and not placeholder-only."
            )
    examples = split_example_blocks(contents.get("examples", ""))
    if not examples:
        errors.append(
            "Component 'examples' must contain at least one EXAMPLE-001 style example."
        )
    for index, block in enumerate(examples, start=1):
        if not (
            GIVEN_RE.search(block) and WHEN_RE.search(block) and THEN_RE.search(block)
        ):
            errors.append(f"example {index} must contain Given, When, and Then steps.")
    scope = contents.get("scope", "")
    if not IN_SCOPE_RE.search(scope):
        errors.append("Component 'scope' must contain an In scope section.")
    if not OUT_OF_SCOPE_RE.search(scope):
        errors.append("Component 'scope' must contain an Out of scope section.")
    scenarios = split_scenario_blocks(contents.get("acceptance_scenarios", ""))
    if not scenarios:
        errors.append(
            "Component 'acceptance_scenarios' must contain at least one SCENARIO-001 style scenario."
        )
    for index, block in enumerate(scenarios, start=1):
        if not (
            GIVEN_RE.search(block) and WHEN_RE.search(block) and THEN_RE.search(block)
        ):
            errors.append(f"scenario {index} must contain Given, When, and Then steps.")
    if unresolved_required_questions(contents.get("open_questions", "")):
        errors.append("open_questions contains unresolved required questions.")
    return errors
