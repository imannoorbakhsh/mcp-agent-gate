"""Synchronous adapter from the bounded loop to the local stdio MCP server."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from approval_logging import ApprovalGate, ToolCallRequest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class LocalMCPDispatcher:
    """Call the local stdio MCP server, passing every call through the approval gate."""

    def __init__(
        self,
        *,
        approval_gate: ApprovalGate,
        run_id: str = "pending",
        command: str = sys.executable,
        arguments: list[str] | None = None,
    ) -> None:
        self._approval_gate = approval_gate
        self._run_id = run_id
        self._server = StdioServerParameters(
            command=command,
            args=arguments or ["-m", "task_calendar_mcp.server"],
        )

    def set_run_id(self, run_id: str) -> None:
        self._run_id = run_id

    def dispatch(self, tool_name: str, tool_input: BaseModel) -> BaseModel:
        request = ToolCallRequest(
            run_id=self._run_id,
            tool_name=tool_name,
            input=tool_input.model_dump(mode="json"),
        )
        result = self._approval_gate.dispatch(
            request,
            lambda _: asyncio.run(self._call(tool_name, request.input)),
        )
        if not result.tool_result.success:
            message = result.tool_result.error.message if result.tool_result.error else "tool failed"
            raise RuntimeError(message)
        return result.tool_result.result

    async def _call(self, tool_name: str, arguments: dict[str, Any]) -> BaseModel:
        async with stdio_client(self._server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                response = await session.call_tool(tool_name, arguments={"request": arguments})
        if getattr(response, "isError", getattr(response, "is_error", False)):
            raise RuntimeError(_text_result(response))
        payload = getattr(response, "structuredContent", None) or getattr(
            response, "structured_content", None
        )
        if payload is None:
            payload = json.loads(_text_result(response))
        return _model_for(tool_name).model_validate(payload)


def _text_result(response: Any) -> str:
    return "".join(
        content.text
        for content in response.content
        if getattr(content, "type", None) == "text"
    )


def _model_for(tool_name: str) -> type[BaseModel]:
    from task_calendar_mcp.models import CalendarEvent, CalendarEventListOutput, Task, TaskListOutput

    models: dict[str, type[BaseModel]] = {
        "list_tasks": TaskListOutput,
        "list_calendar_events": CalendarEventListOutput,
        "create_task": Task,
        "create_calendar_event": CalendarEvent,
    }
    return models[tool_name]
