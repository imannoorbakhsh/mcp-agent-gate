from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from approval_logging import ApprovalGate
from agent_loop import AgentLoop, HardLimits, SnapshotStore
from mcp_agent_gate.cli import _definitions
from mcp_agent_gate.dispatcher import LocalMCPDispatcher


class FakeMessages:
    def __init__(self) -> None:
        self.responses = [
            SimpleNamespace(
                model="claude-opus-5-5",
                stop_reason="tool_use",
                usage=SimpleNamespace(input_tokens=10, output_tokens=5),
                content=[
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "list_tasks",
                        "input": {},
                    }
                ],
            ),
            SimpleNamespace(
                model="claude-opus-5-5",
                stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=20, output_tokens=5),
                content=[{"type": "text", "text": "You have local tasks."}],
            ),
        ]

    def count_tokens(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(input_tokens=20)

    def create(self, **_: object) -> SimpleNamespace:
        return self.responses.pop(0)


def test_agent_uses_stdio_mcp_and_persists_snapshot(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setenv("TASK_CALENDAR_DB_PATH", str(tmp_path / "mock.sqlite3"))
    loop = AgentLoop(
        client=SimpleNamespace(messages=FakeMessages()),
        dispatcher=LocalMCPDispatcher(
            approval_gate=ApprovalGate(log_path=tmp_path / "audit.jsonl")
        ),
        tools=_definitions(),
        snapshot_store=SnapshotStore(tmp_path / "snapshot.json"),
        limits=HardLimits(max_steps=3, max_tokens_per_call=100, max_total_tokens=1_000),
    )

    snapshot = loop.run(loop.start("List tasks"))

    assert snapshot.status == "completed"
    assert snapshot.final_text == "You have local tasks."
    assert snapshot.steps == 2
    assert (tmp_path / "snapshot.json").exists()
    audit_record = json.loads((tmp_path / "audit.jsonl").read_text())
    assert audit_record["tool_name"] == "list_tasks"
    assert audit_record["approval_decision"] == "not_required"
