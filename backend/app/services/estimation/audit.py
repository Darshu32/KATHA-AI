"""Audit logging helpers for enterprise estimation flows."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_audit_config(graph_data: dict) -> dict:
    config = graph_data.get("audit", {})
    return {
        "enabled": bool(config.get("enabled", True)),
        "logs": config.get("logs", ["price_change", "config_update", "estimate_generated"]),
    }


def emit_audit_logs(audit_config: dict, payload: dict) -> list[dict]:
    entries = []
    if not audit_config["enabled"]:
        return entries

    estimate_generated = {
        "event": "estimate_generated",
        "status": payload["status"],
        "final_total": payload["pricing_adjustments"]["final_total"],
    }
    entries.append(estimate_generated)

    if payload["fallback"]["triggered"]:
        entries.append({"event": "price_change", "reason": "fallback_triggered"})

    if payload.get("pricing_control", {}).get("versioned"):
        entries.append(
            {
                "event": "config_update",
                "pricing_version": payload["pricing_control"]["version"],
            }
        )

    for entry in entries:
        logger.info("audit_logged: event=%s", entry["event"])

    return entries
