"""Design Process diagram (BRD Layer 2B #5).

The generation narrative as a clean numbered flow: a solid spine, square
step nodes, and a card per decision point carrying the label, the detail,
and the rule category that drove it. Monochrome with a single accent — the
flow, not the colours, does the talking. Content stays in the left column so
the LLM authoring overlay composes on top.
"""

from __future__ import annotations

from app.knowledge import themes
from app.services.diagrams.plan_geom import plan_envelope
from app.services.diagrams.svg_base import (
    ACCENT_WARM,
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    WHITE,
    background,
    line,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
)


def _build_steps(graph: dict) -> list[tuple[str, str, str]]:
    steps: list[tuple[str, str, str]] = []
    # Brief = the whole plan, not just room 1: show the building envelope and,
    # for a multi-room design, the room count rather than one room's type.
    spaces = graph.get("spaces") or ([graph["room"]] if graph.get("room") else [])
    env = plan_envelope(graph)
    envelope = f"{env['l']:.1f}×{env['w']:.1f}×{env['h']:.1f} m"
    dtype = str(graph.get("design_type") or "").lower()
    if dtype in ("product", "furniture"):
        brief_detail = f"Product piece — {envelope}"
    elif dtype in ("architecture", "exterior"):
        brief_detail = f"Exterior massing — {envelope}"
    elif len(spaces) > 1:
        brief_detail = f"{len(spaces)} rooms — {envelope}"
    else:
        room0 = spaces[0] if spaces else {}
        rtype = str(room0.get("room_type") or room0.get("type") or "room").replace("_", " ").title()
        brief_detail = f"{rtype} — {envelope}"
    steps.append(("Brief captured", brief_detail, "input"))

    style = (graph.get("style") or {}).get("primary") or ""
    pack = themes.get(style)
    if pack:
        steps.append((f"Theme: {pack['display_name']}", "Palette + signature moves applied as parametric rules", "theme"))
        primaries = pack.get("material_palette", {}).get("primary", [])
        if primaries:
            steps.append((f"Primary material: {primaries[0]}", "From theme palette · alt: " + ", ".join(primaries[1:] or ["—"]), "material"))

    for c in graph.get("constraints") or []:
        t = c.get("type")
        if t == "parametric_theme_changes" and c.get("count"):
            steps.append((f"Parametric refinement · {c['count']}", "Snapped materials, colours, ergonomic heights to rules", "refinement"))
        elif t == "knowledge_validation":
            steps.append(("Knowledge validation", c.get("summary", ""), "validation"))
        elif t == "ai_recommendations" and c.get("count"):
            steps.append((f"Recommendations · {c['count']}", "Cost alternatives, lead-time path, volume nudges", "recommendation"))

    steps.append(("Final graph", f"{len(graph.get('objects', []))} objects · {len(graph.get('materials', []))} materials", "output"))
    return steps


def generate(graph: dict, *, canvas_w: int = 880, canvas_h: int | None = None) -> dict:
    steps = _build_steps(graph)
    row_h = 78
    top = 116
    if canvas_h is None:
        canvas_h = max(260, top + row_h * len(steps) + 20)

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(title_block(40, 36, "Design Process", f"{len(steps)} decision points in generation order", width=canvas_w - 80))

    spine_x = 74
    node = 24
    card_x = spine_x + 34
    card_w = min(560, canvas_w - card_x - 40)

    # Spine.
    body.append(line(spine_x, top, spine_x, top + row_h * (len(steps) - 1), stroke=INK_SOFT, stroke_width=1.4))

    for i, (label, detail, cat) in enumerate(steps):
        cy = top + i * row_h
        accent = cat in {"theme", "output"}
        node_fill = ACCENT_WARM if accent else INK
        # Step card.
        body.append(rect(card_x, cy - 22, card_w, 52, fill=WHITE, stroke=INK_SOFT, stroke_width=0.7, extra='rx="5"'))
        body.append(text(card_x + 14, cy - 3, label, size=12, weight="600", fill=INK))
        body.append(text(card_x + 14, cy + 15, _clip(detail, 74), size=9.5, fill=INK_SOFT))
        # Category tag (top-right of card).
        body.append(text(card_x + card_w - 12, cy - 8, cat.upper(), size=8, weight="600", fill=INK_MUTED, anchor="end"))
        # Node square with number, over the spine.
        body.append(rect(spine_x - node / 2, cy - node / 2, node, node, fill=node_fill, stroke=PAPER, stroke_width=2, extra='rx="3"'))
        body.append(text(spine_x, cy + 4, str(i + 1).zfill(2), size=9, weight="600", fill=PAPER, anchor="middle"))

    svg = svg_open(canvas_w, canvas_h, title="Design Process") + "".join(body) + svg_close()
    return {"id": "design_process", "name": "Design Process", "format": "svg", "svg": svg, "meta": {"step_count": len(steps)}}


def _clip(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"
