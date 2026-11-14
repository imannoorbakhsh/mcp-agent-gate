"""Append-only JSON Lines audit logging with recursive secret redaction."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .models import ApprovalDecision, AuditRecord, ToolCallRequest, ToolCallResult

_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "api_key",
        "apikey",
        "authorization",
        "credential",
        "cookie",
        "password",
        "secret",
        "token",
    }
)


class AuditLogError(RuntimeError):
    """Raised when an audit record cannot be made durable."""


def redact_value(value: Any) -> Any:
    """Return a JSON-compatible copy with values under sensitive keys hidden.

    Redaction is recursive and case-insensitive. It intentionally applies to
    audit results too, because tool output can contain secrets even when its
    input did not.
    """

    if isinstance(value, Mapping):
        return {
            str(key): _REDACTED if _is_sensitive_key(str(key)) else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return [redact_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_").replace(" ", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


class JsonlAuditLogger:
    """Write one durable audit record per line without ever truncating a log.

    The log path is injected at construction time so tests can use a temporary
    path and production code can select a host-owned audit location.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def log(
        self,
        request: ToolCallRequest,
        decision: ApprovalDecision,
        result: ToolCallResult,
    ) -> None:
        """Append a complete, redacted record and synchronise it to disk."""

        record = AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            run_id=request.run_id,
            tool_name=request.tool_name,
            input=redact_value(request.input),
            approval_decision=decision,
            result=redact_value(result.result) if result.success else None,
            error=result.error,
        )
        payload = (json.dumps(record.model_dump(mode="json"), default=str, sort_keys=True) + "\n").encode(
            "utf-8"
        )

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(
                self.path,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o600,
            )
            try:
                written = os.write(descriptor, payload)
                if written != len(payload):
                    raise OSError("incomplete write to audit log")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise AuditLogError(f"unable to append audit record to {self.path}") from exc
