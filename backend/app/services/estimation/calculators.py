"""Category-specific cost calculators."""

from __future__ import annotations

from decimal import Decimal

from app.services.estimation.catalog import (
    FIXTURE_RATES,
    FURNITURE_RATES,
    FURNITURE_TYPES,
    LABOR_RATES,
    MATERIAL_RATES,
    MISC_RATES,
    SERVICE_RATES,
)
from app.services.estimation.models import EstimateItem, round_money, to_decimal


def calculate_area_summary(graph_data: dict) -> dict:
    total_sqft = Decimal("0")
    space_breakdown: list[dict] = []

    for index, space in enumerate(graph_data.get("spaces", []), start=1):
        dims = space.get("dimensions", {})
        length = to_decimal(dims.get("length"), "12")
        width = to_decimal(dims.get("width"), "15")
        floor_area = round_money(length * width)
        total_sqft += floor_area
        space_breakdown.append(
            {
                "space_id": space.get("id", f"space_{index}"),
                "space_name": space.get("name", f"Space {index}"),
                "sqft": float(floor_area),
            }
        )

    return {
        "total_sqft": float(round_money(total_sqft)),
        "space_breakdown": space_breakdown,
    }


def calculate_material_items(graph_data: dict) -> tuple[list[EstimateItem], list[str]]:
    items: list[EstimateItem] = []
    assumptions: list[str] = []
    objects = graph_data.get("objects", [])

    for space in graph_data.get("spaces", []):
        dims = space.get("dimensions", {})
        length = to_decimal(dims.get("length"), "12")
        width = to_decimal(dims.get("width"), "15")
        height = to_decimal(dims.get("height"), "10")
        space_name = space.get("name", "Room")

        if not dims.get("length") or not dims.get("width") or not dims.get("height"):
            assumptions.append(
                f"{space_name}: missing dimensions, defaulted to 12x15x10 ft for quantity estimation."
            )

        floor_area = round_money(length * width)
        ceiling_area = floor_area
        perimeter = (length + width) * Decimal("2")
        opening_area = round_money(_estimate_opening_area(objects))
        wall_area = round_money(max((perimeter * height) - opening_area, Decimal("0")))

        floor_material = _guess_floor_material(graph_data)
        wall_material = _guess_wall_material(graph_data)

        items.extend(
            [
                EstimateItem(
                    item=f"{space_name} floor finish",
                    category="materials",
                    subcategory="floor",
                    quantity=floor_area,
                    unit="sqft",
                    base_unit_cost=MATERIAL_RATES.get(floor_material, MATERIAL_RATES["default"]),
                    material=floor_material,
                ),
                EstimateItem(
                    item=f"{space_name} ceiling finish",
                    category="materials",
                    subcategory="ceiling",
                    quantity=ceiling_area,
                    unit="sqft",
                    base_unit_cost=MATERIAL_RATES["paint"],
                    material="paint",
                ),
                EstimateItem(
                    item=f"{space_name} wall finish",
                    category="materials",
                    subcategory="wall",
                    quantity=wall_area,
                    unit="sqft",
                    base_unit_cost=MATERIAL_RATES.get(wall_material, MATERIAL_RATES["default"]),
                    material=wall_material,
                ),
            ]
        )

        assumptions.append(
            f"{space_name}: estimated {float(wall_area):.0f} sqft wall finish after deducting openings."
        )

    for obj in objects:
        obj_type = str(obj.get("type", "")).lower()
        if obj_type in FIXTURE_RATES:
            items.append(
                EstimateItem(
                    item=obj.get("name", obj_type.replace("_", " ")),
                    category="materials",
                    subcategory="fixture",
                    quantity=Decimal("1"),
                    unit="item",
                    base_unit_cost=FIXTURE_RATES[obj_type],
                    material=obj.get("material", obj_type),
                    quality=_resolve_quality(obj),
                    source="object",
                )
            )

    return items, assumptions


def calculate_furniture_items(graph_data: dict) -> list[EstimateItem]:
    items: list[EstimateItem] = []

    for obj in graph_data.get("objects", []):
        obj_type = str(obj.get("type", "")).lower()
        if obj_type not in FURNITURE_TYPES:
            continue

        quantity = _resolve_quantity(obj)
        base_rate = FURNITURE_RATES.get(obj_type, FURNITURE_RATES["default"])

        items.append(
            EstimateItem(
                item=obj.get("name", obj_type.replace("_", " ")),
                category="furniture",
                subcategory="furniture",
                quantity=quantity,
                unit="item",
                base_unit_cost=base_rate,
                material=obj.get("material", "mixed"),
                quality=_resolve_quality(obj),
                source="object",
            )
        )

    return items


def calculate_labor_items(area_summary: dict, priced_goods_total: Decimal, style_tier: str) -> list[EstimateItem]:
    total_sqft = to_decimal(area_summary.get("total_sqft"))
    install_quantity = total_sqft or Decimal("1")
    carpentry_quantity = max(total_sqft * Decimal("0.35"), Decimal("1"))

    return [
        EstimateItem(
            item="Finishing labor",
            category="labor",
            subcategory="labor",
            quantity=install_quantity,
            unit="sqft",
            base_unit_cost=LABOR_RATES["finishing_labor"],
            style_tier=style_tier,
        ),
        EstimateItem(
            item="Installation labor",
            category="labor",
            subcategory="labor",
            quantity=install_quantity,
            unit="sqft",
            base_unit_cost=LABOR_RATES["installation_labor"],
            style_tier=style_tier,
        ),
        EstimateItem(
            item="Carpentry labor",
            category="labor",
            subcategory="labor",
            quantity=round_money(carpentry_quantity),
            unit="sqft",
            base_unit_cost=LABOR_RATES["carpentry_labor"],
            style_tier=style_tier,
            metadata={"goods_reference_total": float(round_money(priced_goods_total))},
        ),
    ]


def calculate_service_items(area_summary: dict, style_tier: str) -> list[EstimateItem]:
    total_sqft = to_decimal(area_summary.get("total_sqft"))
    service_quantity = total_sqft or Decimal("1")
    return [
        EstimateItem(
            item="Design consultation",
            category="services",
            subcategory="service",
            quantity=service_quantity,
            unit="sqft",
            base_unit_cost=SERVICE_RATES["design_consultation"],
            style_tier=style_tier,
        ),
        EstimateItem(
            item="Site supervision",
            category="services",
            subcategory="service",
            quantity=service_quantity,
            unit="sqft",
            base_unit_cost=SERVICE_RATES["site_supervision"],
            style_tier=style_tier,
        ),
        EstimateItem(
            item="Project management",
            category="services",
            subcategory="service",
            quantity=service_quantity,
            unit="sqft",
            base_unit_cost=SERVICE_RATES["project_management"],
            style_tier=style_tier,
        ),
    ]


def calculate_misc_items(subtotal_before_misc: Decimal, style_tier: str) -> list[EstimateItem]:
    reference_total = round_money(subtotal_before_misc)
    return [
        EstimateItem(
            item="Logistics",
            category="misc",
            subcategory="misc",
            quantity=Decimal("1"),
            unit="lot",
            base_unit_cost=round_money(reference_total * MISC_RATES["logistics"]),
            style_tier=style_tier,
        ),
        EstimateItem(
            item="Contingency",
            category="misc",
            subcategory="misc",
            quantity=Decimal("1"),
            unit="lot",
            base_unit_cost=round_money(reference_total * MISC_RATES["contingency"]),
            style_tier=style_tier,
        ),
    ]


def _guess_floor_material(graph_data: dict) -> str:
    for mat in graph_data.get("materials", []):
        category = str(mat.get("category", "")).lower()
        name = str(mat.get("name", "")).lower()
        if any(token in f"{category} {name}" for token in ("floor", "tile", "wood", "marble", "laminate")):
            return _normalize_material(name or category)
    return "tile_ceramic"


def _guess_wall_material(graph_data: dict) -> str:
    for mat in graph_data.get("materials", []):
        category = str(mat.get("category", "")).lower()
        name = str(mat.get("name", "")).lower()
        if any(token in f"{category} {name}" for token in ("wall", "paint", "plaster", "wallpaper")):
            return _normalize_material(name or category)
    return "paint"


def _normalize_material(material: str) -> str:
    normalized = material.lower().strip()
    for key in MATERIAL_RATES:
        if key != "default" and key in normalized:
            return key
    if "wood" in normalized or "timber" in normalized:
        return "hardwood"
    if "marble" in normalized:
        return "tile_marble"
    if "tile" in normalized or "ceramic" in normalized:
        return "tile_ceramic"
    if "stone" in normalized:
        return "stone_natural"
    if "carpet" in normalized:
        return "carpet"
    if "paint" in normalized:
        return "paint"
    return "default"


def _estimate_opening_area(objects: list[dict]) -> Decimal:
    area = Decimal("0")
    for obj in objects:
        obj_type = str(obj.get("type", "")).lower()
        if obj_type not in {"door", "window"}:
            continue
        dims = obj.get("dimensions", {})
        width = to_decimal(dims.get("width"), "3")
        height = to_decimal(dims.get("height"), "7" if obj_type == "door" else "4")
        area += width * height
    return area


def _resolve_quantity(obj: dict) -> Decimal:
    metadata = obj.get("metadata", {})
    if metadata.get("quantity") not in (None, ""):
        return max(to_decimal(metadata.get("quantity")), Decimal("1"))
    return Decimal("1")


def _resolve_quality(obj: dict) -> str:
    metadata = obj.get("metadata", {})
    quality = str(metadata.get("quality", obj.get("quality", "standard"))).strip().lower()
    return quality or "standard"
