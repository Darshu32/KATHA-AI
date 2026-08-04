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


def _multiroom_checks(sm, pack: dict, code: str) -> list[dict]:
    """Habitable minimums checked over EVERY room and aggregated per criterion.

    Ceiling height is universal (hard). Area / short-side stay soft — a small
    service room (bath, utility) legitimately falls below the *habitable* minimum
    and must not flip a whole plan to REVIEW. Opening-based checks (egress,
    daylight) wait until openings are placed on multi-room walls.
    """
    rooms = sm.rooms
    return [
        _agg_check(
            "Ceiling height", rooms,
            lambda rm: rm.envelope.height >= pack["min_ceiling_m"],
            lambda n: f"all {n} rooms ≥ {pack['min_ceiling_m']} m · {code}",
            lambda fails, n: f"{len(fails)}/{n} rooms below {pack['min_ceiling_m']} m ceiling · {code}",
            soft=False,
        ),
        _agg_check(
            "Room area", rooms,
            lambda rm: rm.area >= pack["min_area_m2"],
            lambda n: f"all {n} rooms ≥ {pack['min_area_m2']} m² · {code}",
            lambda fails, n: f"{len(fails)}/{n} below {pack['min_area_m2']} m² habitable (e.g. {fails[0].name}) · {code}",
            soft=True,
        ),
        _agg_check(
            "Min room dimension", rooms,
            lambda rm: min(rm.envelope.length, rm.envelope.width) >= pack["min_short_side_m"],
            lambda n: f"all {n} rooms ≥ {pack['min_short_side_m']} m short side · {code}",
            lambda fails, n: f"{len(fails)}/{n} rooms below {pack['min_short_side_m']} m short side · {code}",
            soft=True,
        ),
        {"label": "Openings", "status": "info",
         "note": f"egress / daylight checked once openings are placed · {code}"},
    ]


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
