"""Runnable demo using an injected local calculator dispatcher."""

from __future__ import annotations

import argparse
import os
from decimal import Decimal
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from .loop import AgentLoop
from .models import HardLimits
from .snapshots import SnapshotStore
from .tools import LocalToolDispatcher, ToolDefinition


class AddInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left: Decimal
    right: Decimal


class AddOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: Decimal


def _add(arguments: BaseModel) -> BaseModel:
    typed = cast(AddInput, arguments)
    return AddOutput(total=typed.left + typed.right)


def build_demo_loop(*, snapshot_path: Path, max_steps: int, token_budget: int, dollar_budget: Decimal) -> AgentLoop:
    try:
        import anthropic
    except ImportError as error:  # pragma: no cover - an installation error path
        raise SystemExit("Install this component first: pip install -e '.[test]'") from error

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit("Set ANTHROPIC_API_KEY in the environment before running the demo.")

    add_tool = ToolDefinition[AddInput, AddOutput](
        name="add_numbers",
        description="Add two decimal numbers exactly.",
        input_model=AddInput,
        output_model=AddOutput,
    )
    return AgentLoop(
        client=anthropic.Anthropic(api_key=api_key),
        dispatcher=LocalToolDispatcher({"add_numbers": _add}),
        tools=[add_tool],
        system=(
            "Use add_numbers for arithmetic additions. Explain the result briefly after the tool "
            "returns. Do not claim to have run a tool unless its result is in the conversation."
        ),
        limits=HardLimits(
            max_steps=max_steps,
            max_total_tokens=token_budget,
            max_cost_usd=dollar_budget,
        ),
        snapshot_store=SnapshotStore(snapshot_path),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bounded manual Anthropic tool-use loop demo")
    subcommands = parser.add_subparsers(dest="command", required=True)
    demo = subcommands.add_parser("demo", help="start a calculator-assisted run")
    demo.add_argument("prompt", help="user request for Claude")
    resume = subcommands.add_parser("resume", help="resume an existing run snapshot")
    for command in (demo, resume):
        command.add_argument("--snapshot", type=Path, required=True, help="JSON run snapshot path")
        command.add_argument("--max-steps", type=int, default=8)
        command.add_argument("--token-budget", type=int, default=80_000)
        command.add_argument("--dollar-budget", type=Decimal, default=Decimal("1.00"))
    arguments = parser.parse_args(argv)

    loop = build_demo_loop(
        snapshot_path=arguments.snapshot,
        max_steps=arguments.max_steps,
        token_budget=arguments.token_budget,
        dollar_budget=arguments.dollar_budget,
    )
    snapshot = loop.start(arguments.prompt) if arguments.command == "demo" else loop.resume()
    if arguments.command == "demo":
        snapshot = loop.run(snapshot)

    if snapshot.final_text:
        print(snapshot.final_text)
    print(
        f"status={snapshot.status} steps={snapshot.steps} "
        f"tokens={snapshot.usage.token_units} cost=${snapshot.usage.cost_usd:.6f}"
    )
    if snapshot.halt_reason:
        print(f"reason={snapshot.halt_reason}")
    return 0 if snapshot.status == "completed" else 2
