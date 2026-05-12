from __future__ import annotations

from pathlib import Path

from planledger.storage import load_record, load_workspace_from_root


def _setup_goal(invoke, workspace: Path) -> None:
    assert invoke(workspace, "goal", "create", "Improve planning", "--status", "exploring").exit_code == 0


def test_create_question_scoped_to_goal(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    _setup_goal(invoke, workspace)
    result = invoke(
        workspace,
        "question",
        "add",
        "What exact outcome should improve?",
        "--goal",
        "goal-0001",
        "--priority",
        "high",
    )
    assert result.exit_code == 0, result.stdout
    ws = load_workspace_from_root(workspace)
    question = load_record(ws, "question", "q-0001")
    assert question.front_matter["scope_kind"] == "goal"
    assert question.front_matter["scope_id"] == "goal-0001"
    assert question.front_matter["status"] == "open"


def test_answer_question(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    _setup_goal(invoke, workspace)
    assert (
        invoke(
            workspace,
            "question",
            "add",
            "What exact outcome should improve?",
            "--goal",
            "goal-0001",
        ).exit_code
        == 0
    )
    result = invoke(
        workspace,
        "question",
        "answer",
        "q-0001",
        "--answer",
        "Durable evolving goal memory.",
    )
    assert result.exit_code == 0, result.stdout
    ws = load_workspace_from_root(workspace)
    question = load_record(ws, "question", "q-0001")
    assert question.front_matter["status"] == "answered"
    assert question.front_matter["answer"] == "Durable evolving goal memory."
    assert question.front_matter.get("answered_at")


def test_obsolete_question(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    _setup_goal(invoke, workspace)
    assert (
        invoke(
            workspace,
            "question",
            "add",
            "What exact outcome should improve?",
            "--goal",
            "goal-0001",
        ).exit_code
        == 0
    )
    result = invoke(
        workspace,
        "question",
        "obsolete",
        "q-0001",
        "--reason",
        "The goal was replaced.",
    )
    assert result.exit_code == 0, result.stdout
    ws = load_workspace_from_root(workspace)
    question = load_record(ws, "question", "q-0001")
    assert question.front_matter["status"] == "obsolete"
    assert question.front_matter["obsolete_reason"] == "The goal was replaced."


def test_create_assumption(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    _setup_goal(invoke, workspace)
    result = invoke(
        workspace,
        "assumption",
        "add",
        "The pain is planning drift, not task execution.",
        "--goal",
        "goal-0001",
        "--confidence",
        "medium",
    )
    assert result.exit_code == 0, result.stdout
    ws = load_workspace_from_root(workspace)
    assumption = load_record(ws, "assumption", "asm-0001")
    assert assumption.front_matter["scope_kind"] == "goal"
    assert assumption.front_matter["status"] == "unverified"


def test_confirm_assumption_with_evidence(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    _setup_goal(invoke, workspace)
    assert (
        invoke(
            workspace,
            "assumption",
            "add",
            "The pain is planning drift, not task execution.",
            "--goal",
            "goal-0001",
        ).exit_code
        == 0
    )
    result = invoke(
        workspace,
        "assumption",
        "confirm",
        "asm-0001",
        "--evidence",
        "user-feedback",
    )
    assert result.exit_code == 0, result.stdout
    ws = load_workspace_from_root(workspace)
    assumption = load_record(ws, "assumption", "asm-0001")
    assert assumption.front_matter["status"] == "confirmed"
    assert assumption.front_matter["evidence"] == ["user-feedback"]


def test_invalidate_assumption(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    _setup_goal(invoke, workspace)
    assert (
        invoke(
            workspace,
            "assumption",
            "add",
            "The pain is planning drift, not task execution.",
            "--goal",
            "goal-0001",
        ).exit_code
        == 0
    )
    result = invoke(
        workspace,
        "assumption",
        "invalidate",
        "asm-0001",
        "--reason",
        "Evidence contradicted the hypothesis.",
    )
    assert result.exit_code == 0, result.stdout
    ws = load_workspace_from_root(workspace)
    assumption = load_record(ws, "assumption", "asm-0001")
    assert assumption.front_matter["status"] == "invalidated"
    assert (
        assumption.front_matter["invalidation_reason"]
        == "Evidence contradicted the hypothesis."
    )


def test_constraint_and_review_commands(invoke, initialized_workspace: Path) -> None:
    workspace = initialized_workspace
    _setup_goal(invoke, workspace)
    assert (
        invoke(
            workspace,
            "constraint",
            "add",
            "Keep LLM provider calls outside planledger.",
            "--scope",
            "project",
        ).exit_code
        == 0
    )
    assert (
        invoke(
            workspace,
            "review",
            "add",
            "Goal review",
            "--scope-kind",
            "goal",
            "--scope-id",
            "goal-0001",
            "--outcome",
            "needs-followup",
        ).exit_code
        == 0
    )
    ws = load_workspace_from_root(workspace)
    constraint = load_record(ws, "constraint", "con-0001")
    review = load_record(ws, "review", "review-0001")
    assert constraint.front_matter["status"] == "active"
    assert review.front_matter["status"] == "completed"
