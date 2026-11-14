"""First-party API price table and conservative pre-call reservation checks."""

from __future__ import annotations

from decimal import Decimal

from .models import HardLimits, UsageTotals


MILLION = Decimal("1000000")


class UnknownModelPricingError(ValueError):
    """Raised instead of guessing a price for a model with no configured rate."""


class BudgetExceededError(RuntimeError):
    """Raised before a Messages API call that could exceed a hard run limit."""


class ModelPricing:
    """USD-per-million-token rates for a first-party Anthropic model."""

    def __init__(
        self,
        *,
        input_per_million: Decimal,
        output_per_million: Decimal,
        cache_write_per_million: Decimal | None = None,
        cache_read_per_million: Decimal | None = None,
    ) -> None:
        self.input_per_million = input_per_million
        self.output_per_million = output_per_million
        self.cache_write_per_million = cache_write_per_million or input_per_million
        self.cache_read_per_million = cache_read_per_million or input_per_million

    def cost(self, usage: UsageTotals) -> Decimal:
        return (
            Decimal(usage.input_tokens) * self.input_per_million
            + Decimal(usage.cache_creation_input_tokens) * self.cache_write_per_million
            + Decimal(usage.cache_read_input_tokens) * self.cache_read_per_million
            + Decimal(usage.output_tokens) * self.output_per_million
        ) / MILLION

    def maximum_next_call(self, input_tokens: int, max_output_tokens: int) -> UsageTotals:
        """Return an upper bound when no prompt-cache behavior is requested."""

        return UsageTotals(
            input_tokens=input_tokens,
            output_tokens=max_output_tokens,
            cost_usd=(
                Decimal(input_tokens) * self.input_per_million
                + Decimal(max_output_tokens) * self.output_per_million
            )
            / MILLION,
        )


# First-party standard pricing. Add a rate explicitly before allowing another model.
MODEL_PRICING: dict[str, ModelPricing] = {
    "claude-opus-5-5": ModelPricing(
        input_per_million=Decimal("4.00"),
        output_per_million=Decimal("20.00"),
        cache_write_per_million=Decimal("5.00"),
        cache_read_per_million=Decimal("0.20"),
    ),
}


def pricing_for(model: str) -> ModelPricing:
    try:
        return MODEL_PRICING[model]
    except KeyError as error:
        raise UnknownModelPricingError(
            f"No price table exists for {model!r}; refusing to make a budgeted call."
        ) from error


def check_pre_call_limits(
    *,
    limits: HardLimits,
    usage: UsageTotals,
    steps: int,
    pricing: ModelPricing,
    next_input_tokens: int,
) -> None:
    """Reject a request before it is sent if its worst case crosses a hard limit."""

    if steps >= limits.max_steps:
        raise BudgetExceededError(
            f"step limit reached ({steps}/{limits.max_steps}); no API request was sent"
        )

    reservation = pricing.maximum_next_call(next_input_tokens, limits.max_tokens_per_call)
    reserved_usage = usage.plus(reservation)

    if limits.max_total_tokens is not None and reserved_usage.token_units > limits.max_total_tokens:
        raise BudgetExceededError(
            "token limit would be exceeded before request "
            f"({reserved_usage.token_units}/{limits.max_total_tokens} reserved)"
        )

    if limits.max_cost_usd is not None and reserved_usage.cost_usd > limits.max_cost_usd:
        raise BudgetExceededError(
            "dollar limit would be exceeded before request "
            f"(${reserved_usage.cost_usd:.6f}/${limits.max_cost_usd:.6f} reserved)"
        )
