"""Typed models shared by the agent loop and its persisted snapshots."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator


class StrictModel(BaseModel):
    """Base model that rejects configuration typos and unexpected persisted data."""

    model_config = ConfigDict(extra="forbid")


class HardLimits(StrictModel):
    """Limits checked before each model request, not after a run has already overspent."""

    max_steps: int = Field(default=8, ge=1)
    max_tokens_per_call: int = Field(default=4096, ge=1, le=128_000)
    max_total_tokens: int | None = Field(default=80_000, ge=1)
    max_cost_usd: Decimal | None = Field(default=Decimal("1.00"), ge=Decimal("0"))


class UsageTotals(StrictModel):
    """Aggregated API usage. Cache fields are retained for accurate post-call accounting."""

    input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    cache_read_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cost_usd: Decimal = Field(default=Decimal("0"), ge=Decimal("0"))

    @property
    def token_units(self) -> int:
        """Return all reported token units, including cache activity."""

        return (
            self.input_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
            + self.output_tokens
        )

    def plus(self, other: "UsageTotals") -> "UsageTotals":
        return UsageTotals(
            input_tokens=self.input_tokens + other.input_tokens,
            cache_creation_input_tokens=(
                self.cache_creation_input_tokens + other.cache_creation_input_tokens
            ),
            cache_read_input_tokens=self.cache_read_input_tokens + other.cache_read_input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )


class MessageRecord(StrictModel):
    """A lossless Messages API history entry suitable for JSON persistence."""

    role: Literal["user", "assistant"]
    content: JsonValue


class ToolExecutionEvent(StrictModel):
    """Append-only journal event for an individual client-side tool call.

    A ``planned`` event is durably recorded before dispatch. A completed event is
    appended after dispatch. On resume, an unmatched planned event is considered
    uncertain and is deliberately not dispatched again.
    """

    event: Literal["planned", "completed", "interrupted"]
    tool_use_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_input: JsonValue
    result_content: str | None = None
    is_error: bool = False

    @model_validator(mode="after")
    def result_events_have_content(self) -> "ToolExecutionEvent":
        if self.event in {"completed", "interrupted"} and self.result_content is None:
            raise ValueError("completed and interrupted events require result_content")
        return self


class RunSnapshot(StrictModel):
    """Durable state for one append-only agent run."""

    schema_version: Literal[1] = 1
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_fingerprint: str = Field(min_length=64, max_length=64)
    model: str = Field(min_length=1)
    system: str = ""
    limits: HardLimits
    messages: list[MessageRecord] = Field(min_length=1)
    tool_events: list[ToolExecutionEvent] = Field(default_factory=list)
    usage: UsageTotals = Field(default_factory=UsageTotals)
    steps: int = Field(default=0, ge=0)
    status: Literal["running", "completed", "halted", "failed"] = "running"
    final_text: str | None = None
    halt_reason: str | None = None

    @model_validator(mode="after")
    def history_starts_with_user(self) -> "RunSnapshot":
        if self.messages[0].role != "user":
            raise ValueError("message history must begin with a user message")
        return self
