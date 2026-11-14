"""Human approval prompt interfaces and the secure terminal default."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from .models import ToolCallRequest


class ApprovalPrompt(Protocol):
    """A human-facing approval mechanism that can be replaced in tests."""

    def request_approval(self, request: ToolCallRequest) -> bool:
        """Return ``True`` only when the tool call has human approval."""


class TerminalApprovalPrompt:
    """Ask a human in the terminal, defaulting safely to rejection.

    Only ``y`` and ``yes`` (case-insensitive, surrounding whitespace ignored)
    approve a call. EOF and an interrupted prompt also reject the call.
    """

    _AFFIRMATIVE_ANSWERS = frozenset({"y", "yes"})

    def __init__(self, input_fn: Callable[[str], str] = input) -> None:
        self._input_fn = input_fn

    def request_approval(self, request: ToolCallRequest) -> bool:
        prompt = (
            f"Approve write tool '{request.tool_name}' for run "
            f"'{request.run_id}'? [y/N]: "
        )
        try:
            answer = self._input_fn(prompt)
        except (EOFError, KeyboardInterrupt):
            return False
        return isinstance(answer, str) and answer.strip().casefold() in self._AFFIRMATIVE_ANSWERS
