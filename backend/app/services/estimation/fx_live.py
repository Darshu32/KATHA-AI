"""Live foreign-exchange rates — INR → {USD, EUR, AED, …}.

Replaces the static ``DEFAULT_CONVERSION_RATES`` fallback with a real forex
feed so a Dubai/Germany project is costed at *today's* rate, not a baked-in
constant. Uses a free, key-less provider (open.er-api.com), caches for the
refresh interval, and returns ``{}`` on any failure so callers fall back to the
static card — FX must never break an estimate.

No API key required. Kept dependency-free (httpx is already a dep) and with NO
import of ``catalog`` so it can be imported from there without a cycle.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

logger = logging.getLogger(__name__)

_PROVIDER_URL = "https://open.er-api.com/v6/latest/INR"
_TTL_SECONDS = 3600.0  # 1h, matching the fx_service refresh_interval default
_cache: dict[str, object] = {"rates": {}, "at": 0.0}


def get_live_inr_rates() -> dict[str, Decimal]:
    """INR→{code} live rates (cached ~1h). Returns ``{}`` when unavailable so the
    caller falls back to the static rate card. Never raises."""
    now = time.time()
    cached = _cache.get("rates") or {}
    if cached and (now - float(_cache.get("at", 0.0))) < _TTL_SECONDS:
        return cached  # type: ignore[return-value]
    try:
        import httpx
        resp = httpx.get(_PROVIDER_URL, timeout=6.0)
        resp.raise_for_status()
        data = resp.json()
        if data.get("result") == "success":
            rates = {
                str(code).upper(): Decimal(str(value))
                for code, value in (data.get("rates") or {}).items()
                if value
            }
            if rates:
                rates.setdefault("INR", Decimal("1"))
                _cache["rates"] = rates
                _cache["at"] = now
                logger.info("fx_live: fetched %d live INR rates", len(rates))
                return rates
    except Exception as exc:  # noqa: BLE001 — FX must never break an estimate
        logger.warning("fx_live: fetch failed (%s); using static fallback", exc)
    # Return a stale cache if we have one, else empty → caller uses the static card.
    return cached  # type: ignore[return-value]
