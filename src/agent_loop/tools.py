"""Typed local tool definitions and an injectable dispatcher boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel

InputModelT = TypeVar("InputModelT", bound=BaseModel)
OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


@dataclass(frozen=True)
class ToolDefinition(Generic[InputModelT, OutputModelT]):
    """A typed client-side tool exposed to the Messages API."""

    name: str
    description: str
    input_model: type[InputModelT]
    output_model: type[OutputModelT]

    def api_definition(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        # Strict API tool use requires a closed object schema.
        schema["additionalProperties"] = False
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
            "strict": True,
        }

    def parse_input(self, raw_input: object) -> InputModelT:
        return self.input_model.model_validate(raw_input)

    def parse_output(self, raw_output: object) -> OutputModelT:
        return self.output_model.model_validate(raw_output)


class ToolDispatcher(Protocol):
    """Application-owned boundary; the loop has no dependency on MCP."""

    def dispatch(self, tool_name: str, tool_input: BaseModel) -> BaseModel:
        """Run one validated local tool call and return its typed output."""


class LocalToolDispatcher:
    """Small mapping-based dispatcher suitable for a demo or local integration."""

    def __init__(self, handlers: Mapping[str, Callable[[BaseModel], BaseModel]]) -> None:
        self._handlers = dict(handlers)

    def dispatch(self, tool_name: str, tool_input: BaseModel) -> BaseModel:
        try:
            handler = self._handlers[tool_name]
        except KeyError as error:
            raise KeyError(f"No local handler is registered for tool {tool_name!r}") from error
        return handler(tool_input)
