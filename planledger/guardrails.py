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
