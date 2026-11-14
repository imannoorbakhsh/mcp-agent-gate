"""SQLite persistence for the local task/calendar MCP mock.

All variable data is supplied to SQLite using DB-API placeholders; SQL structure is
fixed in this module.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .models import (
    CalendarEvent,
    CalendarEventCreateInput,
    ListCalendarEventsInput,
    ListTasksInput,
    Task,
    TaskCreateInput,
)

_COMPONENT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = _COMPONENT_ROOT / "data" / "task_calendar.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    due_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('todo', 'in_progress', 'done')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    description TEXT,
    location TEXT,
    created_at TEXT NOT NULL,
    CHECK (ends_at > starts_at)
);

CREATE TABLE IF NOT EXISTS application_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def database_path_from_environment() -> Path:
    """Return the configured local database path without reading any credentials."""

    raw_path = os.environ.get("TASK_CALENDAR_DB_PATH")
    return Path(raw_path).expanduser() if raw_path else DEFAULT_DATABASE_PATH


def _timestamp(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task.model_validate(dict(row))


def _row_to_event(row: sqlite3.Row) -> CalendarEvent:
    return CalendarEvent.model_validate(dict(row))


class TaskCalendarDatabase:
    """Small, synchronous repository used exclusively by the MCP tool handlers."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the schema and insert a deterministic, one-time example dataset."""

        with self._connection() as connection:
            connection.executescript(_SCHEMA)
            seeded = connection.execute(
                "SELECT 1 FROM application_metadata WHERE key = ?",
                ("seeded",),
            ).fetchone()
            if seeded is not None:
                return

            connection.executemany(
                """
                INSERT INTO tasks (title, description, due_at, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        "Review MCP integration",
                        "Confirm the local task/calendar tools are reachable.",
                        "2030-01-15T10:00:00+00:00",
                        "todo",
                        "2030-01-01T09:00:00+00:00",
                    ),
                    (
                        "Prepare weekly update",
                        None,
                        None,
                        "in_progress",
                        "2030-01-02T09:00:00+00:00",
                    ),
                ],
            )
            connection.execute(
                """
                INSERT INTO calendar_events
                    (title, starts_at, ends_at, description, location, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    "Team planning",
                    "2030-01-10T14:00:00+00:00",
                    "2030-01-10T14:30:00+00:00",
                    "Example event seeded by the local mock.",
                    "Conference room A",
                    "2030-01-01T09:00:00+00:00",
                ),
            )
            connection.execute(
                "INSERT INTO application_metadata (key, value) VALUES (?, ?)",
                ("seeded", "true"),
            )

    def list_tasks(self, request: ListTasksInput) -> list[Task]:
        """List tasks matching the typed filters in deterministic due-date order."""

        clauses: list[str] = []
        parameters: list[object] = []
        if request.status is not None:
            clauses.append("status = ?")
            parameters.append(request.status.value)
        if request.due_before is not None:
            clauses.append("due_at IS NOT NULL AND due_at <= ?")
            parameters.append(_timestamp(request.due_before))

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(request.limit)
        query = (
            "SELECT id, title, description, due_at, status, created_at FROM tasks"
            f"{where} ORDER BY due_at IS NULL, due_at ASC, id ASC LIMIT ?"
        )
        with self._connection() as connection:
            return [_row_to_task(row) for row in connection.execute(query, parameters)]

    def create_task(self, request: TaskCreateInput) -> Task:
        """Persist and return one task."""

        created_at = datetime.now().astimezone().isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (title, description, due_at, status, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    request.title,
                    request.description,
                    _timestamp(request.due_at),
                    request.status.value,
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT id, title, description, due_at, status, created_at
                FROM tasks WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        assert row is not None
        return _row_to_task(row)

    def list_calendar_events(self, request: ListCalendarEventsInput) -> list[CalendarEvent]:
        """List events matching the typed filters in ascending start-time order."""

        clauses: list[str] = []
        parameters: list[object] = []
        if request.starts_after is not None:
            clauses.append("starts_at >= ?")
            parameters.append(_timestamp(request.starts_after))
        if request.ends_before is not None:
            clauses.append("ends_at <= ?")
            parameters.append(_timestamp(request.ends_before))

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(request.limit)
        query = (
            "SELECT id, title, starts_at, ends_at, description, location, created_at "
            f"FROM calendar_events{where} ORDER BY starts_at ASC, id ASC LIMIT ?"
        )
        with self._connection() as connection:
            return [_row_to_event(row) for row in connection.execute(query, parameters)]

    def create_calendar_event(self, request: CalendarEventCreateInput) -> CalendarEvent:
        """Persist and return one calendar event."""

        created_at = datetime.now().astimezone().isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO calendar_events
                    (title, starts_at, ends_at, description, location, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    request.title,
                    _timestamp(request.starts_at),
                    _timestamp(request.ends_at),
                    request.description,
                    request.location,
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT id, title, starts_at, ends_at, description, location, created_at
                FROM calendar_events WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        assert row is not None
        return _row_to_event(row)
