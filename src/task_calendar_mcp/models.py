"""Typed request and response models for the local task/calendar tools."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskStatus(StrEnum):
    """The lifecycle states supported by the local task mock."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskCreateInput(BaseModel):
    """Fields accepted when a task is created."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4_000)
    due_at: datetime | None = None
    status: TaskStatus = TaskStatus.TODO

    @field_validator("due_at")
    @classmethod
    def due_at_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None


class Task(BaseModel):
    """A task persisted by the mock."""

    id: int
    title: str
    description: str | None
    due_at: datetime | None
    status: TaskStatus
    created_at: datetime


class ListTasksInput(BaseModel):
    """Optional filters for listing tasks."""

    status: TaskStatus | None = None
    due_before: datetime | None = None
    limit: int = Field(default=50, ge=1, le=100)


class TaskListOutput(BaseModel):
    """The tasks returned by ``list_tasks``."""

    tasks: list[Task]


class CalendarEventCreateInput(BaseModel):
    """Fields accepted when a calendar event is created."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime
    description: str | None = Field(default=None, max_length=4_000)
    location: str | None = Field(default=None, max_length=500)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def timestamps_must_be_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def end_must_follow_start(self) -> "CalendarEventCreateInput":
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be later than starts_at")
        return self


class CalendarEvent(BaseModel):
    """A calendar event persisted by the mock."""

    id: int
    title: str
    starts_at: datetime
    ends_at: datetime
    description: str | None
    location: str | None
    created_at: datetime


class ListCalendarEventsInput(BaseModel):
    """Optional time-window filters for listing calendar events."""

    starts_after: datetime | None = None
    ends_before: datetime | None = None
    limit: int = Field(default=50, ge=1, le=100)


class CalendarEventListOutput(BaseModel):
    """The events returned by ``list_calendar_events``."""

    events: list[CalendarEvent]
