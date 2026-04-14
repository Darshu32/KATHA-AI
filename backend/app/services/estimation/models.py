"""Shared estimation models and money helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

TWOPLACES = Decimal("0.01")


def to_decimal(value: Any, default: str = "0") -> Decimal:
    """Convert untrusted numeric input into a Decimal safely."""
    if value is None or value == "":
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_money(value: Decimal) -> Decimal:
    return value.quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def decimal_to_float(value: Decimal) -> float:
    return float(round_money(value))


@dataclass(slots=True)
class EstimateItem:
    item: str
    category: str
    quantity: Decimal
    unit: str
    base_unit_cost: Decimal
    currency: str = "INR"
    subcategory: str | None = None
    material: str = ""
    quality: str = "standard"
    style_tier: str = "standard"
    source: str = "calculated"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PricedItem:
    item: str
    category: str
    quantity: Decimal
    unit: str
    base_unit_cost: Decimal
    unit_cost: Decimal
    total_cost: Decimal
    currency: str
    subcategory: str | None
    material: str
    quality: str
    style_tier: str
    source: str
    factors: dict[str, Decimal]
    metadata: dict[str, Any] = field(default_factory=dict)
