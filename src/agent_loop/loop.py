"""A bounded, manual Anthropic Messages API tool-use loop."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

from .models import (
    HardLimits,
    MessageRecord,
    RunSnapshot,
    ToolExecutionEvent,
    UsageTotals,
)
from .pricing import BudgetExceededError, check_pre_call_limits, pricing_for
from .snapshots import SnapshotStore
from .tools import ToolDefinition, ToolDispatcher

MODEL_ID = "claude-opus-5-5"


class MessagesAPI(Protocol):
    def create(self, **kwargs: Any) -> Any: ...

    def count_tokens(self, **kwargs: Any) -> Any: ...


class AnthropicClient(Protocol):
    messages: MessagesAPI


class AgentLoop:
    """Own the tool-use loop while delegating tool execution to application code.

    The loop does not import an MCP client. Integrators can adapt an MCP client to
    ``ToolDispatcher`` later, without coupling model control flow to that choice.
    """

    def __init__(
        self,
        *,
        client: AnthropicClient,
        dispatcher: ToolDispatcher,
        tools: Sequence[ToolDefinition[Any, Any]],
        system: str = "",
        model: str = MODEL_ID,
        limits: HardLimits | None = None,
        snapshot_store: SnapshotStore,
    ) -> None:
        if model != MODEL_ID:
            raise ValueError(f"This component is configured for {MODEL_ID!r}, not {model!r}")
        if len({tool.name for tool in tools}) != len(tools):
            raise ValueError("tool names must be unique")
        self.client = client
        self.dispatcher = dispatcher
        self.tools = {tool.name: tool for tool in tools}
        self.system = system
        self.model = model
        self.limits = limits or HardLimits()
        self.snapshot_store = snapshot_store
        self._agent_fingerprint = self._fingerprint()

    def start(self, user_input: str) -> RunSnapshot:
        """Create and persist a new run before making any model request."""

        snapshot = RunSnapshot(
            agent_fingerprint=self._agent_fingerprint,
            model=self.model,
            system=self.system,
            limits=self.limits,
            messages=[MessageRecord(role="user", content=user_input)],
        )
        self.snapshot_store.save(snapshot)
        return snapshot

    def resume(self) -> RunSnapshot:
        """Load and continue the snapshot associated with this loop configuration."""

        snapshot = self.snapshot_store.load()
        self._validate_snapshot(snapshot)
        return self.run(snapshot)

    def run(self, snapshot: RunSnapshot) -> RunSnapshot:
        """Continue until completion or a limit halts the run.

        Every assistant block is persisted verbatim before a local tool can run;
        every tool result is appended as one user message, never spliced into the
        prior history. This is compatible with preserved-thinking conversations.
        """

        self._validate_snapshot(snapshot)
        if snapshot.status != "running":
            return snapshot
        if hasattr(self.dispatcher, "set_run_id"):
            self.dispatcher.set_run_id(snapshot.run_id)

        while snapshot.status == "running":
            if self._has_pending_tool_results(snapshot):
                self._resolve_pending_tools(snapshot)
                continue

            try:
                input_tokens = self._count_input_tokens(snapshot)
                check_pre_call_limits(
                    limits=snapshot.limits,
                    usage=snapshot.usage,
                    steps=snapshot.steps,
                    pricing=pricing_for(snapshot.model),
                    next_input_tokens=input_tokens,
                )
            except BudgetExceededError as error:
                snapshot.status = "halted"
                snapshot.halt_reason = str(error)
                self.snapshot_store.save(snapshot)
                return snapshot

            response = self.client.messages.create(
                model=snapshot.model,
                max_tokens=snapshot.limits.max_tokens_per_call,
                system=snapshot.system,
                thinking={"type": "adaptive"},
                output_config={"effort": "high"},
                tools=[tool.api_definition() for tool in self.tools.values()],
                messages=[message.model_dump(mode="json") for message in snapshot.messages],
            )
            snapshot.steps += 1
            snapshot.usage = snapshot.usage.plus(self._response_usage(response, snapshot.model))
            snapshot.messages.append(
                MessageRecord(role="assistant", content=_as_json_value(_value(response, "content")))
            )
            self.snapshot_store.save(snapshot)

            tool_calls = _tool_calls(_value(response, "content"))
            if tool_calls:
                continue

            final_text = _text_content(_value(response, "content"))
            stop_reason = _value(response, "stop_reason")
            if stop_reason == "end_turn":
                snapshot.status = "completed"
                snapshot.final_text = final_text
            elif stop_reason == "pause_turn":
                # The just-appended complete assistant content is the required resume input.
                continue
            else:
                snapshot.status = "halted"
                snapshot.final_text = final_text or None
                snapshot.halt_reason = f"model stopped with {stop_reason!r}"
            self.snapshot_store.save(snapshot)

        return snapshot

    def _resolve_pending_tools(self, snapshot: RunSnapshot) -> None:
        calls = _tool_calls(snapshot.messages[-1].content)
        latest = _latest_tool_events(snapshot.tool_events)
        results: list[dict[str, Any]] = []

        for call in calls:
            event = latest.get(call["id"])
            if event is None:
                planned = ToolExecutionEvent(
                    event="planned",
                    tool_use_id=call["id"],
                    tool_name=call["name"],
                    tool_input=call["input"],
                )
                snapshot.tool_events.append(planned)
                self.snapshot_store.save(snapshot)  # durable intent before side effect
                completed = self._dispatch_once(call)
                snapshot.tool_events.append(completed)
                self.snapshot_store.save(snapshot)
                event = completed
            elif event.event == "planned":
                # A process died after durable intent, so dispatch may already have occurred.
                event = ToolExecutionEvent(
                    event="interrupted",
                    tool_use_id=call["id"],
                    tool_name=call["name"],
                    tool_input=call["input"],
                    result_content=(
                        "Tool call was interrupted after it may have been dispatched; "
                        "it was not retried automatically."
                    ),
                    is_error=True,
                )
                snapshot.tool_events.append(event)
                self.snapshot_store.save(snapshot)

            assert event.result_content is not None
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": event.result_content,
                    "is_error": event.is_error,
                }
            )

        snapshot.messages.append(MessageRecord(role="user", content=results))
        self.snapshot_store.save(snapshot)

    def _dispatch_once(self, call: dict[str, Any]) -> ToolExecutionEvent:
        try:
            tool = self.tools[call["name"]]
            typed_input = tool.parse_input(call["input"])
            typed_output = tool.parse_output(self.dispatcher.dispatch(tool.name, typed_input))
            content = json.dumps(typed_output.model_dump(mode="json"), sort_keys=True)
            return ToolExecutionEvent(
                event="completed",
                tool_use_id=call["id"],
                tool_name=call["name"],
                tool_input=call["input"],
                result_content=content,
            )
        except (KeyError, ValidationError, TypeError, ValueError) as error:
            return ToolExecutionEvent(
                event="completed",
                tool_use_id=call["id"],
                tool_name=call["name"],
                tool_input=call["input"],
                result_content=f"Tool validation or dispatch error: {error}",
                is_error=True,
            )
        except Exception as error:  # Dispatcher failures are returned to Claude, not hidden.
            return ToolExecutionEvent(
                event="completed",
                tool_use_id=call["id"],
                tool_name=call["name"],
                tool_input=call["input"],
                result_content=f"Tool execution failed: {type(error).__name__}: {error}",
                is_error=True,
            )

    def _count_input_tokens(self, snapshot: RunSnapshot) -> int:
        count = self.client.messages.count_tokens(
            model=snapshot.model,
            system=snapshot.system,
            tools=[tool.api_definition() for tool in self.tools.values()],
            messages=[message.model_dump(mode="json") for message in snapshot.messages],
        )
        return int(_value(count, "input_tokens"))

    def _response_usage(self, response: Any, model: str) -> UsageTotals:
        usage = _value(response, "usage")
        raw = UsageTotals(
            input_tokens=int(_value(usage, "input_tokens", 0)),
            cache_creation_input_tokens=int(_value(usage, "cache_creation_input_tokens", 0)),
            cache_read_input_tokens=int(_value(usage, "cache_read_input_tokens", 0)),
            output_tokens=int(_value(usage, "output_tokens", 0)),
        )
        actual_model = str(_value(response, "model", model))
        return raw.model_copy(update={"cost_usd": pricing_for(actual_model).cost(raw)})

    def _has_pending_tool_results(self, snapshot: RunSnapshot) -> bool:
        return bool(snapshot.messages) and snapshot.messages[-1].role == "assistant" and bool(
            _tool_calls(snapshot.messages[-1].content)
        )

    def _validate_snapshot(self, snapshot: RunSnapshot) -> None:
        if snapshot.agent_fingerprint != self._agent_fingerprint:
            raise ValueError("snapshot belongs to a different model, system prompt, or tool schema")
        if snapshot.model != self.model or snapshot.system != self.system:
            raise ValueError("snapshot model or system prompt differs from this loop")

    def _fingerprint(self) -> str:
        stable_config = {
            "model": self.model,
            "system": self.system,
            "tools": [tool.api_definition() for tool in self.tools.values()],
        }
        encoded = json.dumps(stable_config, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def _value(source: Any, name: str, default: Any = None) -> Any:
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _as_json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_as_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _as_json_value(item) for key, item in value.items()}
    raise TypeError(f"cannot serialize response content of type {type(value).__name__}")


def _tool_calls(content: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for block in content or []:
        if _value(block, "type") == "tool_use":
            calls.append(
                {
                    "id": str(_value(block, "id")),
                    "name": str(_value(block, "name")),
                    "input": _as_json_value(_value(block, "input", {})),
                }
            )
    return calls


def _text_content(content: Any) -> str:
    return "".join(
        str(_value(block, "text", ""))
        for block in content or []
        if _value(block, "type") == "text"
    )


def _latest_tool_events(events: Sequence[ToolExecutionEvent]) -> dict[str, ToolExecutionEvent]:
    return {event.tool_use_id: event for event in events}
