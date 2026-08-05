"""Deterministic code checks on the typed SpatialModel — the 'defensible' stamp.

Runs common habitable-room minimums against the resolved spec (no LLM, no DB),
picking the figures for the project's jurisdiction from its region so a drawing
sheet carries a compliance summary accurate for where it's built. India is
sourced live from the seeded NBC figures (``app.knowledge.codes``) — the single
source of truth shared with the standards catalogue; the other jurisdictions use
documented representative minimums (IBC/IRC, Eurocode/DIN, Dubai Building Code).
"""

from __future__ import annotations

from app.knowledge.codes import NBC_INDIA
from app.services.regions import jurisdiction_for_region
from app.services.spatial_resolver import resolve_spatial_model

_nbc = NBC_INDIA["minimum_room_dimensions"]

# Habitable-room minimums per standards jurisdiction (metres / floor-area ratios).
# ``india_nbc`` reads live from the seeded NBC knowledge; the rest are documented
# representative minimums with their clause noted inline.
_CODE_PACKS: dict[str, dict] = {
    "india_nbc": {
        "code": "NBC India Part 3",
        "min_ceiling_m": _nbc["habitable_room_min_height_m"],         # 2.75
        "min_area_m2": _nbc["habitable_room_min_area_m2"],            # 9.5
        "min_short_side_m": _nbc["habitable_room_min_short_side_m"],  # 2.4
        "min_door_w_m": 0.90,      # accessibility doorway clear width
        "min_light_ratio": 0.10,   # NBC: openings >= 1/10 of floor area
        # Per-room-type minimums (NBC carries these) so a kitchen / bath / WC is
        # judged against its own standard, not the habitable-room minimum.
        "min_area_by_cat": {
            "habitable": _nbc["habitable_room_min_area_m2"],  # 9.5
            "kitchen": _nbc["kitchen_min_area_m2"],           # 4.5
            "bathroom": _nbc["bathroom_min_area_m2"],         # 1.8
            "wc": _nbc["wc_min_area_m2"],                     # 1.1
        },
        "min_short_by_cat": {
            "habitable": _nbc["habitable_room_min_short_side_m"],  # 2.4
            "kitchen": _nbc["kitchen_min_short_side_m"],           # 1.5
        },
    },
    "international_ibc": {
        "code": "IBC / IRC 2021",
        "min_ceiling_m": 2.29,     # IRC R305.1 — 7'-6"
        "min_area_m2": 6.5,        # IRC R304 — habitable room >= 70 sq ft
        "min_short_side_m": 2.13,  # IRC R304 — no horizontal dim < 7'
        "min_door_w_m": 0.81,      # IBC 1010 — 32" clear egress door
        "min_light_ratio": 0.08,   # IRC R303 — glazing >= 8% of floor
    },
    "eu_eurocode": {
        "code": "EU residential (DIN)",
        "min_ceiling_m": 2.40,     # common EU/DE habitable minimum
        "min_area_m2": 7.0,
        "min_short_side_m": 2.0,
        "min_door_w_m": 0.80,      # DIN clear leaf
        "min_light_ratio": 0.125,  # DIN 5034 — ~1/8 of floor
    },
    "uae_dubai": {
        "code": "Dubai Building Code",
        "min_ceiling_m": 2.40,
        "min_area_m2": 7.5,
        "min_short_side_m": 2.4,
        "min_door_w_m": 0.85,
        "min_light_ratio": 0.10,
    },
}
_DEFAULT_PACK = _CODE_PACKS["international_ibc"]


def _pack_for(region: str | None) -> dict:
    """Region → jurisdiction → code pack (baseline IBC when unseeded)."""
    return _CODE_PACKS.get(jurisdiction_for_region(region), _DEFAULT_PACK)


def code_label(region: str | None = None) -> str:
    """Human name of the code a sheet is checked against, e.g. 'NBC India Part 3'."""
    return _pack_for(region)["code"]


def _chk(label: str, ok: bool, note: str, *, soft: bool = False) -> dict:
    return {"label": label, "status": "pass" if ok else ("warn" if soft else "fail"), "note": note}


def _agg_check(label: str, rooms: list, ok_fn, note_ok, note_bad, *, soft: bool) -> dict:
    """One check aggregated across every room: pass iff all rooms satisfy it,
    else a warn (soft) or fail naming how many missed."""
    fails = [rm for rm in rooms if not ok_fn(rm)]
    if not fails:
        return {"label": label, "status": "pass", "note": note_ok(len(rooms))}
    return {"label": label, "status": "warn" if soft else "fail", "note": note_bad(fails, len(rooms))}


_SERVICE_HINTS = ("hall", "corridor", "foyer", "lobby", "utility", "store",
                  "balcony", "passage", "stair", "lift", "porch")


def _room_category(text: str) -> str:
    """Classify a room from its name/type into an NBC category so it's judged
    against the right minimum. Unknown → habitable (checked, conservative)."""
    t = (text or "").lower()
    if "kitchen" in t:
        return "kitchen"
    if "wc" in t or "toilet" in t or "powder" in t:
        return "wc"
    if any(k in t for k in ("bath", "shower", "washroom", "ensuite", "en-suite")):
        return "bathroom"
    if any(s in t for s in _SERVICE_HINTS):
        return "service"
    return "habitable"


def _min_area(pack: dict, category: str) -> float | None:
    """Floor-area minimum for a category, or None when the pack has no figure
    for it (that room is then exempt from the area check)."""
    by = pack.get("min_area_by_cat")
    if by and category in by:
        return by[category]
    return pack["min_area_m2"] if category == "habitable" else None


def _min_short(pack: dict, category: str) -> float | None:
    by = pack.get("min_short_by_cat")
    if by and category in by:
        return by[category]
    return pack["min_short_side_m"] if category == "habitable" else None


def _multiroom_checks(sm, pack: dict, code: str) -> list[dict]:
    """Per-room NBC checks, each room judged against the minimum for its TYPE.

    Ceiling + egress are universal (hard). Area / short-side use the room's
    category minimum (kitchen / bath / WC have their own; service rooms with no
    figure are exempt) and stay soft. Daylight applies to habitable rooms only.
    """
    rooms = sm.rooms
    cat = {rm.id: _room_category(rm.name or rm.id) for rm in rooms}
    n = len(rooms)

    checks: list[dict] = [
        _agg_check(
            "Ceiling height", rooms,
            lambda rm: rm.envelope.height >= pack["min_ceiling_m"],
            lambda k: f"all {k} rooms ≥ {pack['min_ceiling_m']} m · {code}",
            lambda fails, k: f"{len(fails)}/{k} rooms below {pack['min_ceiling_m']} m ceiling · {code}",
            soft=False,
        ),
    ]

    area_fails = [rm for rm in rooms
                  if _min_area(pack, cat[rm.id]) is not None and rm.area < _min_area(pack, cat[rm.id])]
    checks.append({
        "label": "Room area",
        "status": "pass" if not area_fails else "warn",
        "note": (f"all {n} rooms meet their type minimum · {code}" if not area_fails
                 else f"{len(area_fails)}/{n} below type minimum (e.g. {area_fails[0].name}) · {code}"),
    })

    short_fails = [rm for rm in rooms
                   if _min_short(pack, cat[rm.id]) is not None
                   and min(rm.envelope.length, rm.envelope.width) < _min_short(pack, cat[rm.id])]
    checks.append({
        "label": "Min room dimension",
        "status": "pass" if not short_fails else "warn",
        "note": (f"all rooms meet their type short-side minimum · {code}" if not short_fails
                 else f"{len(short_fails)}/{n} below type short-side minimum · {code}"),
    })

    # Openings → real egress (all rooms) + daylight (habitable rooms).
    doors: dict[str, int] = {}
    win_area: dict[str, float] = {}
    for seg in sm.wall_segments:
        for op in seg.openings:
            if op.kind == "door":
                for rid in seg.rooms:
                    doors[rid] = doors.get(rid, 0) + 1
            elif op.kind == "window":
                for rid in seg.rooms:
                    win_area[rid] = win_area.get(rid, 0.0) + op.width * op.height

    # Soft: an auto-generated draft may leave a tight room without a door-width
    # connection — a circulation refinement note, not a hard code stop.
    no_door = [rm for rm in rooms if doors.get(rm.id, 0) == 0]
    checks.append({
        "label": "Egress",
        "status": "pass" if not no_door else "warn",
        "note": (f"all {n} rooms reached by a door · {code}" if not no_door
                 else f"{len(no_door)}/{n} rooms need a door added (e.g. {no_door[0].name}) · {code}"),
    })

    ratio = pack["min_light_ratio"]
    habitable = [rm for rm in rooms if cat[rm.id] == "habitable"]
    dark = [rm for rm in habitable if (win_area.get(rm.id, 0.0) / rm.area if rm.area else 0.0) < ratio]
    checks.append({
        "label": "Natural light",
        "status": "pass" if not dark else "warn",
        "note": (f"all {len(habitable)} habitable rooms ≥ {int(ratio * 100)}% glazing · {code}" if not dark
                 else f"{len(dark)}/{len(habitable)} habitable rooms below {int(ratio * 100)}% glazing · {code}"),
    })
    return checks


def run_code_checks(graph: dict, region: str | None = None) -> list[dict]:
    """Return [{label, status: pass|warn|fail|info, note}] for the design, using
    the minimums for ``region``'s jurisdiction (defaults to the home market).

    A solved multi-room plan is checked per-room and aggregated; a single room
    keeps the full opening-aware check set below.
    """
    sm = resolve_spatial_model(graph)
    pack = _pack_for(region)
    code = pack["code"]
    if len(sm.rooms) >= 2:
        return _multiroom_checks(sm, pack, code)
    if sm.kind != "interior" or sm.room is None:
        return [{"label": "Room code checks", "status": "info",
                 "note": f"{code} · site / exterior scope — N/A"}]

    r = sm.room
    area = r.length * r.width
    short_side = min(r.length, r.width)
    openings = [o for w in sm.walls for o in w.openings]
    doors = [o for o in openings if o.kind == "door"]
    win_area = sum(o.width * o.height for o in openings if o.kind == "window")
    ratio = (win_area / area) if area else 0.0

    checks = [
        _chk("Ceiling height", r.height >= pack["min_ceiling_m"],
             f"{r.height:.2f} m ≥ {pack['min_ceiling_m']} m · {code}"),
        _chk("Room area", area >= pack["min_area_m2"],
             f"{area:.1f} m² ≥ {pack['min_area_m2']} m² · {code}", soft=True),
        _chk("Min room dimension", short_side >= pack["min_short_side_m"],
             f"{short_side:.2f} m ≥ {pack['min_short_side_m']} m · {code}", soft=True),
    ]
    if doors:
        widest = max(d.width for d in doors)
        checks.append(_chk("Door clear width", widest >= pack["min_door_w_m"],
                           f"{widest:.2f} m ≥ {pack['min_door_w_m']} m · {code}"))
    else:
        checks.append({"label": "Egress door", "status": "fail",
                       "note": f"no door — egress required · {code}"})
    checks.append(_chk("Natural light", ratio >= pack["min_light_ratio"],
                       f"{ratio * 100:.0f}% of floor ≥ {int(pack['min_light_ratio'] * 100)}% · {code}",
                       soft=True))
    return checks


def tally(checks: list[dict]) -> tuple[int, int, int]:
    """(pass, warn, fail) counts."""
    p = sum(1 for c in checks if c["status"] == "pass")
    w = sum(1 for c in checks if c["status"] == "warn")
    f = sum(1 for c in checks if c["status"] == "fail")
    return p, w, f
