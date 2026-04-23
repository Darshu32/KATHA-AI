"""Produce a compact knowledge brief for injection into the LLM system prompt.

Called by ai_orchestrator before chat.completions.create() — keeps the
critical hard rules in front of the model for every generation.
"""

from __future__ import annotations

from app.knowledge import (
    clearances,
    codes,
    ergonomics,
    manufacturing,
    materials,
    space_standards,
    themes,
)


def build_knowledge_brief(
    *,
    room_type: str,
    theme: str,
    segment: str = "residential",
    max_chars: int = 2200,
) -> str:
    """Return a text block summarising the knowledge rules relevant to this
    design request. Kept bounded so we don't blow the context budget.
    """
    parts: list[str] = []

    # Space standard for this room.
    table = {"residential": space_standards.RESIDENTIAL, "commercial": space_standards.COMMERCIAL, "hospitality": space_standards.HOSPITALITY}.get(segment, {})
    room_spec = table.get(room_type)
    if room_spec:
        parts.append(
            f"[Space standard — {segment}/{room_type}] "
            f"min area {room_spec.get('min_area_m2','?')}m^2, "
            f"typical {room_spec.get('typical_area_m2','?')}m^2, "
            f"min short side {room_spec.get('min_short_side_m','?')}m, "
            f"min height {room_spec.get('min_height_m','?')}m. "
            f"{room_spec.get('notes','')}"
        )

    # Core clearances.
    parts.append(
        "[Clearances mm] "
        f"main door {clearances.DOORS['main_entry']['width_mm']}, "
        f"interior door {clearances.DOORS['interior']['width_mm']}, "
        f"residential corridor min {clearances.CORRIDORS['residential']['min_width_mm']}, "
        f"commercial corridor min {clearances.CORRIDORS['commercial']['min_width_mm']}, "
        f"stair rise {clearances.STAIRS['residential']['rise_mm']} tread {clearances.STAIRS['residential']['tread_mm']}, "
        f"around bed {clearances.CIRCULATION['around_bed']}, around dining {clearances.CIRCULATION['around_dining_table']}."
    )

    # Ergonomics — pick the most likely items for this room.
    room_ergo = {
        "bedroom": ["bed", "wardrobe"],
        "living_room": ["lounge_chair", "coffee_table"],
        "dining_room": ["dining_chair", "dining_table"],
        "kitchen": ["kitchen_cabinet_base", "counter"],
        "study": ["office_chair", "desk"],
        "office": ["office_chair", "desk"],
    }.get(room_type, [])
    if room_ergo:
        ergo_lines = []
        for item in room_ergo:
            for cat, table_ in [("CHAIRS", ergonomics.CHAIRS), ("TABLES", ergonomics.TABLES), ("BEDS", ergonomics.BEDS), ("STORAGE", ergonomics.STORAGE)]:
                if item in table_:
                    spec = table_[item]
                    keys = list(spec.keys())[:4]
                    summary = ", ".join(f"{k}={spec[k]}" for k in keys)
                    ergo_lines.append(f"{item}: {summary}")
                    break
        if ergo_lines:
            parts.append("[Ergonomic ranges mm] " + " | ".join(ergo_lines))

    # Theme rules.
    theme_block = themes.describe_for_prompt(theme)
    parts.append("[Theme parametric rules]\n" + theme_block)

    # NBC minima.
    nbc = codes.NBC_INDIA["minimum_room_dimensions"]
    parts.append(
        f"[NBC India] habitable min {nbc['habitable_room_min_area_m2']}m^2 / "
        f"{nbc['habitable_room_min_short_side_m']}m short side / "
        f"{nbc['habitable_room_min_height_m']}m height. "
        f"Kitchen >= {nbc['kitchen_min_area_m2']}m^2. "
        f"Bathroom >= {nbc['bathroom_min_area_m2']}m^2."
    )

    # Manufacturing tolerances (short).
    parts.append(
        f"[Tolerances] structural +/-{manufacturing.TOLERANCES['structural']['+-mm']}mm, "
        f"cosmetic +/-{manufacturing.TOLERANCES['cosmetic']['+-mm']}mm, "
        f"material +/-{manufacturing.TOLERANCES['material_thickness']['+-mm']}mm, "
        f"hardware +/-{manufacturing.TOLERANCES['hardware_placement']['+-mm']}mm."
    )

    # Material hint for primary theme wood if any.
    pack = themes.get(theme)
    if pack:
        primaries = pack.get("material_palette", {}).get("primary", [])
        if primaries:
            first = primaries[0].replace(" ", "_").lower()
            wood = materials.wood_summary(first)
            if wood:
                parts.append(
                    f"[Material — {primaries[0]}] density {wood['density_kg_m3']}kg/m^3, "
                    f"MOR {wood['mor_mpa']}MPa, cost INR {wood['cost_inr_kg']}/kg, "
                    f"lead {wood['lead_time_weeks']}w. {wood.get('aesthetic','')}"
                )

    brief = "\n".join(parts)
    if len(brief) > max_chars:
        brief = brief[: max_chars - 20] + "\n...[truncated]"
    return brief
