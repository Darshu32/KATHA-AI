"""Stage 3E — ergonomics seed builder.

Translates :mod:`app.knowledge.ergonomics` into ``building_standards``
rows tagged ``category='space'`` and ``subcategory='furniture_ergonomics'``.

Why ``space`` (not a new ``ergonomics`` category)?
  - BRD groups space planning + furniture ergonomics together
    (clearance around bed, seat-height ranges, etc.).
  - Reuses the existing 5-category enum without another schema migration.
  - Admin filter UIs can still slice by subcategory.

Slug naming
-----------
  ``ergonomics_<group>_<item>`` e.g. ``ergonomics_chair_dining_chair``,
  ``ergonomics_storage_wardrobe``, ``ergonomics_bed_queen``.

The single special constant ``BED_UNDER_STORAGE_MM`` becomes its own
row ``ergonomics_bed_under_storage`` so callers can fetch it without
parsing.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.knowledge import ergonomics as ergo_kb


def _new_id() -> str:
    return uuid4().hex


def _row(
    slug: str,
    *,
    display_name: str,
    data: dict[str, Any],
    item_group: str,
    notes: str | None = None,
    source_tag: str = "seed:ergonomics",
) -> dict[str, Any]:
    return {
        "id": _new_id(),
        "slug": slug,
        "category": "space",
        "jurisdiction": "india_nbc",
        "subcategory": "furniture_ergonomics",
        "display_name": display_name,
        "notes": notes,
        "data": _serialise({"item_group": item_group, **data}),
        "source_section": "BRD §1C — Furniture ergonomics + Neufert",
        "source_doc": "BRD-Phase-1",
        "source": source_tag,
    }


def _serialise(value: Any) -> Any:
    """Coerce tuples → lists for JSON-friendly storage."""
    if isinstance(value, tuple):
        return [_serialise(v) for v in value]
    if isinstance(value, list):
        return [_serialise(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialise(v) for k, v in value.items()}
    return value


def _table_rows(
    table: dict[str, dict[str, Any]],
    *,
    item_group: str,
    slug_prefix: str,
    source_tag: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item, spec in table.items():
        rows.append(
            _row(
                f"{slug_prefix}_{item}",
                display_name=f"Ergonomics — {item.replace('_', ' ').title()}",
                data={"item": item, **dict(spec)},
                item_group=item_group,
                notes=spec.get("notes") if isinstance(spec, dict) else None,
                source_tag=source_tag,
            )
        )
    return rows


def _bed_under_storage_row() -> dict[str, Any]:
    low, high = ergo_kb.BED_UNDER_STORAGE_MM
    return _row(
        "ergonomics_bed_under_storage",
        display_name="Ergonomics — Under-bed storage clearance",
        data={"under_storage_height_mm": [int(low), int(high)]},
        item_group="bed",
        notes="BRD: 30–40 cm minimum.",
        source_tag="seed:ergonomics.BED_UNDER_STORAGE_MM",
    )


# ─────────────────────────────────────────────────────────────────────
# Public — single entry point
# ─────────────────────────────────────────────────────────────────────


def build_ergonomics_seed_rows() -> list[dict[str, Any]]:
    """Every furniture-ergonomics row, ready for ``op.bulk_insert``."""
    return [
        *_table_rows(
            ergo_kb.CHAIRS,
            item_group="chair",
            slug_prefix="ergonomics_chair",
            source_tag="seed:ergonomics.CHAIRS",
        ),
        *_table_rows(
            ergo_kb.TABLES,
            item_group="table",
            slug_prefix="ergonomics_table",
            source_tag="seed:ergonomics.TABLES",
        ),
        *_table_rows(
            ergo_kb.BEDS,
            item_group="bed",
            slug_prefix="ergonomics_bed",
            source_tag="seed:ergonomics.BEDS",
        ),
        _bed_under_storage_row(),
        *_table_rows(
            ergo_kb.STORAGE,
            item_group="storage",
            slug_prefix="ergonomics_storage",
            source_tag="seed:ergonomics.STORAGE",
        ),
    ]
