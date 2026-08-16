"""PDF project dossier — reportlab platypus layout.

Renders the full spec bundle into a multi-page PDF suitable for client
delivery. Sections: cover, summary, materials, manufacturing, MEP, cost.
"""

from __future__ import annotations

import io
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

PAPER = colors.HexColor("#f7f2ea")
PAPER_DEEP = colors.HexColor("#ece5d8")
INK = colors.HexColor("#1f1d1a")
INK_SOFT = colors.HexColor("#4a463f")
INK_MUTED = colors.HexColor("#8a847a")
ACCENT = colors.HexColor("#b46a3a")


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("katha_title", parent=base["Title"], fontName="Helvetica-Bold",
                                 fontSize=26, leading=30, textColor=INK, spaceAfter=6),
        "subtitle": ParagraphStyle("katha_sub", parent=base["Normal"], fontName="Helvetica",
                                    fontSize=11, textColor=INK_SOFT, spaceAfter=20),
        "h1": ParagraphStyle("katha_h1", parent=base["Heading1"], fontName="Helvetica-Bold",
                              fontSize=16, leading=20, textColor=INK, spaceBefore=14, spaceAfter=10),
        "h2": ParagraphStyle("katha_h2", parent=base["Heading2"], fontName="Helvetica-Bold",
                              fontSize=12, leading=16, textColor=INK_SOFT, spaceBefore=10, spaceAfter=6),
        "body": ParagraphStyle("katha_body", parent=base["Normal"], fontName="Helvetica",
                                fontSize=10, leading=14, textColor=INK),
        "small": ParagraphStyle("katha_small", parent=base["Normal"], fontName="Helvetica",
                                 fontSize=8, leading=11, textColor=INK_MUTED),
    }


_CELL_HDR = ParagraphStyle("katha_cell_hdr", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=PAPER)
_CELL_BODY = ParagraphStyle("katha_cell_body", fontName="Helvetica", fontSize=9, leading=11, textColor=INK)


def _cell(value, style: ParagraphStyle) -> Paragraph:
    # Escape XML so values like "R_min >= 2.5 & up" don't break Paragraph markup,
    # and keep newlines as line breaks.
    text = _xml_escape(str(value)).replace("\n", "<br/>")
    return Paragraph(text, style)


def _human_date(iso: str | None) -> str:
    """Raw ISO timestamp → a clean 'DD Mon YYYY' for the dossier header."""
    if not iso:
        return "—"
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(iso)).strftime("%d %b %Y")
    except Exception:
        return str(iso)[:10]


def _table(data: list[list], col_widths: list[float] | None = None) -> Table:
    # Wrap every cell in a Paragraph so long values WRAP inside the column
    # instead of overflowing the page — reportlab does not wrap bare strings.
    wrapped = [
        [c if isinstance(c, Paragraph) else _cell(c, _CELL_HDR if i == 0 else _CELL_BODY) for c in row]
        for i, row in enumerate(data)
    ]
    t = Table(wrapped, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, PAPER_DEEP]),
        ("GRID", (0, 0), (-1, -1), 0.25, INK_MUTED),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
    ]))
    return t


def _fmt_range(v) -> str:
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return f"{v[0]} – {v[1]}"
    if v is None:
        return "—"
    return str(v)


def export(spec: dict, graph: dict) -> dict:
    s = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title=f"KATHA — {spec['meta']['project_name']}",
        author="KATHA AI",
    )

    story = []
    meta = spec["meta"]
    story.append(Paragraph("KATHA Design Dossier", s["title"]))
    # Subtitle from only the meaningful parts — skip an empty room type and the
    # None×None×None dimensions an exterior/massing design carries (no room), and
    # show a clean date instead of a raw ISO timestamp.
    _lead = str(meta.get("design_title") or meta.get("project_name") or "Design")
    _parts: list[str] = [_lead[:1].upper() + _lead[1:]]
    _rt = meta.get("room_type")
    if _rt and str(_rt) not in ("—", "None", ""):
        _parts.append(str(_rt).replace("_", " ").title())
    if meta.get("theme"):
        _parts.append(f"Theme: {meta['theme']}")
    _dims = meta.get("dimensions_m") or {}
    _L, _W, _H = _dims.get("length"), _dims.get("width"), _dims.get("height")
    if all(isinstance(v, (int, float)) for v in (_L, _W, _H)):
        _parts.append(f"{_L} × {_W} × {_H} m")
    _parts.append(f"Generated {_human_date(meta.get('generated_at'))}")
    story.append(Paragraph(_xml_escape("  ·  ".join(_parts)), s["subtitle"]))

    story += _section_materials(spec, s)
    story.append(PageBreak())
    story += _section_manufacturing(spec, s)
    story.append(PageBreak())
    story += _section_mep(spec, s)
    story.append(PageBreak())
    story += _section_cost(spec, s)

    doc.build(story)
    buffer.seek(0)
    return {
        "content_type": "application/pdf",
        "filename": f"{_safe_name(meta['project_name'])}-dossier.pdf",
        "bytes": buffer.getvalue(),
    }


def _section_materials(spec: dict, s: dict) -> list:
    mat = spec["material"]
    story = [Paragraph("Materials", s["h1"])]
    buckets = [
        ("Primary Structure", mat["primary_structure"]),
        ("Secondary", mat["secondary_materials"]),
        ("Upholstery", mat["upholstery"]),
        ("Hardware", mat["hardware"]),
        ("Finishing", mat["finishing"]),
    ]
    for label, rows in buckets:
        if not rows:
            continue
        story.append(Paragraph(label, s["h2"]))
        data = [["Name", "Grade", "Finish", "Color", "Supplier", "Lead (wk)", "Cost INR"]]
        for r in rows:
            data.append([
                r.get("name", "—"),
                r.get("grade", "—"),
                r.get("finish", "—"),
                r.get("color", "—"),
                r.get("supplier", "—"),
                _fmt_range(r.get("lead_time_weeks")),
                _fmt_range(r.get("cost_inr")),
            ])
        story.append(_table(data, col_widths=[30*mm, 22*mm, 26*mm, 18*mm, 28*mm, 16*mm, 22*mm]))
        story.append(Spacer(0, 6))
    tn = mat.get("total_notes", {})
    if tn:
        story.append(Paragraph(tn.get("adjusted_note", ""), s["small"]))
    return story


def _section_manufacturing(spec: dict, s: dict) -> list:
    m = spec["manufacturing"]
    story = [Paragraph("Manufacturing", s["h1"])]
    for trade, block in m.items():
        story.append(Paragraph(trade.replace("_", " ").title(), s["h2"]))
        rows = [["Key", "Value"]]
        for k, v in block.items():
            rows.append([k.replace("_", " ").title(), _flat(v)])
        story.append(_table(rows, col_widths=[60*mm, 115*mm]))
        story.append(Spacer(0, 6))
    return story


def _section_mep(spec: dict, s: dict) -> list:
    mep = spec["mep"]
    story = [Paragraph("MEP — Mechanical, Electrical, Plumbing", s["h1"])]
    for system, block in mep.items():
        story.append(Paragraph(system.upper(), s["h2"]))
        rows = [["Parameter", "Value"]]
        for k, v in block.items():
            rows.append([k.replace("_", " ").title(), _flat(v)])
        story.append(_table(rows, col_widths=[60*mm, 115*mm]))
        story.append(Spacer(0, 6))
    return story


def _section_cost(spec: dict, s: dict) -> list:
    c = spec["cost"]
    story = [Paragraph("Cost Estimate", s["h1"])]
    totals = c.get("totals", {})
    story.append(Paragraph(
        f"Status: {c.get('status','pending').title()}  ·  Currency: {c.get('currency','INR')}  "
        f"·  Total (low / base / high): {totals.get('low','—')} / {totals.get('base','—')} / {totals.get('high','—')}",
        s["body"],
    ))
    line_items = c.get("line_items") or []
    if line_items:
        rows = [["Category", "Item", "Qty", "Unit", "Rate", "Low", "High"]]
        for li in line_items[:60]:
            rows.append([
                li.get("category", "—"),
                li.get("itemName") or li.get("item_name") or li.get("name", "—"),
                str(li.get("quantity", "—")),
                li.get("unit", "—"),
                _fmt_range(li.get("unitRate") or li.get("unit_rate")),
                _fmt_range(li.get("totalLow") or li.get("total_low")),
                _fmt_range(li.get("totalHigh") or li.get("total_high")),
            ])
        story.append(_table(rows, col_widths=[22*mm, 44*mm, 15*mm, 15*mm, 22*mm, 22*mm, 22*mm]))
    else:
        story.append(Paragraph("Cost will be computed after the estimation pipeline completes.", s["small"]))
    for a in c.get("assumptions", [])[:10]:
        story.append(Paragraph(f"• {a}", s["small"]))
    return story


def _flat(v) -> str:
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_flat(x)}" for k, x in v.items())
    if isinstance(v, list):
        return "; ".join(_flat(x) for x in v)
    if isinstance(v, tuple):
        return _fmt_range(list(v))
    return "—" if v is None else str(v)


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "project"
