from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


class _FakeRun:
    def __init__(self) -> None:
        self.created_task = "task-0031"

    def __call__(
        self, cmd: list[str], cwd: Path, capture_output: bool, text: bool, check: bool
    ):
        _ = (cwd, capture_output, text, check)
        args = cmd[2:]
        payload: dict[str, Any]
        if args[:2] == ["status", "--full"]:
            payload = {
                "result": {
                    "ledger_ref": "main",
                    "active_task": {"task_ref": "task-0007", "slug": "active-task"},
                }
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if args[:3] == ["task", "create", args[2]]:
            payload = {
                "result": {
                    "task_ref": self.created_task,
                    "slug": "slice-one",
                    "status": "implementation",
                }
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if args[:2] == ["task", "activate"]:
            return subprocess.CompletedProcess(
                cmd, 0, json.dumps({"result": {"ok": True}}), ""
            )
        if args[:2] == ["task", "show"]:
            payload = {
                "result": {
                    "task_ref": args[2],
                    "slug": "slice-one",
                    "status": "implementation",
                    "progress": {"todos_total": 3, "todos_done": 1, "todos_open": 2},
                }
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        if args[:2] == ["next-action", "--task"]:
            payload = {"result": {"action": "todo-work"}}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": {}}), "")


def _setup_project(invoke, workspace: Path) -> None:
    invoke(workspace, "goal", "create", "Goal")
    invoke(workspace, "initiative", "create", "Init", "--goal", "goal-0001")
    invoke(workspace, "initiative", "activate", "init-0001")
    invoke(workspace, "plan", "draft", "--initiative", "init-0001")
    invoke(workspace, "milestone", "add", "Milestone", "--plan", "plan-0001")
    invoke(workspace, "slice", "add", "Slice one", "--milestone", "ms-0001")
    invoke(workspace, "slice", "ready", "slice-0001")


def test_taskledger_detect_push_pull_reconcile_plan_template(
    invoke,
    initialized_workspace: Path,
    monkeypatch,
) -> None:
    workspace = initialized_workspace
    _setup_project(invoke, workspace)

    fake_run = _FakeRun()
    monkeypatch.setattr(
        "planledger.taskledger.shutil.which", lambda _: "/usr/bin/taskledger"
    )
    monkeypatch.setattr("planledger.taskledger.subprocess.run", fake_run)

    (workspace / "taskledger.toml").write_text(
        '[project]\nname = "Taskledger"\n', encoding="utf-8"
    )

    detect_result = invoke(workspace, "--json", "taskledger", "detect")
    detect_payload = json.loads(detect_result.stdout)
    assert detect_result.exit_code == 0
    assert detect_payload["result"]["detected"] is True

    push_result = invoke(
        workspace,
        "taskledger",
        "push",
        "slice-0001",
        "--create-task",
        "--activate",
    )
    assert push_result.exit_code == 0

    binding_path = (
        workspace / ".planledger" / "ledgers" / "main" / "bindings" / "bind-0001.md"
    )
    assert binding_path.exists()

    pull_result = invoke(workspace, "--json", "taskledger", "pull")
    pull_payload = json.loads(pull_result.stdout)
    assert pull_result.exit_code == 0
    assert pull_payload["result"]["count"] == 1

    reconcile_result = invoke(workspace, "--json", "taskledger", "reconcile")
    reconcile_payload = json.loads(reconcile_result.stdout)
    assert reconcile_result.exit_code == 0
    assert isinstance(reconcile_payload["result"]["drift"], list)

    template_output = workspace / "task-plan.md"
    template_result = invoke(
        workspace,
        "taskledger",
        "plan-template",
        "slice-0001",
        "--output",
        str(template_output),
    )
    assert template_result.exit_code == 0
    assert template_output.exists()


def test_taskledger_bind(invoke, initialized_workspace: Path, monkeypatch) -> None:
    workspace = initialized_workspace
    _setup_project(invoke, workspace)

    def fake_run(
        cmd: list[str], cwd: Path, capture_output: bool, text: bool, check: bool
    ):
        _ = (cwd, capture_output, text, check)
        args = cmd[2:]
        if args[:2] == ["task", "show"]:
            payload = {
                "result": {
                    "task_ref": args[2],
                    "slug": "existing-task",
                    "status": "implementation",
                }
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"result": {}}), "")

    monkeypatch.setattr("planledger.taskledger.subprocess.run", fake_run)

    bind_result = invoke(
        workspace, "taskledger", "bind", "slice-0001", "--task", "task-0031"
    )
    assert bind_result.exit_code == 0
    assert "bind-0001" in bind_result.stdout
