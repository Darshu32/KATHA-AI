"""Versioned catalog metadata helpers."""

from __future__ import annotations

from app.services.estimation.catalog import (
    DEFAULT_CATALOG_LAST_UPDATED,
    DEFAULT_CATALOG_VERSION,
)


def build_catalog_metadata(graph_data: dict) -> dict:
    return {
        "version": graph_data.get("catalog_version", DEFAULT_CATALOG_VERSION),
        "last_updated": graph_data.get("catalog_last_updated", DEFAULT_CATALOG_LAST_UPDATED),
    }
