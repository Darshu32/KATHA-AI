"""Deterministic code checks on the typed SpatialModel — the 'defensible' stamp.

Runs a handful of common habitable-room minimums against the resolved spec (no
LLM, no DB) so a drawing sheet can carry a compliance summary. Values are broadly
representative minimums; a later pass can swap in the region-specific figures
already seeded in ``app.services.standards`` per the project's jurisdiction.
"""

from __future__ import annotations

from app.services.spatial_resolver import resolve_spatial_model

# Representative habitable-room minimums (metres / ratios).
_MIN_CEILING = 2.4
_MIN_AREA = 7.0
_MIN_DOOR_W = 0.8
_MIN_LIGHT_RATIO = 0.10  # window area ÷ floor area


def _chk(label: str, ok: bool, note: str, *, soft: bool = False) -> dict:
    return {"label": label, "status": "pass" if ok else ("warn" if soft else "fail"), "note": note}


def run_code_checks(graph: dict) -> list[dict]:
    """Return [{label, status: pass|warn|fail|info, note}] for the design."""
    sm = resolve_spatial_model(graph)
    if sm.kind != "interior" or sm.room is None:
        return [{"label": "Room code checks", "status": "info", "note": "site / exterior scope — N/A"}]

    r = sm.room
    area = r.length * r.width
    openings = [o for w in sm.walls for o in w.openings]
    doors = [o for o in openings if o.kind == "door"]
    win_area = sum(o.width * o.height for o in openings if o.kind == "window")
    ratio = (win_area / area) if area else 0.0

    checks = [
        _chk("Ceiling height", r.height >= _MIN_CEILING, f"{r.height:.2f} m ≥ {_MIN_CEILING} m"),
        _chk("Room area", area >= _MIN_AREA, f"{area:.1f} m² ≥ {_MIN_AREA} m²", soft=True),
    ]
    if doors:
        widest = max(d.width for d in doors)
        checks.append(_chk("Door clear width", widest >= _MIN_DOOR_W, f"{widest:.2f} m ≥ {_MIN_DOOR_W} m"))
    else:
        checks.append({"label": "Egress door", "status": "fail", "note": "no door — egress required"})
    checks.append(
        _chk("Natural light", ratio >= _MIN_LIGHT_RATIO,
             f"{ratio * 100:.0f}% of floor ≥ {int(_MIN_LIGHT_RATIO * 100)}%", soft=True)
    )
    return checks


def tally(checks: list[dict]) -> tuple[int, int, int]:
    """(pass, warn, fail) counts."""
    p = sum(1 for c in checks if c["status"] == "pass")
    w = sum(1 for c in checks if c["status"] == "warn")
    f = sum(1 for c in checks if c["status"] == "fail")
    return p, w, f
