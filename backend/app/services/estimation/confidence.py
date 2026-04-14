"""Weighted confidence scoring engine."""

from __future__ import annotations

import logging
from decimal import Decimal

from app.services.estimation.models import round_money

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE_WEIGHTS = {
    "data_completeness": Decimal("0.40"),
    "market_accuracy": Decimal("0.35"),
    "item_coverage": Decimal("0.25"),
}


def build_confidence_score(
    graph_data: dict,
    area_summary: dict,
    validation_errors: list[str],
    fallback_triggered: bool,
    breakdown_count: int,
    fx_fallback_used: bool,
) -> dict:
    factor_scores = {
        "data_completeness": _data_completeness_score(graph_data, area_summary),
        "market_accuracy": _market_accuracy_score(graph_data, validation_errors, fx_fallback_used),
        "item_coverage": _item_coverage_score(graph_data, breakdown_count, fallback_triggered),
    }
    weights = _load_weights(graph_data)
    weighted_score = sum((factor_scores[key] * weight for key, weight in weights.items()), Decimal("0"))
    weighted_score = max(Decimal("0.0"), min(weighted_score, Decimal("0.99")))

    if weighted_score >= Decimal("0.80"):
        level = "high"
    elif weighted_score >= Decimal("0.60"):
        level = "medium"
    else:
        level = "low"

    logger.info("confidence_computed: score=%s level=%s", weighted_score, level)

    return {
        "score": float(round_money(weighted_score)),
        "level": level,
        "factors": {key: float(round_money(value)) for key, value in factor_scores.items()},
        "weighted": True,
        "weights": {key: float(round_money(value)) for key, value in weights.items()},
    }


def _load_weights(graph_data: dict) -> dict[str, Decimal]:
    raw_weights = graph_data.get("confidence_weights", {})
    weights = {key: value for key, value in DEFAULT_CONFIDENCE_WEIGHTS.items()}
    for key, value in raw_weights.items():
        if key in weights:
            weights[key] = Decimal(str(value))
    return weights


def _data_completeness_score(graph_data: dict, area_summary: dict) -> Decimal:
    score = Decimal("1.00")
    if not graph_data.get("materials"):
        score -= Decimal("0.25")
    if not graph_data.get("objects"):
        score -= Decimal("0.20")
    if not area_summary.get("total_sqft"):
        score -= Decimal("0.25")
    return max(score, Decimal("0.0"))


def _market_accuracy_score(graph_data: dict, validation_errors: list[str], fx_fallback_used: bool) -> Decimal:
    score = Decimal("0.95")
    if not (graph_data.get("site") or graph_data.get("region")):
        score -= Decimal("0.15")
    if fx_fallback_used:
        score -= Decimal("0.20")
    if validation_errors:
        score -= Decimal("0.10")
    return max(score, Decimal("0.0"))


def _item_coverage_score(graph_data: dict, breakdown_count: int, fallback_triggered: bool) -> Decimal:
    objects = graph_data.get("objects", [])
    expected_items = max(len(objects), 1)
    ratio = Decimal(str(min(breakdown_count / expected_items, 1.0)))
    if fallback_triggered:
        ratio -= Decimal("0.10")
    return max(ratio, Decimal("0.0"))
