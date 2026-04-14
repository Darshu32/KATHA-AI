"""History storage metadata and estimate history extraction."""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.estimation.models import round_money, to_decimal


def build_history_storage(graph_data: dict) -> dict:
    return {
        "type": "database",
        "linked_to": graph_data.get("project_id", "project_id"),
    }


def build_history_entries(graph_data: dict, pricing_adjustments: dict) -> list[dict]:
    history = []

    for entry in graph_data.get("history", []):
        timestamp = entry.get("timestamp")
        total = entry.get("total")
        if timestamp is None or total is None:
            continue
        history.append(
            {
                "timestamp": timestamp,
                "total": float(round_money(to_decimal(total))),
            }
        )

    history.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total": float(round_money(to_decimal(pricing_adjustments["final_total"]))),
        }
    )
    return history
