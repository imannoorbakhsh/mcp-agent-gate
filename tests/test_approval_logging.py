from __future__ import annotations

import json
from pathlib import Path

from approval_logging import ApprovalGate, ToolCallRequest


class StaticPrompt:
    def __init__(self, answer: bool) -> None:
        self.answer = answer

    def request_approval(self, request: ToolCallRequest) -> bool:
        return self.answer


def test_write_tool_requires_approval_and_is_logged(tmp_path: Path) -> None:
    audit_path = tmp_path / "tool_calls.jsonl"
    gate = ApprovalGate(approval_prompt=StaticPrompt(False), log_path=audit_path)
    request = ToolCallRequest(run_id="run-1", tool_name="create_task", input={"title": "x"})

    result = gate.dispatch(request, lambda _: (_ for _ in ()).throw(AssertionError("called")))

    assert result.approval_decision.value == "rejected"
    record = json.loads(audit_path.read_text().strip())
    assert record["tool_name"] == "create_task"
    assert record["approval_decision"] == "rejected"


def test_read_tool_executes_without_approval_and_is_logged(tmp_path: Path) -> None:
    audit_path = tmp_path / "tool_calls.jsonl"
    gate = ApprovalGate(approval_prompt=StaticPrompt(False), log_path=audit_path)

    result = gate.dispatch(
        ToolCallRequest(run_id="run-2", tool_name="list_tasks", input={}),
        lambda _: {"tasks": []},
    )

    assert result.tool_result.success
    assert json.loads(audit_path.read_text())["approval_decision"] == "not_required"
