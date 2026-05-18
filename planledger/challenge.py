from __future__ import annotations

from planledger.models import Record, Workspace
from planledger.storage import list_records, load_record

CHALLENGE_SESSION_STATUSES = {"active", "completed", "abandoned"}


def plan_requires_challenge(plan: Record) -> bool:
    if plan.front_matter.get("requires_challenge") is True:
        return True
    return str(plan.front_matter.get("planning_mode") or "") == "full"


def active_challenge_sessions(
    workspace: Workspace,
    *,
    plan_id: str | None = None,
) -> list[Record]:
    sessions = [
        session
        for session in list_records(workspace, "challenge_session")
        if session.front_matter.get("status") == "active"
    ]
    if plan_id is not None:
        sessions = [
            session
            for session in sessions
            if str(session.front_matter.get("plan") or "") == plan_id
        ]
    return sessions


def challenge_status_for_plan(workspace: Workspace, plan: Record) -> str:
    status = str(plan.front_matter.get("challenge_status") or "").strip()
    if status:
        return status
    if active_challenge_sessions(workspace, plan_id=plan.record_id):
        return "active"
    return "not-started"


def load_challenge_session(workspace: Workspace, session_ref: str) -> Record:
    return load_record(workspace, "challenge_session", session_ref)


def questions_for_session(
    workspace: Workspace,
    session_id: str,
    *,
    open_only: bool = False,
    high_only: bool = False,
) -> list[Record]:
    questions = [
        question
        for question in list_records(workspace, "question")
        if question.front_matter.get("challenge_session") == session_id
    ]
    if open_only:
        questions = [
            question
            for question in questions
            if question.front_matter.get("status") == "open"
        ]
    if high_only:
        questions = [
            question
            for question in questions
            if question.front_matter.get("priority") == "high"
        ]
    return questions
