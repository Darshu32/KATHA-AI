"""Currency conversion helpers for estimation payloads."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP

from app.services.estimation.catalog import CURRENCY, DEFAULT_CONVERSION_RATES, SUPPORTED_CURRENCIES
from app.services.estimation.models import round_money, to_decimal


def build_currency_system(graph_data: dict) -> dict:
    provided = graph_data.get("currency_system", {})
    conversion_rates = {code: rate for code, rate in DEFAULT_CONVERSION_RATES.items()}

    for code, rate in provided.get("conversion_rates", {}).items():
        conversion_rates[str(code).upper()] = to_decimal(rate)

    supported = provided.get("supported_currencies") or list(SUPPORTED_CURRENCIES)
    supported_currencies = []
    for code in supported:
        normalized = str(code).upper()
        if normalized not in supported_currencies:
            supported_currencies.append(normalized)
        conversion_rates.setdefault(normalized, Decimal("1.00") if normalized == CURRENCY else Decimal("0"))

    if CURRENCY not in supported_currencies:
        supported_currencies.insert(0, CURRENCY)

    conversion_rates[CURRENCY] = Decimal("1.00")

    return {
        "base_currency": CURRENCY,
        "supported_currencies": supported_currencies,
        "conversion_rates": conversion_rates,
    }


def serialize_currency_system(currency_system: dict) -> dict:
    return {
        "base_currency": currency_system["base_currency"],
        "supported_currencies": currency_system["supported_currencies"],
        "conversion_rates": {
            code: float(rate.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
            for code, rate in currency_system["conversion_rates"].items()
        },
    }


def convert_amount(amount: Decimal, target_currency: str, currency_system: dict) -> Decimal:
    normalized = str(target_currency).upper()
    rate = currency_system["conversion_rates"].get(normalized, Decimal("0"))
    return round_money(amount * rate)


def append_currency_conversions(payload: dict, currency_system: dict) -> dict:
    converted = deepcopy(payload)
    conversions: dict[str, dict] = {}

    final_total = to_decimal(payload["pricing_adjustments"]["final_total"])
    subtotal = sum((to_decimal(section["total_cost"]) for section in payload["estimate"].values()), Decimal("0"))

    for code in currency_system["supported_currencies"]:
        converted_final_total = convert_amount(final_total, code, currency_system)
        converted_subtotal = convert_amount(subtotal, code, currency_system)
        conversions[code] = {
            "subtotal": float(converted_subtotal),
            "final_total": float(converted_final_total),
        }

    converted["currency_system"] = serialize_currency_system(currency_system)
    converted["converted_totals"] = conversions
    return converted
