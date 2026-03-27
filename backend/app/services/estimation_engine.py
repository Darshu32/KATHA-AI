"""Estimation Engine — computes quantities and cost ranges from design graph geometry."""

import logging
import math

logger = logging.getLogger(__name__)


# ── Material unit rates (INR per unit) — configurable defaults ───────────────

DEFAULT_RATES: dict[str, dict] = {
    "paint": {"unit": "sqft", "low": 12, "high": 25},
    "wallpaper": {"unit": "sqft", "low": 30, "high": 80},
    "tile_ceramic": {"unit": "sqft", "low": 45, "high": 120},
    "tile_marble": {"unit": "sqft", "low": 120, "high": 350},
    "hardwood": {"unit": "sqft", "low": 150, "high": 400},
    "laminate": {"unit": "sqft", "low": 60, "high": 150},
    "carpet": {"unit": "sqft", "low": 40, "high": 120},
    "concrete": {"unit": "sqft", "low": 20, "high": 50},
    "brick": {"unit": "sqft", "low": 35, "high": 80},
    "glass": {"unit": "sqft", "low": 100, "high": 300},
    "fabric": {"unit": "sqft", "low": 50, "high": 200},
    "wood_panel": {"unit": "sqft", "low": 80, "high": 250},
    "stone_natural": {"unit": "sqft", "low": 150, "high": 500},
    "plaster": {"unit": "sqft", "low": 15, "high": 35},
    "metal": {"unit": "sqft", "low": 200, "high": 600},
    "default": {"unit": "sqft", "low": 30, "high": 100},
}

# Common fixture costs
FIXTURE_RATES: dict[str, dict] = {
    "door": {"low": 5000, "high": 25000},
    "window": {"low": 4000, "high": 20000},
    "light_fixture": {"low": 1500, "high": 15000},
    "fan": {"low": 2000, "high": 8000},
    "switch_board": {"low": 200, "high": 800},
    "outlet": {"low": 150, "high": 500},
    "default": {"low": 1000, "high": 10000},
}


def process(layout: dict) -> dict:
    """
    Pipeline-facing estimation entry point. The orchestrator depends on this stable
    interface so the underlying estimation logic can evolve independently.
    """
    logger.info("Estimation engine: computing estimate from layout")
    return compute_estimate(layout)


def compute_estimate(graph_data: dict) -> dict:
    """
    Read the design graph and produce a full estimate breakdown.

    Returns a dict with:
      - line_items: list of categorized quantity + cost entries
      - total_low / total_high
      - assumptions
    """
    line_items: list[dict] = []
    assumptions: list[str] = []

    spaces = graph_data.get("spaces", [])
    objects = graph_data.get("objects", [])
    materials = graph_data.get("materials", [])

    # Build material lookup
    material_map = {m.get("id", ""): m for m in materials}

    for space in spaces:
        dims = space.get("dimensions", {})
        length = dims.get("length", 0)
        width = dims.get("width", 0)
        height = dims.get("height", 0)
        space_name = space.get("name", "Room")

        if not (length and width and height):
            assumptions.append(f"Dimensions missing for {space_name}, using defaults 12x15x10 ft")
            length, width, height = 12, 15, 10

        # ── Floor area ───────────────────────────────────────
        floor_area = length * width
        line_items.append(
            _make_line_item(
                category="floor",
                item_name=f"{space_name} — Floor finish",
                material=_guess_floor_material(graph_data),
                quantity=floor_area,
                unit="sqft",
            )
        )

        # ── Ceiling area ─────────────────────────────────────
        ceiling_area = floor_area
        line_items.append(
            _make_line_item(
                category="ceiling",
                item_name=f"{space_name} — Ceiling finish",
                material="paint",
                quantity=ceiling_area,
                unit="sqft",
            )
        )

        # ── Wall area (perimeter × height minus openings) ────
        perimeter = 2 * (length + width)
        gross_wall_area = perimeter * height
        opening_area = _estimate_opening_area(objects)
        net_wall_area = max(gross_wall_area - opening_area, 0)

        line_items.append(
            _make_line_item(
                category="wall",
                item_name=f"{space_name} — Wall finish",
                material=_guess_wall_material(graph_data),
                quantity=net_wall_area,
                unit="sqft",
            )
        )

        assumptions.append(
            f"{space_name}: {length}×{width}×{height} ft, "
            f"wall area {net_wall_area:.0f} sqft (minus ~{opening_area:.0f} sqft openings)"
        )

    # ── Fixtures and furniture ────────────────────────────────
    for obj in objects:
        obj_type = obj.get("type", "").lower()
        if obj_type in ("wall", "floor", "ceiling"):
            continue

        if obj_type in ("door", "window", "light_fixture", "fan", "switch_board", "outlet"):
            rates = FIXTURE_RATES.get(obj_type, FIXTURE_RATES["default"])
            line_items.append({
                "category": "fixture",
                "item_name": obj.get("name", obj_type),
                "material": obj.get("material", ""),
                "quantity": 1,
                "unit": "nos",
                "unit_rate_low": rates["low"],
                "unit_rate_high": rates["high"],
                "total_low": rates["low"],
                "total_high": rates["high"],
            })
        elif obj_type in ("sofa", "table", "chair", "bed", "desk", "shelf",
                          "bookshelf", "cabinet", "wardrobe", "dining_table",
                          "coffee_table", "tv_unit", "rug"):
            # Furniture — estimate from dimensions if available
            dims = obj.get("dimensions", {})
            obj_area = dims.get("length", 3) * dims.get("width", 3)
            mat = obj.get("material", "wood_panel")
            line_items.append(
                _make_line_item(
                    category="furniture",
                    item_name=obj.get("name", obj_type),
                    material=mat,
                    quantity=obj_area,
                    unit="sqft",
                )
            )

    # ── Totals ────────────────────────────────────────────────
    total_low = sum(item["total_low"] for item in line_items)
    total_high = sum(item["total_high"] for item in line_items)

    return {
        "status": "computed",
        "line_items": line_items,
        "total_low": round(total_low, 2),
        "total_high": round(total_high, 2),
        "currency": "INR",
        "assumptions": assumptions,
    }


def _make_line_item(
    category: str,
    item_name: str,
    material: str,
    quantity: float,
    unit: str,
) -> dict:
    mat_key = _normalize_material(material)
    rates = DEFAULT_RATES.get(mat_key, DEFAULT_RATES["default"])
    return {
        "category": category,
        "item_name": item_name,
        "material": material,
        "quantity": round(quantity, 2),
        "unit": unit,
        "unit_rate_low": rates["low"],
        "unit_rate_high": rates["high"],
        "total_low": round(quantity * rates["low"], 2),
        "total_high": round(quantity * rates["high"], 2),
    }


def _normalize_material(material: str) -> str:
    material = material.lower().strip()
    for key in DEFAULT_RATES:
        if key in material:
            return key
    if "wood" in material or "timber" in material:
        return "hardwood"
    if "marble" in material:
        return "tile_marble"
    if "tile" in material or "ceramic" in material:
        return "tile_ceramic"
    if "stone" in material:
        return "stone_natural"
    if "carpet" in material:
        return "carpet"
    if "paint" in material:
        return "paint"
    return "default"


def _guess_floor_material(graph_data: dict) -> str:
    for mat in graph_data.get("materials", []):
        cat = mat.get("category", "").lower()
        if "floor" in cat or "tile" in cat or "wood" in cat:
            return mat.get("name", "tile_ceramic")
    return "tile_ceramic"


def _guess_wall_material(graph_data: dict) -> str:
    for mat in graph_data.get("materials", []):
        cat = mat.get("category", "").lower()
        if "wall" in cat or "paint" in cat or "plaster" in cat:
            return mat.get("name", "paint")
    return "paint"


def _estimate_opening_area(objects: list[dict]) -> float:
    """Sum up door/window areas from object dimensions."""
    area = 0.0
    for obj in objects:
        obj_type = obj.get("type", "").lower()
        if obj_type in ("door", "window"):
            dims = obj.get("dimensions", {})
            w = dims.get("width", 3)
            h = dims.get("height", 7 if obj_type == "door" else 4)
            area += w * h
    return area
