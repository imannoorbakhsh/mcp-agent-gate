"""Pydantic contracts for tool calls and their outcomes."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ApprovalDecision(str, Enum):
    """The decision recorded for a tool call."""

    NOT_REQUIRED = "not_required"
    APPROVED = "approved"
    REJECTED = "rejected"


class ToolError(BaseModel):
    """A structured, serializable tool failure."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ToolCallRequest(BaseModel):
    """Validated input to a tool dispatch operation.

    ``input`` is intentionally opaque to this component: each tool adapter may
    validate its own domain-specific arguments before dispatch.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)


class ToolCallResult(BaseModel):
    """Validated result returned by a dispatched tool."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    result: Any = None
    error: ToolError | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.success and self.error is not None:
            raise ValueError("successful tool results cannot contain an error")
        if not self.success and self.error is None:
            raise ValueError("failed tool results must contain an error")


class AuditRecord(BaseModel):
    """One append-only JSONL audit event."""

    model_config = ConfigDict(extra="forbid")

    timestamp: str
    run_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    input: dict[str, Any]
    approval_decision: ApprovalDecision
    result: Any = None
    error: ToolError | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.result is not None and self.error is not None:
            raise ValueError("an audit record cannot contain both result and error")
