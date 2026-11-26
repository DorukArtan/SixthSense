"""Step 7 - Result presentation.

Owner: Nilsu Kına

Money columns (*_u) are integer units: 1 GBP = 10,000 units. Convert with
Decimal after aggregation and round half up to two decimals for display only.
Chart choice: category ranking -> "bar", time series -> "line",
single scalar -> "value". Keep column headers for empty results.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from rowsetta.types import ChartKind, QueryResult

UNITS_PER_GBP = Decimal(10_000)


def units_to_gbp(units: int) -> Decimal:
    return (Decimal(units) / UNITS_PER_GBP).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def choose_chart(result: QueryResult) -> ChartKind | None:
    raise NotImplementedError("present.choose_chart")


def to_display_rows(result: QueryResult) -> tuple[list[str], list[tuple]]:
    """Column labels and rows with *_u columns converted to GBP."""
    raise NotImplementedError("present.to_display_rows")
