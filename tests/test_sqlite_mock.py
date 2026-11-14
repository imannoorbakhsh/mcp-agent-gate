from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from task_calendar_mcp.database import TaskCalendarDatabase
from task_calendar_mcp.models import CalendarEventCreateInput, ListTasksInput, TaskCreateInput


def test_sqlite_mock_seeds_once_and_creates_task(tmp_path: Path) -> None:
    database = TaskCalendarDatabase(tmp_path / "mock.sqlite3")
    database.initialize()
    database.initialize()

    created = database.create_task(TaskCreateInput(title="Bounded demo"))

    tasks = database.list_tasks(ListTasksInput(limit=100))
    assert [task.id for task in tasks].count(created.id) == 1
    assert len(tasks) == 3


def test_calendar_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone"):
        CalendarEventCreateInput(
            title="Unsafe time",
            starts_at=datetime(2030, 1, 1, 10),
            ends_at=datetime(2030, 1, 1, 11),
        )
