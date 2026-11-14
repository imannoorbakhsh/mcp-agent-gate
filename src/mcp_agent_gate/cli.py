"""Run the bounded agent through the local stdio MCP server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from approval_logging import ApprovalGate
from agent_loop import AgentLoop, HardLimits, SnapshotStore, ToolDefinition
from task_calendar_mcp.models import (
    CalendarEvent,
    CalendarEventCreateInput,
    CalendarEventListOutput,
    ListCalendarEventsInput,
    ListTasksInput,
    Task,
    TaskCreateInput,
    TaskListOutput,
)

from .dispatcher import LocalMCPDispatcher


def _definitions() -> list[ToolDefinition[Any, Any]]:
    return [
        ToolDefinition("list_tasks", "List local tasks.", ListTasksInput, TaskListOutput),
        ToolDefinition(
            "list_calendar_events",
            "List local calendar events.",
            ListCalendarEventsInput,
            CalendarEventListOutput,
        ),
        ToolDefinition("create_task", "Create a local task.", TaskCreateInput, Task),
        ToolDefinition(
            "create_calendar_event",
            "Create a local calendar event.",
            CalendarEventCreateInput,
            CalendarEvent,
        ),
    ]


def build_loop(snapshot_path: Path, audit_path: Path) -> AgentLoop:
    gate = ApprovalGate(log_path=audit_path)
    return AgentLoop(
        client=_anthropic_client(),
        dispatcher=LocalMCPDispatcher(approval_gate=gate),
        tools=_definitions(),
        system=(
            "You are a bounded personal planning assistant. Use the local task/calendar "
            "tools to answer the user. A human must approve every write tool call."
        ),
        limits=HardLimits(),
        snapshot_store=SnapshotStore(snapshot_path),
    )


def _anthropic_client() -> Any:
    import anthropic

    return anthropic.Anthropic()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--snapshot", type=Path, default=Path("run_snapshot.json"))
    parser.add_argument("--audit-log", type=Path, default=Path("tool_calls.jsonl"))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    loop = build_loop(args.snapshot, args.audit_log)
    snapshot = loop.resume() if args.resume else loop.run(loop.start(args.prompt))
    print(json.dumps(snapshot.model_dump(mode="json"), indent=2, default=str))


if __name__ == "__main__":
    main()
