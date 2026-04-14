"""Cost optimization suggestions for enterprise estimates."""

from __future__ import annotations

from decimal import Decimal

from app.services.estimation.models import round_money, to_decimal


def build_cost_suggestions(payload: dict, pricing_context: dict) -> list[dict]:
    suggestions: list[dict] = []
    final_total = to_decimal(payload["pricing_adjustments"]["final_total"])
    style_tier = pricing_context["style_tier"]

    if style_tier in {"premium", "luxury"}:
        reduced = round_money(final_total * Decimal("0.12"))
        suggestions.append(
            {
                "type": "cost_reduction",
                "message": f"Switch to standard materials to reduce cost by approximately {float(reduced):.2f} INR.",
            }
        )

    return suggestions
