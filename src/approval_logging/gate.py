"""Approval-aware tool dispatch that produces one audit event per call."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from .logging import JsonlAuditLogger
from .models import ApprovalDecision, ToolCallRequest, ToolCallResult, ToolError
from .prompts import ApprovalPrompt, TerminalApprovalPrompt

WRITE_TOOL_NAMES = frozenset({"create_task", "create_calendar_event"})


class ApprovalRequiredError(PermissionError):
    """Compatibility exception for callers that choose to reject gate results."""


class AuditLogger(Protocol):
    """Minimal logger interface, allowing an in-memory test double."""

    def log(
        self,
        request: ToolCallRequest,
        decision: ApprovalDecision,
        result: ToolCallResult,
    ) -> None:
        """Persist a completed tool-call audit event."""


class DispatchResult(BaseModel):
    """The approval state and outcome of one completed dispatch attempt."""

    model_config = ConfigDict(extra="forbid")

    approval_decision: ApprovalDecision
    tool_result: ToolCallResult


ToolHandler = Callable[[ToolCallRequest], ToolCallResult | Any]


class ApprovalGate:
    """Gate designated write tools before dispatch and audit every outcome.

    By default, only ``create_task`` and ``create_calendar_event`` require
    approval. Read-only tools are dispatched directly and logged with a
    ``not_required`` decision. Both the approval prompt and audit destination
    are constructor dependencies, keeping automation and tests non-interactive.
    """

    def __init__(
        self,
        *,
        approval_prompt: ApprovalPrompt | None = None,
        log_path: str | Path = "tool_calls.jsonl",
        logger: AuditLogger | None = None,
        write_tools: Iterable[str] = WRITE_TOOL_NAMES,
    ) -> None:
        if logger is not None and log_path != "tool_calls.jsonl":
            raise ValueError("provide either logger or log_path, not both")

        self._approval_prompt = approval_prompt or TerminalApprovalPrompt()
        self._logger = logger or JsonlAuditLogger(log_path)
        self._write_tools = frozenset(write_tools)

    @property
    def write_tools(self) -> frozenset[str]:
        """Names of tools that must be approved before their handlers run."""

        return self._write_tools

    def dispatch(self, request: ToolCallRequest, handler: ToolHandler) -> DispatchResult:
        """Approve when required, invoke at most once, then append an audit log.

        A rejected or unavailable approval never invokes ``handler``. Handler
        exceptions are converted into a serializable failed result and audited.
        Audit logger failures are deliberately raised: continuing would violate
        the component's guarantee to record every completed dispatch attempt.
        """

        if request.tool_name in self._write_tools:
            approved, approval_error = self._request_approval(request)
            if not approved:
                result = ToolCallResult(
                    success=False,
                    error=ToolError(
                        type="ApprovalPromptError" if approval_error else "ApprovalRejected",
                        message=approval_error or "human approval was not granted",
                    ),
                )
                return self._audit(request, ApprovalDecision.REJECTED, result)
            decision = ApprovalDecision.APPROVED
        else:
            decision = ApprovalDecision.NOT_REQUIRED

        try:
            handler_result = handler(request)
            result = (
                handler_result
                if isinstance(handler_result, ToolCallResult)
                else ToolCallResult(success=True, result=handler_result)
            )
        except Exception as exc:  # Tool failures must be captured in the audit trail.
            result = ToolCallResult(
                success=False,
                error=ToolError(type=type(exc).__name__, message=str(exc) or type(exc).__name__),
            )

        return self._audit(request, decision, result)

    def _request_approval(self, request: ToolCallRequest) -> tuple[bool, str | None]:
        try:
            return self._approval_prompt.request_approval(request), None
        except Exception as exc:  # A broken prompt must fail closed.
            return False, str(exc) or type(exc).__name__

    def _audit(
        self,
        request: ToolCallRequest,
        decision: ApprovalDecision,
        result: ToolCallResult,
    ) -> DispatchResult:
        self._logger.log(request, decision, result)
        return DispatchResult(approval_decision=decision, tool_result=result)
