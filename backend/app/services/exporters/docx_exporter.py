"""DOCX specification document — python-docx layout.

Produces a Word file with the same sections as the PDF but editable and
client-deliverable via email.
"""

from __future__ import annotations

import io

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.shared import Cm, Pt, RGBColor


def _fmt_range(v) -> str:
    if isinstance(v, (list, tuple)) and len(v) == 2:
        return f"{v[0]} – {v[1]}"
    if v is None:
        return "—"
    return str(v)


def _flat(v) -> str:
    if isinstance(v, dict):
        return ", ".join(f"{k}: {_flat(x)}" for k, x in v.items())
    if isinstance(v, list):
        return "; ".join(_flat(x) for x in v)
    if isinstance(v, tuple):
        return _fmt_range(list(v))
    return "—" if v is None else str(v)


def _h1(doc, text):
    p = doc.add_heading(text, level=1)
    for run in p.runs:
        run.font.color.rgb = RGBColor(0x1F, 0x1D, 0x1A)


def _h2(doc, text):
    p = doc.add_heading(text, level=2)
    for run in p.runs:
        run.font.color.rgb = RGBColor(0x4A, 0x46, 0x3F)


def _table(doc, header: list[str], rows: list[list]):
    table = doc.add_table(rows=1, cols=len(header))
    table.alignment = WD_TABLE_ALIGNMENT.LEFT
    table.style = "Light Grid Accent 1"
    for i, h in enumerate(header):
        cell = table.rows[0].cells[i]
        cell.text = h
        for run in cell.paragraphs[0].runs:
            run.bold = True
            run.font.size = Pt(9)
    for row in rows:
        cells = table.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v) if v is not None else "—"
            for run in cells[i].paragraphs[0].runs:
                run.font.size = Pt(9)
    return table


def export(spec: dict, graph: dict) -> dict:
    doc = Document()

    for section in doc.sections:
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)

    meta = spec["meta"]

    title = doc.add_paragraph()
    run = title.add_run("KATHA Design Dossier")
    run.bold = True
    run.font.size = Pt(24)

    subtitle = doc.add_paragraph()
    subtitle.add_run(
        f"{meta['project_name']} · {meta.get('room_type', '—')} · Theme: {meta.get('theme', '—')} · "
        f"{meta['dimensions_m'].get('length','?')} x {meta['dimensions_m'].get('width','?')} x "
        f"{meta['dimensions_m'].get('height','?')} m · Generated {meta['generated_at']}"
    ).italic = True

    # Materials.
    _h1(doc, "Materials")
    mat = spec["material"]
    header = ["Name", "Grade", "Finish", "Color", "Supplier", "Lead (wk)", "Cost INR"]
    for label, rows_src in [
        ("Primary Structure", mat["primary_structure"]),
        ("Secondary", mat["secondary_materials"]),
        ("Upholstery", mat["upholstery"]),
        ("Hardware", mat["hardware"]),
        ("Finishing", mat["finishing"]),
    ]:
        if not rows_src:
            continue
        _h2(doc, label)
        rows = [
            [
                r.get("name", "—"),
                r.get("grade", "—"),
                r.get("finish", "—"),
                r.get("color", "—"),
                r.get("supplier", "—"),
                _fmt_range(r.get("lead_time_weeks")),
                _fmt_range(r.get("cost_inr")),
            ]
            for r in rows_src
        ]
        _table(doc, header, rows)
    tn = mat.get("total_notes", {})
    if tn.get("adjusted_note"):
        p = doc.add_paragraph(tn["adjusted_note"])
        p.runs[0].font.size = Pt(9)

    # Manufacturing.
    doc.add_page_break()
    _h1(doc, "Manufacturing")
    for trade, block in spec["manufacturing"].items():
        _h2(doc, trade.replace("_", " ").title())
        _table(doc, ["Key", "Value"], [[k.replace("_", " ").title(), _flat(v)] for k, v in block.items()])

    # MEP.
    doc.add_page_break()
    _h1(doc, "MEP — Mechanical, Electrical, Plumbing")
    for system, block in spec["mep"].items():
        _h2(doc, system.upper())
        _table(doc, ["Parameter", "Value"], [[k.replace("_", " ").title(), _flat(v)] for k, v in block.items()])

    # Cost.
    doc.add_page_break()
    _h1(doc, "Cost Estimate")
    c = spec["cost"]
    totals = c.get("totals", {})
    doc.add_paragraph(
        f"Status: {c.get('status','pending').title()} · Currency: {c.get('currency','INR')} · "
        f"Total (low / base / high): {totals.get('low','—')} / {totals.get('base','—')} / {totals.get('high','—')}"
    )
    line_items = c.get("line_items") or []
    if line_items:
        rows = [
            [
                li.get("category", "—"),
                li.get("itemName") or li.get("item_name") or li.get("name", "—"),
                str(li.get("quantity", "—")),
                li.get("unit", "—"),
                _fmt_range(li.get("unitRate") or li.get("unit_rate")),
                _fmt_range(li.get("totalLow") or li.get("total_low")),
                _fmt_range(li.get("totalHigh") or li.get("total_high")),
            ]
            for li in line_items[:60]
        ]
        _table(doc, ["Category", "Item", "Qty", "Unit", "Rate", "Low", "High"], rows)
    else:
        doc.add_paragraph("Cost will be computed after the estimation pipeline completes.")
    for a in c.get("assumptions", [])[:10]:
        doc.add_paragraph(f"• {a}")

    buffer = io.BytesIO()
    doc.save(buffer)
    buffer.seek(0)
    return {
        "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "filename": f"{_safe_name(meta['project_name'])}-dossier.docx",
        "bytes": buffer.getvalue(),
    }


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "project"
