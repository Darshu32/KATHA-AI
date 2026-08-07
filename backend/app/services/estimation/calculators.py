"""Category-specific cost calculators."""

from __future__ import annotations

from decimal import Decimal

from app.services.estimation.catalog import (
    CONSTRUCTION_RATE_PER_SQFT,
    FIXTURE_RATES,
    FURNITURE_RATES,
    FURNITURE_TYPES,
    LABOR_RATES,
    MATERIAL_RATES,
    MISC_RATES,
    PRODUCT_RATE_ALIASES,
    SERVICE_RATES,
)
from app.services.estimation.models import EstimateItem, round_money, to_decimal


# Graph dimensions are authored in METRES (the spatial kernel + normalize_graph
# enforce this), but the estimation rates are ₹/sqft and the defaults below are
# in FEET. Convert metric dims → feet at every read so areas are TRUE square feet
# (a room is not 16 sqft because it's 4×4 m — it's ~172 sqft).
FEET_PER_M = Decimal("3.280839895")
SQFT_PER_SQM = Decimal("10.763910417")


def _ft(value, default_ft: str) -> Decimal:
    """A present metric dimension → feet; the (feet) default when absent/zero."""
    if not value:
        return to_decimal(default_ft)
    return to_decimal(value) * FEET_PER_M


def calculate_area_summary(graph_data: dict) -> dict:
    total_sqft = Decimal("0")
    space_breakdown: list[dict] = []

    for index, space in enumerate(graph_data.get("spaces") or [], start=1):
        dims = space.get("dimensions", {})
        length = _ft(dims.get("length"), "12")
        width = _ft(dims.get("width"), "15")
        floor_area = round_money(length * width)
        total_sqft += floor_area
        space_breakdown.append(
            {
                "space_id": space.get("id", f"space_{index}"),
                "space_name": space.get("name", f"Space {index}"),
                "sqft": float(floor_area),
            }
        )

    # Fallback: a rooms PROGRAM (area_sqm per room) that was never solved into
    # placed spaces — still cost it on the programmed floor area (m² → sqft).
    if not space_breakdown:
        for index, room in enumerate(graph_data.get("rooms") or [], start=1):
            area_m2 = to_decimal(room.get("area_sqm"))
            if area_m2 <= 0:
                continue
            floor_area = round_money(area_m2 * SQFT_PER_SQM)
            total_sqft += floor_area
            space_breakdown.append(
                {
                    "space_id": room.get("id", f"room_{index}"),
                    "space_name": room.get("type", f"Room {index}"),
                    "sqft": float(floor_area),
                }
            )

    # Exterior/architecture: no interior rooms, but there IS a built-up area —
    # each massing volume contributes footprint × storeys (height ÷ ~3 m/floor).
    # This is the area the shell + labour + services are costed on.
    if not space_breakdown and str(graph_data.get("design_type")) == "architecture":
        for index, obj in enumerate(graph_data.get("objects") or [], start=1):
            if str(obj.get("role")) != "massing":
                continue
            dims = obj.get("dimensions") or {}
            length_ft = _ft(dims.get("length") or dims.get("width") or dims.get("x"), "40")
            width_ft = _ft(dims.get("depth") or dims.get("width") or dims.get("y"), "30")
            height_m = to_decimal(dims.get("height") or dims.get("z"))
            floors = max(int(height_m / Decimal("3")), 1) if height_m >= Decimal("3") else 1
            built = round_money(length_ft * width_ft * Decimal(floors))
            if built <= 0:
                continue
            total_sqft += built
            space_breakdown.append(
                {
                    "space_id": obj.get("id", f"mass_{index}"),
                    "space_name": obj.get("name", f"Massing {index}"),
                    "sqft": float(built),
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
        length = _ft(dims.get("length"), "12")
        width = _ft(dims.get("width"), "15")
        height = _ft(dims.get("height"), "10")
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


def calculate_structure_items(graph_data: dict, area_summary: dict) -> list[EstimateItem]:
    """Exterior/architecture shell — RCC structure + envelope, costed on the
    built-up area (computed in :func:`calculate_area_summary`). Interior projects
    return nothing here (their cost comes from per-room surfaces)."""
    if str(graph_data.get("design_type")) != "architecture":
        return []
    built = to_decimal(area_summary.get("total_sqft"))
    if built <= 0:
        return []
    return [
        EstimateItem(
            item="Structure & building shell (built-up area)",
            category="materials",
            subcategory="construction",
            quantity=round_money(built),
            unit="sqft",
            base_unit_cost=CONSTRUCTION_RATE_PER_SQFT,
            material="rcc_structure",
            source="massing",
        )
    ]


def calculate_product_items(graph_data: dict) -> list[EstimateItem]:
    """Furniture/product — priced per-unit off the rate card (a product has no
    floor area). The product's type comes from the ``product_meta`` constraint;
    its parts are geometry, not separate line items."""
    if str(graph_data.get("design_type")) != "product":
        return []
    ptype = _product_type(graph_data)
    return [
        EstimateItem(
            item=(ptype.replace("_", " ").title() or "Product"),
            category="furniture",
            subcategory="product",
            quantity=Decimal("1"),
            unit="item",
            base_unit_cost=_product_base_rate(ptype),
            material="mixed",
            quality="standard",
            source="product",
        )
    ]


def _product_type(graph_data: dict) -> str:
    for constraint in graph_data.get("constraints") or []:
        if str(constraint.get("type")) == "product_meta":
            return str(constraint.get("value") or "product").lower().strip()
    return "product"


def _product_base_rate(ptype: str) -> Decimal:
    """Free-text product type → a rate-card price. Exact key, then exact alias,
    then substring on aliases (so 'lounge armchair' → 'armchair' → sofa tier
    BEFORE the bare 'chair' substring), then substring on furniture keys."""
    t = (ptype or "").lower().strip()
    if t in FURNITURE_RATES:
        return FURNITURE_RATES[t]
    if t in PRODUCT_RATE_ALIASES:
        return FURNITURE_RATES[PRODUCT_RATE_ALIASES[t]]
    for alias, key in PRODUCT_RATE_ALIASES.items():
        if alias in t:
            return FURNITURE_RATES[key]
    for key in FURNITURE_TYPES:
        if key in t:
            return FURNITURE_RATES[key]
    return FURNITURE_RATES["default"]


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
        width = _ft(dims.get("width"), "3")
        height = _ft(dims.get("height"), "7" if obj_type == "door" else "4")
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
