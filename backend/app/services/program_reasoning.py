"""Program → room-program reasoning — constraint reasoning for the *interior*.

Turns a program brief ("3BHK", "2BHK 900 sqft", "4-bedroom house") into a
grounded ROOM PROGRAM: the list of rooms with target areas taken from the space
standards (:mod:`app.knowledge.space_standards`, NBC minimums) and their
adjacencies — exactly the shape the layout solver places into a real floor plan.

The founding spec and today's pipeline lean on the LLM to decompose "3BHK" into
rooms. This makes it deterministic and standards-grounded: every room respects
its NBC minimum area, and when a built-up area is given the program is balanced
to fit it. Constraints → program, not a guess — and every room area is defensible.
"""
from __future__ import annotations

import math
import re

from app.knowledge import space_standards

_SQFT_TO_SQM = 0.092903
_RES = space_standards.RESIDENTIAL


def parse_bedrooms(text) -> int | None:
    """Pull a bedroom count out of '3BHK' / '3 BHK' / '3-bedroom' / '3 bed'."""
    if not isinstance(text, str):
        return None
    # Require an explicit "BHK"/"bedroom" — NOT bare "beds"/"br", which show up as
    # furniture/context ("a room with 3 beds", "4 br studio") and must not be read
    # as a home program.
    m = re.search(r"(\d+)[\s-]*(?:bhk|b\.?h\.?k|bed\s*rooms?|bedrooms?)\b", text.lower())
    return int(m.group(1)) if m else None


def parse_area_sqm(brief: dict) -> float | None:
    """Built-up area in m² from an explicit field or a 'NNN sqft/sqm' string."""
    for key in ("built_up_area_sqm", "area_sqm", "built_up_area_m2"):
        v = brief.get(key)
        try:
            if v and float(v) > 0:
                return float(v)
        except (TypeError, ValueError):
            pass
    for key in ("built_up_area_sqft", "area_sqft"):
        v = brief.get(key)
        try:
            if v and float(v) > 0:
                return float(v) * _SQFT_TO_SQM
        except (TypeError, ValueError):
            pass
    text = " ".join(str(brief.get(k, "")) for k in ("program", "prompt", "area", "space_notes"))
    m = re.search(r"(\d[\d,\.]*)\s*(sq\s*ft|sqft|sf|sq\.?\s*m|sqm|m2|m²)", text.lower())
    if m:
        val = float(m.group(1).replace(",", ""))
        return val * _SQFT_TO_SQM if "f" in m.group(2) else val
    return None


def _bath_count(bedrooms: int) -> int:
    """Baths per Indian practice: 1BHK→1, 2–3BHK→2, 4+→3."""
    if bedrooms <= 1:
        return 1
    return 2 if bedrooms <= 3 else 3


def _typical(room_type: str, fallback: float) -> float:
    r = _RES.get(room_type) or {}
    return float(r.get("typical_area_m2", fallback))


def _min_area(room_type: str, fallback: float = 0.0) -> float:
    r = _RES.get(room_type) or {}
    return float(r.get("min_area_m2", fallback))


def derive_room_program(brief: dict) -> dict:
    """Grounded room program {spaces, adjacencies, program_summary} for a brief.

    ``brief`` keys used: ``bedrooms`` or ``program``/``prompt`` (→ bedroom count),
    and any built-up area (``built_up_area_sqm``/``…_sqft`` or a 'NNN sqft' in the
    text). Returns spaces the layout solver can place (id, name, room_type, area)
    and adjacencies wiring them through a hall.
    """
    bedrooms = brief.get("bedrooms")
    if not isinstance(bedrooms, int):
        bedrooms = parse_bedrooms(" ".join(str(brief.get(k, "")) for k in ("program", "prompt")))
    if not bedrooms or bedrooms < 1:
        return {"spaces": [], "adjacencies": [], "program_summary": {}}
    bedrooms = min(bedrooms, 8)  # sanity cap
    built_up = parse_area_sqm(brief)

    # 1) Compose the room list with typical (standards) areas. Master ×1.3.
    rooms: list[dict] = []
    rooms.append({"id": "master", "name": "Master Bedroom", "room_type": "bedroom",
                  "typical": round(_typical("bedroom", 12.0) * 1.3, 1)})
    for i in range(2, bedrooms + 1):
        rooms.append({"id": f"bed{i}", "name": f"Bedroom {i}", "room_type": "bedroom",
                      "typical": _typical("bedroom", 12.0)})
    rooms.append({"id": "living", "name": "Living Room", "room_type": "living_room",
                  "typical": _typical("living_room", 20.0)})
    rooms.append({"id": "kitchen", "name": "Kitchen", "room_type": "kitchen",
                  "typical": _typical("kitchen", 9.0)})
    if bedrooms >= 2:
        rooms.append({"id": "dining", "name": "Dining", "room_type": "dining_room",
                      "typical": _typical("dining_room", 12.0)})
    n_baths = _bath_count(bedrooms)
    for b in range(1, n_baths + 1):
        rooms.append({"id": f"bath{b}", "name": "Bathroom" if b == 1 else f"Bathroom {b}",
                      "room_type": "bathroom", "typical": _typical("bathroom", 5.0)})

    # 2) Circulation (hall) at ~12% of the habitable area.
    habitable = sum(r["typical"] for r in rooms)
    hall = {"id": "hall", "name": "Hall", "room_type": "hall", "typical": round(0.12 * habitable, 1)}
    rooms.append(hall)

    # 3) Balance to the built-up area if one was given; never below the NBC min.
    base_total = sum(r["typical"] for r in rooms)
    scale = (built_up / base_total) if (built_up and base_total > 0) else 1.0
    spaces = []
    for r in rooms:
        area = max(round(r["typical"] * scale, 1), _min_area(r["room_type"]))
        spaces.append({
            "id": r["id"], "name": r["name"], "room_type": r["room_type"],
            "area": area, "area_sqm": area,
        })

    # 4) Adjacencies — everything reaches through the hall; master is en-suite;
    #    living/dining/kitchen form the social core.
    adj = [{"a": "hall", "b": "living"}, {"a": "hall", "b": "master"}]
    for i in range(2, bedrooms + 1):
        adj.append({"a": "hall", "b": f"bed{i}"})
    if any(s["id"] == "dining" for s in spaces):
        adj += [{"a": "living", "b": "dining"}, {"a": "dining", "b": "kitchen"}]
    else:
        adj.append({"a": "living", "b": "kitchen"})
    adj.append({"a": "master", "b": "bath1"})            # en-suite
    for b in range(2, n_baths + 1):
        adj.append({"a": "hall", "b": f"bath{b}"})

    total = round(sum(s["area"] for s in spaces), 1)
    return {
        "spaces": spaces,
        "adjacencies": adj,
        "program_summary": {
            "bedrooms": bedrooms, "bathrooms": n_baths, "rooms": len(spaces),
            "built_up_area_sqm": built_up, "programmed_area_sqm": total,
        },
    }


def program_rationale(program: dict) -> list[str]:
    """Human-readable 'here is the program and why' lines for the UI / a report."""
    s = program.get("program_summary") or {}
    if not s:
        return []
    lines = [
        f"{s['bedrooms']}BHK → {s['rooms']} rooms: {s['bedrooms']} bedroom(s) + living + "
        f"kitchen{' + dining' if s['bedrooms'] >= 2 else ''} + {s['bathrooms']} bath(s) + hall, "
        f"decomposed from the brief.",
    ]
    if s.get("built_up_area_sqm"):
        lines.append(
            f"Room areas balanced to the {s['built_up_area_sqm']:.0f} m² built-up "
            f"({s['programmed_area_sqm']:.0f} m² programmed), each held at or above its NBC minimum "
            f"(bedroom ≥ {_min_area('bedroom'):.0f}, kitchen ≥ {_min_area('kitchen'):.1f}, "
            f"bath ≥ {_min_area('bathroom'):.1f} m²)."
        )
    else:
        lines.append("Room areas from typical space standards (no built-up area given).")
    return lines


# ── Hybrid reconcile: deterministic core program + LLM-detected specials ──────

# Non-standard rooms the model may have detected that the base program doesn't
# enumerate — kept so a user's "…with a study / pooja room / balcony" survives.
_SPECIAL_KEYWORDS = (
    "study", "office", "pooja", "puja", "prayer", "balcony", "veranda", "terrace",
    "utility", "laundry", "store", "storage", "dressing", "closet", "walk-in",
    "servant", "staff", "foyer", "lobby", "mudroom", "gym", "library", "guest",
    "home theatre", "home theater", "media",
)


def _stated_area(space: dict) -> float | None:
    dims = space.get("dimensions") if isinstance(space, dict) else None
    if isinstance(dims, dict):
        try:
            length, width = float(dims.get("length") or 0), float(dims.get("width") or 0)
            if length > 0 and width > 0:
                return round(length * width, 1)
        except (TypeError, ValueError):
            pass
    for k in ("area_sqm", "area"):
        try:
            a = float(space.get(k))
            if a > 0:
                return round(a, 1)
        except (TypeError, ValueError):
            pass
    return None


def _is_bedroom(space: dict) -> bool:
    label = " ".join(str(space.get(k) or "") for k in ("room_type", "type", "name", "id")).lower()
    return "bedroom" in label or ("master" in label and "bath" not in label)


def reconcile_program(graph: dict, brief: dict) -> dict | None:
    """RESCUE an under-decomposed home with a deterministic, NBC-grounded program,
    while KEEPING any special rooms the model detected (study, pooja, guest, …).

    Fires only when (a) the brief gives a bedroom count *and* (b) the model
    produced FEWER bedrooms than that — i.e. it collapsed the home. When the model
    already decomposed the program (enough bedrooms), its design is left intact:
    we never replace a good multi-room result or wipe its furniture. Returns
    ``{graph, rationale}`` or ``None`` (a true no-op).
    """
    prog = derive_room_program(brief)
    base = prog["spaces"]
    if not base:
        return None

    # Rescue-only: if the model already produced the bedrooms, keep its design.
    expected = prog["program_summary"]["bedrooms"]
    llm_bedrooms = sum(1 for s in (graph.get("spaces") or [])
                       if isinstance(s, dict) and _is_bedroom(s))
    if llm_bedrooms >= expected:
        return None

    used_ids = {s["id"] for s in base}
    extras, extra_adj = [], []
    for s in (graph.get("spaces") or []):
        if not isinstance(s, dict):
            continue
        label = " ".join(str(s.get(k) or "") for k in ("room_type", "type", "name")).lower()
        if not any(kw in label for kw in _SPECIAL_KEYWORDS):
            continue  # a standard room — the base program already covers it
        rid = str(s.get("id") or s.get("name") or f"extra{len(extras) + 1}").lower().replace(" ", "_")
        while rid in used_ids:
            rid += "_x"
        used_ids.add(rid)
        area = _stated_area(s) or _typical("study", 7.5)
        extras.append({
            "id": rid, "name": str(s.get("name") or rid.replace("_", " ").title()),
            "room_type": str(s.get("room_type") or s.get("type") or "study"),
            "area": area, "area_sqm": area,
        })
        extra_adj.append({"a": "hall", "b": rid})

    out = dict(graph)
    out["spaces"] = base + extras
    out["adjacencies"] = prog["adjacencies"] + extra_adj
    out["objects"] = []  # cleared — furnish_rooms re-furnishes each placed room
    rationale = program_rationale(prog)
    if extras:
        rationale.append("Kept the room(s) you asked for: " + ", ".join(e["name"] for e in extras) + ".")
    return {"graph": out, "rationale": rationale}
