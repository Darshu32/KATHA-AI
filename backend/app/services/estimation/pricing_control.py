"""Admin-controlled pricing metadata."""

from __future__ import annotations


def build_pricing_control(graph_data: dict) -> dict:
    config = graph_data.get("pricing_control", {})
    return {
        "source": config.get("source", "admin_panel"),
        "editable": bool(config.get("editable", True)),
        "versioned": bool(config.get("versioned", True)),
        "version": config.get("version", graph_data.get("catalog_version", "v2")),
    }
