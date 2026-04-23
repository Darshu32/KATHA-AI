"""Recommendations engine — BRD Layer 6 "proactive suggestions".

Produces forward-looking, actionable tips on top of the pure validator.
The validator says "this is wrong"; the recommendations engine says
"here's what you could do better, and why."

Output shape:
    [
        {
            "id": "rec_...",
            "category": "materials" | "cost" | "lead_time" | "theme" | "volume" | "sustainability",
            "severity": "info" | "tip" | "nudge",
            "title": str,
            "message": str,
            "evidence": { ... },   # numbers backing the tip
        },
        ...
    ]
"""

from __future__ import annotations

import logging

from app.knowledge import manufacturing, materials as materials_kb, themes

logger = logging.getLogger(__name__)


def recommend(data: dict) -> list[dict]:
    """Run all recommenders on a design graph and return merged list."""
    recs: list[dict] = []

    style = (data.get("style") or {}).get("primary") or ""
    pack = themes.get(style)

    _recommend_theme_materials(data, pack, recs)
    _recommend_material_cost(data, recs)
    _recommend_lead_times(data, recs)
    _recommend_volume_pricing(data, recs)
    _recommend_sustainability(data, pack, recs)

    logger.info("recommendations_built", extra={"count": len(recs), "style": style})
    return recs


# ── Theme-aware material tips ────────────────────────────────────────────────

def _recommend_theme_materials(data: dict, pack: dict | None, recs: list[dict]) -> None:
    if not pack:
        return
    primaries = pack.get("material_palette", {}).get("primary", [])
    if not primaries:
        return
    theme_name = pack["display_name"]
    seen = {(m.get("name") or "").lower() for m in data.get("materials", [])}
    first_choice = primaries[0]
    if not any(first_choice.lower() in s for s in seen):
        recs.append({
            "id": f"rec_theme_material_{first_choice}",
            "category": "theme",
            "severity": "tip",
            "title": f"For {theme_name}, typically use {first_choice}",
            "message": (
                f"The {theme_name} theme reads strongest with {first_choice} as the primary material. "
                f"Alternatives in palette: {', '.join(primaries[1:] or ['none'])}."
            ),
            "evidence": {"theme": theme_name, "primary_palette": primaries},
        })


# ── Cost advisories ─────────────────────────────────────────────────────────

def _recommend_material_cost(data: dict, recs: list[dict]) -> None:
    """Flag premium materials and suggest cheaper look-alikes."""
    alternatives = {
        "walnut": ["rubberwood with walnut stain", "oak with dark stain"],
        "teak": ["rubberwood with teak finish", "oak"],
        "brass": ["brushed stainless with antique finish", "powder-coated steel"],
        "marble": ["engineered quartz", "porcelain slab"],
        "travertine": ["porcelain travertine-look tile"],
    }
    seen = set()
    for mat in data.get("materials", []):
        name = (mat.get("name") or "").lower()
        for premium, alts in alternatives.items():
            if premium in name and premium not in seen:
                seen.add(premium)
                wood = materials_kb.wood_summary(premium) or {}
                cost_range = wood.get("cost_inr_kg")
                recs.append({
                    "id": f"rec_cost_alt_{premium}",
                    "category": "cost",
                    "severity": "nudge",
                    "title": f"'{premium.title()}' is a premium material",
                    "message": (
                        f"If the budget tightens, consider: {', '.join(alts)}. "
                        + (f"Current cost band: INR {cost_range[0]}-{cost_range[1]}/kg." if cost_range else "")
                    ),
                    "evidence": {"premium": premium, "alternatives": alts, "cost_inr_kg": cost_range},
                })


# ── Lead-time advisories ────────────────────────────────────────────────────

def _recommend_lead_times(data: dict, recs: list[dict]) -> None:
    """Summarise longest lead-time driver so procurement plans for it."""
    drivers: list[tuple[str, tuple[int, int]]] = []
    for obj in data.get("objects", []):
        mat = (obj.get("material") or "").lower()
        if any(s in mat for s in ("walnut", "oak", "teak", "rosewood")):
            lt = manufacturing.lead_time_for("woodworking_furniture")
            if lt:
                drivers.append((obj.get("type") or "wood item", lt))
        elif any(s in mat for s in ("steel", "iron", "brass", "aluminium", "aluminum")):
            lt = manufacturing.lead_time_for("metal_fabrication")
            if lt:
                drivers.append((obj.get("type") or "metal item", lt))

    if not drivers:
        return
    longest_item, longest_range = max(drivers, key=lambda x: x[1][1])
    recs.append({
        "id": "rec_lead_time_longest",
        "category": "lead_time",
        "severity": "info",
        "title": f"Longest lead: {longest_item}",
        "message": (
            f"Critical-path item is '{longest_item}' at ~{longest_range[0]}-{longest_range[1]} weeks. "
            "Order this first to avoid blocking assembly."
        ),
        "evidence": {"item": longest_item, "weeks": list(longest_range)},
    })


# ── Volume pricing nudges ───────────────────────────────────────────────────

def _recommend_volume_pricing(data: dict, recs: list[dict]) -> None:
    # Count repeated / parametric pieces worth batching.
    type_counts: dict[str, int] = {}
    for obj in data.get("objects", []):
        t = (obj.get("type") or "").lower()
        type_counts[t] = type_counts.get(t, 0) + 1
    repeaters = [(t, c) for t, c in type_counts.items() if c >= 2]
    if not repeaters:
        return
    item, count = max(repeaters, key=lambda x: x[1])
    recs.append({
        "id": f"rec_volume_{item}",
        "category": "volume",
        "severity": "tip",
        "title": f"Batch '{item}' at quantity {count}+",
        "message": (
            f"You already use {count} x {item}. Unit price typically drops 10-20% "
            "at >=5 pieces from the same fabricator. Confirm batch pricing."
        ),
        "evidence": {"item": item, "count": count},
    })


# ── Sustainability / regional hint ──────────────────────────────────────────

def _recommend_sustainability(data: dict, pack: dict | None, recs: list[dict]) -> None:
    site = (data.get("site") or {})
    location = (site.get("location") or "").lower()
    seen_woods = {
        (m.get("name") or "").lower()
        for m in data.get("materials", [])
        if any(w in (m.get("name") or "").lower() for w in ("walnut", "oak", "rosewood"))
    }
    if seen_woods and location and "india" in location:
        recs.append({
            "id": "rec_regional_wood",
            "category": "sustainability",
            "severity": "tip",
            "title": "Consider locally sourced teak or rubberwood",
            "message": (
                "Project located in India — teak and rubberwood carry shorter supply chains "
                "and lower embodied carbon than imported walnut / rosewood. "
                "Rubberwood also takes stain well if walnut look is desired."
            ),
            "evidence": {"imported_seen": sorted(seen_woods)},
        })
