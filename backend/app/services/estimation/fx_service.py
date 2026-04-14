"""FX service integration with provider metadata, caching, and fallback handling."""

from __future__ import annotations

import logging
from decimal import Decimal

from app.services.estimation.catalog import CURRENCY, DEFAULT_CONVERSION_RATES, SUPPORTED_CURRENCIES
from app.services.estimation.models import to_decimal

logger = logging.getLogger(__name__)


def build_fx_service(graph_data: dict) -> dict:
    config = graph_data.get("fx_service", {})
    return {
        "provider": config.get("provider", "external_api"),
        "refresh_interval": config.get("refresh_interval", "1h"),
        "cache_enabled": bool(config.get("cache_enabled", True)),
    }


def build_fx_fallback(graph_data: dict) -> dict:
    config = graph_data.get("fx_fallback", {})
    return {
        "enabled": bool(config.get("enabled", True)),
        "last_known_rate": bool(config.get("last_known_rate", True)),
        "used": False,
    }


def resolve_currency_system(graph_data: dict, fx_service: dict, fx_fallback: dict) -> tuple[dict, dict]:
    raw_currency = graph_data.get("currency_system", {})
    live_rates = _fetch_live_rates(graph_data, fx_service)
    fallback_used = False

    if not live_rates and fx_fallback["enabled"]:
        live_rates = _load_fallback_rates(graph_data, raw_currency)
        fallback_used = True

    conversion_rates = {code: rate for code, rate in DEFAULT_CONVERSION_RATES.items()}
    for code, rate in live_rates.items():
        conversion_rates[str(code).upper()] = to_decimal(rate)

    supported = raw_currency.get("supported_currencies") or list(SUPPORTED_CURRENCIES)
    supported_currencies: list[str] = []
    for code in supported:
        normalized = str(code).upper()
        if normalized not in supported_currencies:
            supported_currencies.append(normalized)
        conversion_rates.setdefault(normalized, Decimal("0"))

    if CURRENCY not in supported_currencies:
        supported_currencies.insert(0, CURRENCY)
    conversion_rates[CURRENCY] = Decimal("1.00")

    if live_rates:
        logger.info("fx_rate_fetched: provider=%s currencies=%s", fx_service["provider"], ",".join(supported_currencies))

    fx_fallback["used"] = fallback_used

    return {
        "base_currency": CURRENCY,
        "supported_currencies": supported_currencies,
        "conversion_rates": conversion_rates,
    }, fx_fallback


def _fetch_live_rates(graph_data: dict, fx_service: dict) -> dict:
    live_rates = graph_data.get("fx_live_rates")
    if isinstance(live_rates, dict) and live_rates:
        return live_rates

    provider_payload = graph_data.get("fx_provider_payload")
    if isinstance(provider_payload, dict) and provider_payload.get("provider") == fx_service["provider"]:
        return provider_payload.get("rates", {})

    return {}


def _load_fallback_rates(graph_data: dict, raw_currency: dict) -> dict:
    if isinstance(graph_data.get("fx_last_known_rates"), dict):
        return graph_data["fx_last_known_rates"]
    if isinstance(raw_currency.get("conversion_rates"), dict):
        return raw_currency["conversion_rates"]
    return DEFAULT_CONVERSION_RATES
