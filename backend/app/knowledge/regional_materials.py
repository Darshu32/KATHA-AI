"""Regional material availability, sourcing, and cost adjustment.

Keeps the core material specs in `materials.py` universal; this module
layers regional availability, typical lead-time adders, and a price
index so cost/estimation stages can adapt dynamically.
"""

from __future__ import annotations

# ── Price index by city (baseline = 1.0 for Delhi NCR) ───────────────────────
# Used to scale catalog unit rates so regional cost reflects real market.
CITY_PRICE_INDEX: dict[str, float] = {
    "delhi": 1.00,
    "new_delhi": 1.00,
    "gurgaon": 1.05,
    "noida": 1.00,
    "mumbai": 1.18,
    "pune": 1.05,
    "bengaluru": 1.10,
    "bangalore": 1.10,
    "hyderabad": 1.02,
    "chennai": 1.04,
    "kolkata": 0.96,
    "ahmedabad": 0.95,
    "jaipur": 0.92,
    "lucknow": 0.90,
    "goa": 1.12,
    "kochi": 1.02,
    "chandigarh": 0.98,
    "shimla": 1.18,
    "srinagar": 1.22,
    "leh": 1.40,
    "guwahati": 1.08,
}

# ── Material → cities where it is readily available ─────────────────────────
# "readily" = local supplier network, normal lead time; everything else
# ships from hubs and gets a lead-time adder applied by helper below.
MATERIAL_AVAILABILITY: dict[str, list[str]] = {
    # Woods
    "teak": ["mumbai", "pune", "goa", "chennai", "kochi", "bengaluru", "hyderabad"],
    "walnut": ["delhi", "gurgaon", "chandigarh", "srinagar", "mumbai", "bengaluru"],
    "oak": ["delhi", "mumbai", "bengaluru", "hyderabad", "chennai"],
    "rubberwood": ["chennai", "kochi", "bengaluru", "hyderabad"],
    "plywood_marine": ["*"],  # everywhere
    "mdf": ["*"],
    "bamboo": ["guwahati", "kolkata", "kochi", "bengaluru"],

    # Stone
    "kota_stone": ["jaipur", "delhi", "ahmedabad", "mumbai"],
    "marble_makrana": ["jaipur", "delhi", "gurgaon", "ahmedabad"],
    "granite_south": ["bengaluru", "hyderabad", "chennai"],
    "travertine": ["mumbai", "delhi", "bengaluru"],  # mostly imported
    "sandstone_dholpur": ["jaipur", "delhi", "agra"],

    # Metals
    "mild_steel": ["*"],
    "stainless_steel_304": ["*"],
    "aluminium_6061": ["*"],
    "brass": ["moradabad", "delhi", "mumbai", "jaipur"],  # Moradabad is the hub

    # Upholstery / textiles
    "leather_genuine_grade_A": ["chennai", "kanpur", "kolkata", "delhi", "mumbai"],
    "fabric_cotton": ["*"],
    "fabric_linen": ["delhi", "mumbai", "bengaluru"],
    "fabric_wool_blend": ["delhi", "srinagar", "mumbai", "bengaluru"],

    # Terracotta / tiles
    "terracotta": ["kochi", "chennai", "jaipur", "kolkata"],
    "vitrified_tiles": ["*"],
    "ceramic_tiles": ["*"],
}

# Lead-time adder (weeks) when material has to be trucked in from a non-local hub.
REMOTE_LEAD_TIME_ADDER_WEEKS: tuple[int, int] = (1, 3)


def price_index_for_city(city: str | None) -> float:
    if not city:
        return 1.0
    key = city.strip().lower().replace(" ", "_")
    return CITY_PRICE_INDEX.get(key, 1.0)


def is_locally_available(material: str, city: str | None) -> bool:
    if not material:
        return False
    mat_key = material.strip().lower().replace(" ", "_").replace("-", "_")
    cities = MATERIAL_AVAILABILITY.get(mat_key)
    if cities is None:
        return False
    if "*" in cities:
        return True
    if not city:
        return False
    return city.strip().lower().replace(" ", "_") in cities


def availability_report(materials: list[str], city: str | None) -> dict:
    """Return {locally_available, requires_transport, unknown} for the list."""
    local: list[str] = []
    remote: list[str] = []
    unknown: list[str] = []
    for mat in materials or []:
        mat_key = mat.strip().lower().replace(" ", "_").replace("-", "_")
        cities = MATERIAL_AVAILABILITY.get(mat_key)
        if cities is None:
            unknown.append(mat)
        elif "*" in cities or (city and city.strip().lower().replace(" ", "_") in cities):
            local.append(mat)
        else:
            remote.append(mat)
    return {
        "locally_available": local,
        "requires_transport": remote,
        "unknown": unknown,
        "remote_lead_time_adder_weeks": REMOTE_LEAD_TIME_ADDER_WEEKS,
        "city_price_index": price_index_for_city(city),
    }
