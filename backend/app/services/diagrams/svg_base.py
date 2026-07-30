"""Shared SVG primitives for KATHA auto-diagrams (BRD Layer 2B).

Pure text output — no external dependencies. Each diagram module composes
these helpers into a full <svg> document that renders identically in
browser, PDF, Figma, or any SVG viewer.

Coordinate system: SVG Y grows downward, but we keep plan diagrams in
room-space (metres) via a transform so every module works in natural units.
"""

from __future__ import annotations

import html
import math

# Canonical palette — neutral, printable, aligned with Satoshi/paper UI.
INK = "#1f1d1a"
INK_SOFT = "#4a463f"
INK_MUTED = "#8a847a"
PAPER = "#f7f2ea"
PAPER_DEEP = "#ece5d8"
WHITE = "#ffffff"
ACCENT_WARM = "#b46a3a"
ACCENT_COOL = "#3a6a7a"

ZONE_COLOURS = [
    "#c9b79a", "#d7c3a6", "#b79a74", "#8a6a3b",
    "#5a4632", "#3a5a4a", "#7a4632", "#c98a5a",
]

# Discrete tonal ramp, dark → light. Encodes rank / weight / depth without
# reaching for colour — keeps the figure-ground register the redesigned
# diagrams share.
TONES = ["#1f1d1a", "#453f38", "#6b6459", "#938c7e", "#bcb4a3", "#dcd4c4"]


def tone(rank: int, count: int) -> str:
    """Pick a ramp tone for item ``rank`` of ``count`` (0 = darkest/heaviest)."""
    if count <= 1:
        return TONES[0]
    idx = round(rank / (count - 1) * (len(TONES) - 2))
    return TONES[min(idx, len(TONES) - 1)]


def svg_open(width: int, height: int, view_box: str | None = None, title: str = "") -> str:
    vb = view_box or f"0 0 {width} {height}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="{vb}" font-family="Satoshi, Inter, system-ui, sans-serif" '
        f'role="img" aria-label="{html.escape(title)}">'
    )


def svg_close() -> str:
    return "</svg>"


def rect(x: float, y: float, w: float, h: float, fill: str = "none", stroke: str = INK, stroke_width: float = 1, opacity: float = 1.0, dash: str | None = None, extra: str = "") -> str:
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" '
        f'opacity="{opacity}"{da} {extra}/>'
    )


def line(x1: float, y1: float, x2: float, y2: float, stroke: str = INK, stroke_width: float = 1, dash: str | None = None) -> str:
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{stroke}" stroke-width="{stroke_width}"{da}/>'


def circle(cx: float, cy: float, r: float, fill: str = INK, opacity: float = 1.0, stroke: str = "none", stroke_width: float = 0.0) -> str:
    return (
        f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}" opacity="{opacity}" '
        f'stroke="{stroke}" stroke-width="{stroke_width}"/>'
    )


def arrow(
    x1: float, y1: float, x2: float, y2: float, *,
    stroke: str = INK, stroke_width: float = 1.4, head: float = 7.0, dash: str | None = None,
) -> str:
    """Line from (x1,y1) to (x2,y2) with a filled triangular head at the end."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    ex, ey = x2 - ux * head, y2 - uy * head  # shaft stops short of the tip
    da = f' stroke-dasharray="{dash}"' if dash else ""
    shaft = f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{ex:.2f}" y2="{ey:.2f}" stroke="{stroke}" stroke-width="{stroke_width}"{da}/>'
    lx, ly = ex - uy * head * 0.55, ey + ux * head * 0.55
    rx, ry = ex + uy * head * 0.55, ey - ux * head * 0.55
    headp = f'<polygon points="{lx:.2f},{ly:.2f} {rx:.2f},{ry:.2f} {x2:.2f},{y2:.2f}" fill="{stroke}"/>'
    return shaft + headp


def text(x: float, y: float, content: str, size: float = 11, fill: str = INK, weight: str = "400", anchor: str = "start") -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" fill="{fill}" '
        f'font-weight="{weight}" text-anchor="{anchor}">{html.escape(content)}</text>'
    )


def group(body: str, transform: str = "") -> str:
    t = f' transform="{transform}"' if transform else ""
    return f"<g{t}>{body}</g>"


def background(width: int, height: int, fill: str = PAPER) -> str:
    return rect(0, 0, width, height, fill=fill, stroke="none")


def title_block(x: float, y: float, title: str, subtitle: str = "", width: float = 320) -> str:
    t = text(x, y, title, size=14, weight="600")
    s = text(x, y + 18, subtitle, size=10, fill=INK_SOFT) if subtitle else ""
    rule = line(x, y + 26, x + width, y + 26, stroke=INK_SOFT, stroke_width=0.6)
    return t + s + rule


def legend(x: float, y: float, items: list[tuple[str, str]], row_height: float = 16) -> str:
    """items: list of (swatch_fill, label)."""
    parts: list[str] = []
    for i, (swatch, label) in enumerate(items):
        cy = y + i * row_height
        parts.append(rect(x, cy, 10, 10, fill=swatch, stroke=INK_SOFT, stroke_width=0.5))
        parts.append(text(x + 16, cy + 9, label, size=10, fill=INK_SOFT))
    return "".join(parts)


def compute_plan_transform(room_length_m: float, room_width_m: float, canvas_w: int, canvas_h: int, margin: int = 40) -> tuple[float, float, float]:
    """Return (scale, tx, ty) mapping metres → SVG px, centred in canvas."""
    avail_w = canvas_w - 2 * margin
    avail_h = canvas_h - 2 * margin
    scale = min(avail_w / room_length_m, avail_h / room_width_m)
    room_w_px = room_length_m * scale
    room_h_px = room_width_m * scale
    tx = (canvas_w - room_w_px) / 2
    ty = (canvas_h - room_h_px) / 2
    return scale, tx, ty
