"""Design Process diagram (BRD Layer 2B #5).

Step-by-step narrative: each decision point shown as a node in a vertical
flow, annotated with the rule that drove it (theme, ergonomic, code, cost).
Draws on theme_applier + validator outputs already attached to the graph.
"""

from __future__ import annotations

from app.knowledge import themes
from app.services.diagrams.svg_base import (
    ACCENT_COOL,
    ACCENT_WARM,
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    PAPER_DEEP,
    background,
    circle,
    line,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
)


def _build_steps(graph: dict) -> list[tuple[str, str, str]]:
    """Return [(label, detail, category), ...] in the order they'd occur."""
    steps: list[tuple[str, str, str]] = []

    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    steps.append((
        "Brief captured",
        f"{room.get('type', 'room').replace('_', ' ').title()} — {dims.get('length','?')}x{dims.get('width','?')}x{dims.get('height','?')} m",
        "input",
    ))

    style = (graph.get("style") or {}).get("primary") or ""
    pack = themes.get(style)
    if pack:
        steps.append((
            f"Theme selected: {pack['display_name']}",
            "Applied palette + signature moves as parametric rules",
            "theme",
        ))
        primaries = pack.get("material_palette", {}).get("primary", [])
        if primaries:
            steps.append((
                f"Primary material: {primaries[0]}",
                "Pulled from theme palette. Alternatives: " + ", ".join(primaries[1:] or ["—"]),
                "material",
            ))

    # Constraints log: theme_applier changes + validator.
    constraints = graph.get("constraints") or []
    for c in constraints:
        if c.get("type") == "parametric_theme_changes":
            n = c.get("count", 0)
            if n:
                steps.append((
                    f"Parametric refinement: {n} snap(s)",
                    "Snapped materials, colours, ergonomic heights to theme rules",
                    "refinement",
                ))
        elif c.get("type") == "knowledge_validation":
            summary = c.get("summary", "")
            steps.append((
                "Knowledge validation",
                summary,
                "validation",
            ))
        elif c.get("type") == "ai_recommendations":
            n = c.get("count", 0)
            if n:
                steps.append((
                    f"Recommendations: {n} tip(s)",
                    "Cost alternatives, lead-time critical path, volume nudges",
                    "recommendation",
                ))

    steps.append((
        "Final graph",
        f"{len(graph.get('objects', []))} objects, {len(graph.get('materials', []))} materials",
        "output",
    ))

    return steps


_CATEGORY_COLOUR = {
    "input": INK_MUTED,
    "theme": ACCENT_WARM,
    "material": "#8a6a3b",
    "refinement": ACCENT_COOL,
    "validation": "#3a5a4a",
    "recommendation": "#7a4632",
    "output": INK,
}


def generate(graph: dict, *, canvas_w: int = 880, canvas_h: int | None = None) -> dict:
    steps = _build_steps(graph)
    if canvas_h is None:
        canvas_h = max(220, 110 + 70 * len(steps))

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(title_block(40, 36, "Design Process", f"{len(steps)} decision points in generation order", width=canvas_w - 80))

    col_x = 80
    first_y = 110
    row_h = 64
    node_r = 9

    for i, (label, detail, cat) in enumerate(steps):
        cy = first_y + i * row_h
        colour = _CATEGORY_COLOUR.get(cat, INK)

        # Connector from previous node.
        if i > 0:
            body.append(line(col_x, cy - row_h + node_r, col_x, cy - node_r, stroke=INK_SOFT, stroke_width=1.0, dash="3 3"))

        # Node dot + index.
        body.append(circle(col_x, cy, node_r, fill=colour))
        body.append(text(col_x, cy + 3, str(i + 1).zfill(2), size=8, fill=PAPER, anchor="middle", weight="600"))

        # Text block.
        body.append(text(col_x + 22, cy - 2, label, size=12, weight="600"))
        body.append(text(col_x + 22, cy + 14, detail, size=10, fill=INK_SOFT))

        # Category tag pill.
        tag_w = 88
        body.append(rect(canvas_w - 40 - tag_w, cy - 9, tag_w, 18, fill=PAPER_DEEP, stroke=colour, stroke_width=0.8))
        body.append(text(canvas_w - 40 - tag_w / 2, cy + 4, cat.upper(), size=8, fill=colour, anchor="middle", weight="600"))

    svg = svg_open(canvas_w, canvas_h, title="Design Process") + "".join(body) + svg_close()
    return {
        "id": "design_process",
        "name": "Design Process",
        "format": "svg",
        "svg": svg,
        "meta": {"step_count": len(steps)},
    }
