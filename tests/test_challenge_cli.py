from __future__ import annotations

import json
from pathlib import Path

from planledger.storage import list_events, load_record, load_workspace_from_root, save_record


def _seed_challenge_plan(invoke, workspace: Path) -> None:
    invoke(workspace, "goal", "create", "Goal")
    invoke(workspace, "initiative", "create", "Init", "--goal", "goal-0001")
    invoke(workspace, "initiative", "activate", "init-0001")
    invoke(workspace, "plan", "draft", "--initiative", "init-0001")
    invoke(workspace, "milestone", "add", "Milestone", "--plan", "plan-0001")
    invoke(workspace, "slice", "add", "Slice", "--milestone", "ms-0001")
    invoke(workspace, "slice", "ready", "slice-0001")
    invoke(workspace, "plan", "accept", "plan-0001", "--note", "Ready")
    ws = load_workspace_from_root(workspace)
    plan = load_record(ws, "plan", "plan-0001")
    plan.front_matter["planning_mode"] = "full"
    plan.front_matter["requires_challenge"] = True
    save_record(plan)


def test_challenge_start_creates_active_session(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    _seed_challenge_plan(invoke, workspace)
    result = invoke(workspace, "challenge", "start", "--plan", "plan-0001")
    assert result.exit_code == 0, result.stdout

    ws = load_workspace_from_root(workspace)
    sessions = load_record(ws, "challenge_session", "challenge-0001")
    plan = load_record(ws, "plan", "plan-0001")
    assert sessions.front_matter["status"] == "active"
    assert plan.front_matter["challenge_status"] == "active"


def test_challenge_answer_links_question_and_creates_review_event(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    _seed_challenge_plan(invoke, workspace)
    invoke(workspace, "challenge", "start", "--plan", "plan-0001")
    invoke(
        workspace,
        "challenge",
        "record-question",
        "What blocks billing?",
        "--session",
        "challenge-0001",
        "--priority",
        "high",
    )
    result = invoke(
        workspace,
        "challenge",
        "answer",
        "q-0001",
        "--answer",
        "Nothing blocks billing now.",
    )
    assert result.exit_code == 0, result.stdout

    ws = load_workspace_from_root(workspace)
    question = load_record(ws, "question", "q-0001")
    events = list_events(ws)
    assert question.front_matter["challenge_session"] == "challenge-0001"
    assert question.front_matter["status"] == "answered"
    assert any(event.get("event_type") == "challenge_answered" for event in events)


def test_challenge_complete_blocks_if_open_high_priority_questions_remain_unless_allow_open(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    _seed_challenge_plan(invoke, workspace)
    invoke(workspace, "challenge", "start", "--plan", "plan-0001")
    invoke(
        workspace,
        "challenge",
        "record-question",
        "What blocks billing?",
        "--session",
        "challenge-0001",
        "--priority",
        "high",
    )
    blocked = invoke(workspace, "challenge", "complete", "--session", "challenge-0001")
    assert blocked.exit_code != 0

    allowed = invoke(
        workspace,
        "challenge",
        "complete",
        "--session",
        "challenge-0001",
        "--allow-open",
    )
    assert allowed.exit_code == 0, allowed.stdout


def test_next_action_recommends_continuing_active_challenge_before_handoff(
    invoke, initialized_workspace: Path
) -> None:
    workspace = initialized_workspace
    _seed_challenge_plan(invoke, workspace)
    invoke(workspace, "challenge", "start", "--plan", "plan-0001")
    result = invoke(workspace, "--json", "next-action")
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["result"]["action"] == "continue-challenge"
