"""Constraint → design reasoning — the layer the founding spec is missing.

The founding spec (and today's pipeline) treats climate as a *checker*: the
zone knowledge in :mod:`app.knowledge.climate` "feeds the LLM prompt (grounding)
and the validator (post-generation checks)". It never *drives* form. This module
flips that — it turns the same knowledge into concrete DESIGN MOVES with a stated
rationale, and applies the geometric ones to the massing.

So the system PROPOSES a brise-soleil because the facade faces the afternoon sun
in a hot climate — not because the user typed "timber slats". That is the leap
from an output-factory to a design partner.

Everything here is deterministic and grounded in the NBC / SP 41 zone data — no
LLM, no external service — so it is testable and never drifts.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.knowledge import climate

# ── Compass + sun model (Northern hemisphere / India) ────────────────────────
_CANON = {
    "n": "N", "north": "N", "s": "S", "south": "S", "e": "E", "east": "E",
    "w": "W", "west": "W", "ne": "NE", "north-east": "NE", "northeast": "NE",
    "nw": "NW", "north-west": "NW", "northwest": "NW", "se": "SE",
    "south-east": "SE", "southeast": "SE", "sw": "SW", "south-west": "SW",
    "southwest": "SW",
}

# Cooling-dominated zones shade the sun; the heating-dominated zone instead wants
# every bit of winter sun, so it is never shaded.
_HEATING_DOMINATED = {"cold"}

# A few well-known cities → NBC zone, so a brief can name a place. (The full,
# authoritative mapping lives DB-side in standards.codes_lookup; this is a
# convenience for the common cases, grounded in climate.ZONES' typical_regions.)
_CITY_ZONE = {
    "jaipur": "hot_dry", "jodhpur": "hot_dry", "ahmedabad": "hot_dry",
    "chennai": "warm_humid", "mumbai": "warm_humid", "kolkata": "warm_humid",
    "goa": "warm_humid", "kochi": "warm_humid", "kozhikode": "warm_humid",
    "delhi": "composite", "lucknow": "composite", "bhopal": "composite",
    "bengaluru": "temperate", "bangalore": "temperate", "pune": "temperate",
    "shimla": "cold", "manali": "cold", "srinagar": "cold", "leh": "cold",
}


def canonical_direction(value) -> str | None:
    if not isinstance(value, str):
        return None
    return _CANON.get(value.strip().lower())


def _parse_dirs(text) -> set[str]:
    """Pull compass directions out of a free-text field like 'N, S (shaded)'."""
    if not isinstance(text, str):
        return set()
    out: set[str] = set()
    for tok in text.replace("/", ",").replace("&", ",").split(","):
        d = canonical_direction(tok.split("(")[0].strip())
        if d:
            out.add(d)
    return out


def zone_for(brief: dict) -> str | None:
    """Resolve the climate zone from an explicit zone or a city name."""
    z = brief.get("climate_zone")
    if isinstance(z, str) and z.strip():
        key = z.strip().lower().replace(" ", "_").replace("-", "_").replace("&", "").replace("__", "_")
        if climate.get(key):
            return key
    loc = brief.get("location")
    if isinstance(loc, str):
        return _CITY_ZONE.get(loc.strip().lower())
    return None


def shade_directions(zone_key: str, zone: dict) -> set[str]:
    """Facade directions that want solar shading in this zone.

    Cooling-dominated zones shade their heat-critical facades — the zone's own
    'minimise openings' directions plus the near-universal problem of the low
    western afternoon sun. The cold zone shades nothing (it wants the sun).
    """
    if zone_key in _HEATING_DOMINATED:
        return set()
    dirs = _parse_dirs((zone.get("preferred_orientation") or {}).get("minimise_openings", ""))
    dirs.add("W")  # west afternoon sun is the near-universal problem in cooling climates
    return dirs


# ── Directives ───────────────────────────────────────────────────────────────

@dataclass
class Directive:
    """One design decision the site/climate implies, with its justification."""
    id: str
    category: str          # shading | orientation | glazing | ventilation | solar_gain | envelope
    title: str
    rationale: str
    target: str | None = None          # a facade direction, when geometric
    params: dict = field(default_factory=dict)


def derive_directives(brief: dict) -> list[Directive]:
    """Turn a site/program brief into design moves grounded in the zone rules.

    ``brief`` keys used: ``climate_zone`` or ``location`` (→ zone), and
    ``facade_orientation`` (the way the primary facade faces). Extra keys are
    ignored, so callers can pass a richer brief.
    """
    zone_key = zone_for(brief)
    zone = climate.get(zone_key) if zone_key else None
    if not zone:
        return []
    name = zone.get("display_name", zone_key)
    po = zone.get("preferred_orientation") or {}
    glz = zone.get("glazing") or {}
    priorities = zone.get("passive_priorities") or []
    facade = canonical_direction(brief.get("facade_orientation"))
    shade = shade_directions(zone_key, zone)
    directives: list[Directive] = []

    # 1) Solar shading on the sun-exposed primary facade (the flagship move).
    if facade and facade in shade:
        devices = glz.get("shading_devices") or ["external louvres", "deep overhangs"]
        directives.append(Directive(
            id="shade_primary_facade",
            category="shading",
            title=f"Shade the {facade} facade with a brise-soleil",
            rationale=(
                f"{name} zone: the {facade} facade takes harsh sun, so it is shaded to "
                f"cut solar heat gain and glare. NBC/SP 41 minimises openings on "
                f"{'/'.join(sorted(shade))}; recommended devices: {', '.join(devices)}. "
                f"Priority: {priorities[0] if priorities else 'shade before insulate'}."
            ),
            target=facade,
            params={"device": "brise_soleil", "orientation": "horizontal",
                    "gradient": "top", "shading_devices": devices},
        ))

    # 2) Passive-solar gain instead of shading, in the heating-dominated zone.
    if zone_key in _HEATING_DOMINATED:
        directives.append(Directive(
            id="admit_south_sun",
            category="solar_gain",
            title="Open the south facade to winter sun",
            rationale=(
                f"{name} zone is heating-dominated: maximise south glazing for passive "
                f"solar gain and keep north openings small to limit heat loss. "
                f"Priority: {priorities[0] if priorities else 'passive solar'}."
            ),
            target="S",
            params={"glazing_priority": "S"},
        ))

    # 3) Orientation — long axis + where the good openings go.
    if po.get("long_axis") or po.get("primary_openings"):
        directives.append(Directive(
            id="orientation",
            category="orientation",
            title=f"Run the long axis {po.get('long_axis', 'E–W')}; primary openings to {po.get('primary_openings', 'N/S')}",
            rationale=(
                f"{name} zone: a {po.get('long_axis', 'E–W')} long axis keeps the harsh "
                f"low sun off the long facades and puts living spaces on the good "
                f"light ({po.get('primary_openings', 'N/S')})."
            ),
            target=None,
            params={k: po.get(k) for k in ("long_axis", "primary_openings", "minimise_openings") if po.get(k)},
        ))

    # 4) Cross-ventilation where the zone makes it mandatory.
    if str(po.get("cross_ventilation", "")).lower() == "mandatory":
        directives.append(Directive(
            id="cross_ventilation",
            category="ventilation",
            title="Plan for cross-ventilation",
            rationale=(
                f"{name} zone: humidity is high, so continuous cross-ventilation is "
                f"mandatory — openable openings on opposite facades along the breeze."
            ),
        ))

    # 5) Glazing cap (window-to-wall ratio) from the zone envelope target.
    wwr = glz.get("window_wall_ratio_max")
    if isinstance(wwr, (int, float)):
        directives.append(Directive(
            id="glazing_cap",
            category="glazing",
            title=f"Cap glazing at {int(wwr * 100)}% window-to-wall",
            rationale=(
                f"{name} zone: keep the window-to-wall ratio at or below "
                f"{int(wwr * 100)}% ({glz.get('glazing_type', 'appropriate glazing')}) "
                f"to hold the envelope's thermal load."
            ),
            params={"window_wall_ratio_max": wwr},
        ))

    return directives


def design_rationale(directives: list[Directive]) -> list[str]:
    """Human-readable 'design decisions & why' lines for the UI / a report."""
    return [f"{d.title} — {d.rationale}" for d in directives]


# ── Applying the geometric moves ─────────────────────────────────────────────

_SOLID_MASS_TYPES = {"building", "block", "wing", "roof", "mass"}


def _massing_bbox(graph: dict):
    """Bounding box (minx,maxx,minz,maxz,miny,maxy) over the solid mass volumes."""
    xs0, xs1, zs0, zs1, ys1 = [], [], [], [], []
    for o in graph.get("objects") or []:
        if not isinstance(o, dict):
            continue
        if str(o.get("type", "")).lower() not in _SOLID_MASS_TYPES:
            continue
        p, d = o.get("position") or {}, o.get("dimensions") or {}
        try:
            cx, cz = float(p.get("x", 0) or 0), float(p.get("z", 0) or 0)
            cy = float(p.get("y", 0) or 0)
            L, W, H = float(d.get("length", 0) or 0), float(d.get("width", 0) or 0), float(d.get("height", 0) or 0)
        except (TypeError, ValueError):
            continue
        xs0.append(cx - L / 2); xs1.append(cx + L / 2)
        zs0.append(cz - W / 2); zs1.append(cz + W / 2)
        ys1.append(cy + H)
    if not xs0:
        return None
    return min(xs0), max(xs1), min(zs0), max(zs1), 0.0, max(ys1)


def apply_directives(graph: dict, directives: list[Directive]) -> dict:
    """Apply the geometric directives to a massing graph (returns a copy).

    Today's flagship move: a shading directive adds a horizontal brise-soleil
    screen across the primary facade (the +z 'front' face of the massing), sized
    to the facade and graded dense-at-the-top for the high sun — reusing the
    kernel's ``screen`` element. Non-geometric directives (orientation, glazing,
    ventilation) are advisory and left for the layout/spec stages to honour.
    """
    out = dict(graph)
    objects = [o for o in (graph.get("objects") or []) if isinstance(o, dict)]
    out["objects"] = objects = list(objects)

    bbox = _massing_bbox(graph)
    if bbox is None:
        return out
    minx, maxx, minz, maxz, _miny, maxy = bbox
    width = max(maxx - minx, 0.5)
    height = max(maxy, 2.4)

    for d in directives:
        if d.category != "shading":
            continue
        # A brise-soleil over the upper ~65% of the primary (front/+z) facade.
        band_h = round(height * 0.65, 2)
        objects.append({
            "id": f"shade_{d.target or 'front'}",
            "type": "screen",
            "name": "Brise-Soleil",
            "role": "massing",
            "material": "dark stained timber",
            "orientation": d.params.get("orientation", "horizontal"),
            "gradient": d.params.get("gradient", "top"),
            "position": {"x": round((minx + maxx) / 2, 3), "y": round(height - band_h, 3),
                         "z": round(maxz + 0.05, 3)},
            "dimensions": {"length": round(width, 3), "width": 0.18, "height": band_h},
        })
    return out


def reason(graph: dict, brief: dict) -> dict:
    """One-call convenience: derive directives, apply the geometric ones, and
    return the enriched graph plus the directives and a human rationale.
    """
    directives = derive_directives(brief)
    return {
        "graph": apply_directives(graph, directives),
        "directives": [d.__dict__ for d in directives],
        "rationale": design_rationale(directives),
    }
