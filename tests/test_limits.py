from __future__ import annotations

from decimal import Decimal

import pytest

from agent_loop.models import HardLimits, UsageTotals
from agent_loop.pricing import BudgetExceededError, check_pre_call_limits, pricing_for


def test_step_limit_blocks_the_next_model_call() -> None:
    with pytest.raises(BudgetExceededError, match="step limit"):
        check_pre_call_limits(
            limits=HardLimits(max_steps=1),
            usage=UsageTotals(),
            steps=1,
            pricing=pricing_for("claude-opus-5-5"),
            next_input_tokens=1,
        )


def test_dollar_cap_reserves_maximum_next_call() -> None:
    with pytest.raises(BudgetExceededError, match="dollar limit"):
        check_pre_call_limits(
            limits=HardLimits(max_tokens_per_call=1_000, max_cost_usd=Decimal("0.001")),
            usage=UsageTotals(),
            steps=0,
            pricing=pricing_for("claude-opus-5-5"),
            next_input_tokens=1,
        )
