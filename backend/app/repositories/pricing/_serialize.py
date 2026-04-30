"""Shared row → dict serializers for pricing repositories.

Repositories return plain JSON-safe dicts rather than detached ORM
instances. Reasons:

- Caching with Redis requires JSON-serializable values.
- The cost-engine knowledge dict mirrors these shapes 1:1, so the
  shape becomes the *contract* with downstream code.
- Tests can assert against dicts without dragging the ORM session
  along.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def material_price_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "slug": row.slug,
        "region": row.region,
        "name": row.name,
        "category": row.category,
        "basis_unit": row.basis_unit,
        "price_inr_low": row.price_inr_low,
        "price_inr_high": row.price_inr_high,
        "lead_time_weeks_low": row.lead_time_weeks_low,
        "lead_time_weeks_high": row.lead_time_weeks_high,
        "available_in_cities": list(row.available_in_cities) if row.available_in_cities else None,
        "extras": dict(row.extras or {}),
        "version": row.version,
        "is_current": row.is_current,
        "effective_from": _iso(row.effective_from),
        "effective_to": _iso(row.effective_to),
        "source": row.source,
        "source_ref": row.source_ref,
    }


def labor_rate_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "trade": row.trade,
        "region": row.region,
        "rate_inr_per_hour_low": row.rate_inr_per_hour_low,
        "rate_inr_per_hour_high": row.rate_inr_per_hour_high,
        "notes": row.notes,
        "version": row.version,
        "effective_from": _iso(row.effective_from),
        "effective_to": _iso(row.effective_to),
        "source": row.source,
    }


def trade_hour_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "trade": row.trade,
        "complexity": row.complexity,
        "hours_low": row.hours_low,
        "hours_high": row.hours_high,
        "notes": row.notes,
        "version": row.version,
        "source": row.source,
    }


def city_index_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "city_slug": row.city_slug,
        "display_name": row.display_name,
        "state": row.state,
        "tier": row.tier,
        "index_multiplier": row.index_multiplier,
        "remote_lead_time_weeks_low": row.remote_lead_time_weeks_low,
        "remote_lead_time_weeks_high": row.remote_lead_time_weeks_high,
        "aliases": list(row.aliases) if row.aliases else None,
        "version": row.version,
        "effective_from": _iso(row.effective_from),
        "source": row.source,
    }


def cost_factor_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "factor_key": row.factor_key,
        "value_low": row.value_low,
        "value_high": row.value_high,
        "unit": row.unit,
        "description": row.description,
        "version": row.version,
        "effective_from": _iso(row.effective_from),
        "source": row.source,
    }


def pricing_snapshot_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": _iso(row.created_at),
        "target_type": row.target_type,
        "target_id": row.target_id,
        "project_id": row.project_id,
        "city": row.city,
        "market_segment": row.market_segment,
        "snapshot_data": dict(row.snapshot_data or {}),
        "source_versions": dict(row.source_versions or {}),
        "actor_id": row.actor_id,
        "actor_kind": row.actor_kind,
        "request_id": row.request_id,
    }
