"""Approval gates and append-only audit logging for tool dispatch."""

from .gate import ApprovalGate, ApprovalRequiredError, DispatchResult
from .logging import JsonlAuditLogger, redact_value
from .models import (
    ApprovalDecision,
    ToolCallRequest,
    ToolCallResult,
    ToolError,
)
from .prompts import ApprovalPrompt, TerminalApprovalPrompt

__all__ = [
    "ApprovalDecision",
    "ApprovalGate",
    "ApprovalPrompt",
    "ApprovalRequiredError",
    "DispatchResult",
    "JsonlAuditLogger",
    "TerminalApprovalPrompt",
    "ToolCallRequest",
    "ToolCallResult",
    "ToolError",
    "redact_value",
]

__version__ = "0.1.0"
