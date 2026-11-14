"""Runnable stdio FastMCP server for the local task/calendar mock."""

from __future__ import annotations

from fastmcp import FastMCP

from .database import TaskCalendarDatabase, database_path_from_environment
from .models import (
    CalendarEvent,
    CalendarEventCreateInput,
    CalendarEventListOutput,
    ListCalendarEventsInput,
    ListTasksInput,
    Task,
    TaskCreateInput,
    TaskListOutput,
)

mcp = FastMCP(
    "Task Calendar Mock",
    instructions=(
        "Use the four task and calendar tools to work with the local SQLite mock. "
        "No external services or credentials are used."
    ),
)


def _database() -> TaskCalendarDatabase:
    database = TaskCalendarDatabase(database_path_from_environment())
    database.initialize()
    return database


@mcp.tool
def list_tasks(request: ListTasksInput) -> TaskListOutput:
    """List local tasks, optionally filtered by status or due date."""

    return TaskListOutput(tasks=_database().list_tasks(request))


@mcp.tool
def list_calendar_events(
    request: ListCalendarEventsInput,
) -> CalendarEventListOutput:
    """List local calendar events, optionally filtered by a time window."""

    return CalendarEventListOutput(events=_database().list_calendar_events(request))


@mcp.tool
def create_task(request: TaskCreateInput) -> Task:
    """Create one task in the local SQLite mock and return the saved task."""

    return _database().create_task(request)


@mcp.tool
def create_calendar_event(request: CalendarEventCreateInput) -> CalendarEvent:
    """Create one calendar event in the local SQLite mock and return the saved event."""

    return _database().create_calendar_event(request)


def main() -> None:
    """Start the MCP server over stdin/stdout."""

    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
