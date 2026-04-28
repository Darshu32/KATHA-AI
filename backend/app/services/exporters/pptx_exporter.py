"""PPTX (PowerPoint) exporter — Office Open XML (zero-dep, hand-rolled).

A .pptx is a zip of XML files. We hand-write the minimum tree
(presentation, slide master, layout, theme, and N slides) so the
output opens in PowerPoint, Keynote, LibreOffice Impress, and Google
Slides without external libraries.

Slides emitted:
    1. Cover                      — project, theme, date
    2. Concept                    — theme story + signature moves
    3. Specification summary      — material / manufacturing call-outs
    4. Cost & pricing snapshot    — manufacturing cost + final retail
    5. Timeline                   — lead time low/high
    6. Renders / drawings index   — list of attached files
    7. Next steps                 — handoff + sign-off

Resolution: 13.333" × 7.5" widescreen (16:9), the modern default.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape


# ── Helpers ─────────────────────────────────────────────────────────────────


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or "project")).strip("-") or "project"


def _e(text: object) -> str:
    return escape(str(text or ""), {"\"": "&quot;", "'": "&apos;"})


def _money(v: object) -> str:
    if v in (None, "", "—"):
        return "—"
    try:
        return f"₹{float(v):,.0f}"
    except (TypeError, ValueError):
        return _e(v)


# ── XML fragments ───────────────────────────────────────────────────────────


def _content_types(slide_count: int) -> str:
    overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(1, slide_count + 1)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
{overrides}
</Types>"""


_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
</Relationships>"""


def _presentation_xml(slide_count: int) -> str:
    sld_id_lst = "".join(
        f'<p:sldId id="{256 + i}" r:id="rId{i + 1}"/>'
        for i in range(slide_count)
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
                xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
                xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                saveSubsetFonts="1">
<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId{slide_count + 1}"/></p:sldMasterIdLst>
<p:sldIdLst>{sld_id_lst}</p:sldIdLst>
<p:sldSz cx="12192000" cy="6858000"/>
<p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>"""


def _presentation_rels(slide_count: int) -> str:
    rels = "".join(
        f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{i + 1}.xml"/>'
        for i in range(slide_count)
    )
    rels += (
        f'<Relationship Id="rId{slide_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" '
        'Target="slideMasters/slideMaster1.xml"/>'
    )
    rels += (
        f'<Relationship Id="rId{slide_count + 2}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" '
        'Target="theme/theme1.xml"/>'
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>"""


_THEME = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="KATHA">
<a:themeElements>
<a:clrScheme name="KATHA">
<a:dk1><a:srgbClr val="111111"/></a:dk1>
<a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
<a:dk2><a:srgbClr val="3D3A36"/></a:dk2>
<a:lt2><a:srgbClr val="EFE9DF"/></a:lt2>
<a:accent1><a:srgbClr val="8C6A4F"/></a:accent1>
<a:accent2><a:srgbClr val="B79A74"/></a:accent2>
<a:accent3><a:srgbClr val="5C3B1E"/></a:accent3>
<a:accent4><a:srgbClr val="2E2A26"/></a:accent4>
<a:accent5><a:srgbClr val="A89F8F"/></a:accent5>
<a:accent6><a:srgbClr val="D9CDB8"/></a:accent6>
<a:hlink><a:srgbClr val="8C6A4F"/></a:hlink>
<a:folHlink><a:srgbClr val="5C3B1E"/></a:folHlink>
</a:clrScheme>
<a:fontScheme name="KATHA">
<a:majorFont>
<a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/>
</a:majorFont>
<a:minorFont>
<a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/>
</a:minorFont>
</a:fontScheme>
<a:fmtScheme name="Office">
<a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:fillStyleLst>
<a:lnStyleLst><a:ln w="9525"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="25400"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln><a:ln w="38100"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>
<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>
<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:bgFillStyleLst>
</a:fmtScheme>
</a:themeElements>
</a:theme>"""


_SLIDE_MASTER = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:cSld>
<p:bg><p:bgPr><a:solidFill><a:srgbClr val="EFE9DF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>
<p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
</p:spTree>
</p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
</p:sldMaster>"""


_SLIDE_MASTER_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>
</Relationships>"""


_SLIDE_LAYOUT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
             xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
             xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
             type="blank" preserve="1">
<p:cSld name="Blank">
<p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
</p:spTree>
</p:cSld>
<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""


_SLIDE_LAYOUT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""


_SLIDE_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>"""


# ── Slide builders ──────────────────────────────────────────────────────────


def _text_box(*, sp_id: int, x_emu: int, y_emu: int, cx_emu: int, cy_emu: int,
              paragraphs: list[tuple[str, dict]]) -> str:
    """One text box. Each paragraph: (text, {size, bold, color}). EMU = 914400/inch."""
    runs = []
    for text, opts in paragraphs:
        sz = int(opts.get("size", 18) * 100)        # half-points × 100
        bold = "1" if opts.get("bold") else "0"
        color = opts.get("color", "111111")
        algn = opts.get("align", "l")
        runs.append(f"""
<a:p>
  <a:pPr algn="{algn}"/>
  <a:r>
    <a:rPr lang="en-US" sz="{sz}" b="{bold}" dirty="0">
      <a:solidFill><a:srgbClr val="{color}"/></a:solidFill>
    </a:rPr>
    <a:t>{_e(text)}</a:t>
  </a:r>
</a:p>""")
    body = "".join(runs)
    return f"""
<p:sp>
  <p:nvSpPr>
    <p:cNvPr id="{sp_id}" name="TextBox{sp_id}"/>
    <p:cNvSpPr txBox="1"/><p:nvPr/>
  </p:nvSpPr>
  <p:spPr>
    <a:xfrm>
      <a:off x="{x_emu}" y="{y_emu}"/>
      <a:ext cx="{cx_emu}" cy="{cy_emu}"/>
    </a:xfrm>
    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
    <a:noFill/>
  </p:spPr>
  <p:txBody>
    <a:bodyPr wrap="square" rtlCol="0"/>
    <a:lstStyle/>
    {body}
  </p:txBody>
</p:sp>"""


def _slide_xml(text_boxes: list[str]) -> str:
    body = "".join(text_boxes)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
       xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
       xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
<p:cSld>
<p:spTree>
<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
{body}
</p:spTree>
</p:cSld>
<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sld>"""


# ── Per-slide content from spec_bundle ──────────────────────────────────────


def _build_cover(spec: dict) -> str:
    meta = spec.get("meta") or {}
    today = datetime.now(timezone.utc).date().isoformat()
    return _slide_xml([
        _text_box(
            sp_id=10, x_emu=720000, y_emu=2200000, cx_emu=10752000, cy_emu=900000,
            paragraphs=[(meta.get("project_name", "KATHA Project"), {"size": 44, "bold": True, "color": "3D3A36"})],
        ),
        _text_box(
            sp_id=11, x_emu=720000, y_emu=3200000, cx_emu=10752000, cy_emu=600000,
            paragraphs=[(f"Theme — {meta.get('theme', '—')}", {"size": 22, "color": "8C6A4F"})],
        ),
        _text_box(
            sp_id=12, x_emu=720000, y_emu=5800000, cx_emu=10752000, cy_emu=400000,
            paragraphs=[
                (f"Generated {today}  •  {meta.get('room_type', '—')}",
                 {"size": 14, "color": "5C3B1E"}),
            ],
        ),
    ])


def _build_concept(spec: dict, graph: dict) -> str:
    meta = spec.get("meta") or {}
    style = (graph.get("style") or {}) if isinstance(graph, dict) else {}
    moves = style.get("signature_moves") or []
    paragraphs: list[tuple[str, dict]] = [
        ("Concept", {"size": 32, "bold": True, "color": "3D3A36"}),
        (f"Theme: {meta.get('theme', '—')}", {"size": 18, "color": "8C6A4F"}),
        ("", {"size": 10}),
    ]
    if moves:
        for m in moves[:8]:
            paragraphs.append((f"•  {m}", {"size": 16, "color": "111111"}))
    else:
        paragraphs.append(
            ("•  Theme rule pack referenced from the BRD knowledge base.", {"size": 16}),
        )
    return _slide_xml([
        _text_box(sp_id=20, x_emu=720000, y_emu=720000,
                  cx_emu=10752000, cy_emu=5400000, paragraphs=paragraphs),
    ])


def _build_specification(spec: dict) -> str:
    material = spec.get("material") or {}
    manufacturing = spec.get("manufacturing") or {}
    primary = (material.get("primary_structure") or [{}])[0]
    paragraphs = [
        ("Specification summary", {"size": 32, "bold": True, "color": "3D3A36"}),
        ("", {"size": 8}),
        (f"Primary material: {primary.get('name', '—')}", {"size": 16}),
        (f"Finish: {primary.get('finish', '—')}", {"size": 14, "color": "5C3B1E"}),
        (f"Lead time (weeks): {primary.get('lead_time_weeks', '—')}", {"size": 14}),
        ("", {"size": 8}),
        ("Manufacturing notes", {"size": 18, "bold": True, "color": "8C6A4F"}),
    ]
    wood = (manufacturing.get("woodworking_notes") or {})
    if wood:
        prec = wood.get("machine_precision_required", {})
        paragraphs.append(
            (f"•  Precision: {prec.get('level', '—')} ±{prec.get('tolerance_mm', '—')} mm",
             {"size": 14}),
        )
        joinery = wood.get("joinery_methods") or []
        if joinery:
            paragraphs.append(
                (f"•  Joinery: {', '.join(j.get('method', '') for j in joinery[:4])}", {"size": 14}),
            )
        lt = wood.get("lead_time") or {}
        paragraphs.append(
            (f"•  Lead time: {lt.get('low_weeks', '—')}–{lt.get('high_weeks', '—')} weeks ({lt.get('complexity', '—')})",
             {"size": 14}),
        )
    return _slide_xml([
        _text_box(sp_id=30, x_emu=720000, y_emu=720000,
                  cx_emu=10752000, cy_emu=5400000, paragraphs=paragraphs),
    ])


def _build_cost(spec: dict) -> str:
    cost = spec.get("cost") or {}
    totals = cost.get("totals") or {}
    paragraphs = [
        ("Cost & pricing", {"size": 32, "bold": True, "color": "3D3A36"}),
        ("", {"size": 10}),
        (f"Currency: {cost.get('currency', 'INR')}", {"size": 14, "color": "5C3B1E"}),
        ("", {"size": 8}),
        (f"Indicative manufacturing cost: {_money(totals.get('base'))}", {"size": 22, "bold": True}),
        (f"Range: {_money(totals.get('low'))}  –  {_money(totals.get('high'))}", {"size": 16}),
        ("", {"size": 10}),
        ("Line items", {"size": 18, "bold": True, "color": "8C6A4F"}),
    ]
    for line in (cost.get("line_items") or [])[:6]:
        paragraphs.append(
            (f"•  {line.get('category', '—')}: {_money(line.get('total_inr'))} ({line.get('quantity', '—')} {line.get('unit', '')})",
             {"size": 13}),
        )
    return _slide_xml([
        _text_box(sp_id=40, x_emu=720000, y_emu=720000,
                  cx_emu=10752000, cy_emu=5400000, paragraphs=paragraphs),
    ])


def _build_timeline(spec: dict) -> str:
    manufacturing = spec.get("manufacturing") or {}
    wood_lt = (manufacturing.get("woodworking_notes") or {}).get("lead_time") or {}
    metal_lt = (manufacturing.get("metal_fabrication_notes") or {}).get("lead_time") or {}
    uphol_lt = (manufacturing.get("upholstery_assembly_notes") or {}).get("lead_time") or {}
    paragraphs = [
        ("Timeline", {"size": 32, "bold": True, "color": "3D3A36"}),
        ("", {"size": 10}),
        (f"Woodworking: {wood_lt.get('low_weeks', '—')}–{wood_lt.get('high_weeks', '—')} weeks",
         {"size": 16}),
        (f"Metal fabrication: {metal_lt.get('low_weeks', '—')}–{metal_lt.get('high_weeks', '—')} weeks",
         {"size": 16}),
        (f"Upholstery assembly: {uphol_lt.get('low_weeks', '—')}–{uphol_lt.get('high_weeks', '—')} weeks",
         {"size": 16}),
        ("", {"size": 10}),
        ("Critical path is woodworking; upholstery follows the frame; metal fab runs in parallel.",
         {"size": 13, "color": "5C3B1E"}),
    ]
    return _slide_xml([
        _text_box(sp_id=50, x_emu=720000, y_emu=720000,
                  cx_emu=10752000, cy_emu=5400000, paragraphs=paragraphs),
    ])


def _build_drawings_index(spec: dict) -> str:
    objects_count = spec.get("objects_count") or 0
    meta = spec.get("meta") or {}
    dims = meta.get("dimensions_m") or {}
    paragraphs = [
        ("Drawings & renders", {"size": 32, "bold": True, "color": "3D3A36"}),
        ("", {"size": 10}),
        (f"Room: {dims.get('length', '—')} × {dims.get('width', '—')} × {dims.get('height', '—')} m",
         {"size": 14}),
        (f"Objects in graph: {objects_count}", {"size": 14}),
        ("", {"size": 10}),
        ("Attached deliverables", {"size": 18, "bold": True, "color": "8C6A4F"}),
        ("•  Plan, elevation, section, isometric (PDF / DXF)", {"size": 14}),
        ("•  3D scene (OBJ / GLTF / FBX)", {"size": 14}),
        ("•  Parametric solid (STEP / IGES)", {"size": 14}),
        ("•  BIM model (IFC) and project data (GeoJSON)", {"size": 14}),
    ]
    return _slide_xml([
        _text_box(sp_id=60, x_emu=720000, y_emu=720000,
                  cx_emu=10752000, cy_emu=5400000, paragraphs=paragraphs),
    ])


def _build_next_steps(spec: dict) -> str:
    meta = spec.get("meta") or {}
    paragraphs = [
        ("Next steps", {"size": 32, "bold": True, "color": "3D3A36"}),
        ("", {"size": 10}),
        ("•  Client review & approval", {"size": 16}),
        ("•  Material samples and finish board", {"size": 16}),
        ("•  Kick off fabrication on PO + 50 % advance", {"size": 16}),
        ("•  Mid-production QA gate", {"size": 16}),
        ("•  Site delivery & install scheduling", {"size": 16}),
        ("", {"size": 14}),
        (f"Studio contact — {meta.get('project_name', '—')}", {"size": 12, "color": "5C3B1E"}),
    ]
    return _slide_xml([
        _text_box(sp_id=70, x_emu=720000, y_emu=720000,
                  cx_emu=10752000, cy_emu=5400000, paragraphs=paragraphs),
    ])


# ── Public ──────────────────────────────────────────────────────────────────


def export(spec: dict, graph: dict) -> dict:
    project = _safe_name((spec.get("meta") or {}).get("project_name", "project"))
    slides = [
        _build_cover(spec),
        _build_concept(spec, graph or {}),
        _build_specification(spec),
        _build_cost(spec),
        _build_timeline(spec),
        _build_drawings_index(spec),
        _build_next_steps(spec),
    ]

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", _content_types(len(slides)))
        zf.writestr("_rels/.rels", _ROOT_RELS)
        zf.writestr("ppt/presentation.xml", _presentation_xml(len(slides)))
        zf.writestr("ppt/_rels/presentation.xml.rels", _presentation_rels(len(slides)))
        zf.writestr("ppt/theme/theme1.xml", _THEME)
        zf.writestr("ppt/slideMasters/slideMaster1.xml", _SLIDE_MASTER)
        zf.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _SLIDE_MASTER_RELS)
        zf.writestr("ppt/slideLayouts/slideLayout1.xml", _SLIDE_LAYOUT)
        zf.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _SLIDE_LAYOUT_RELS)
        for i, slide_xml in enumerate(slides, start=1):
            zf.writestr(f"ppt/slides/slide{i}.xml", slide_xml)
            zf.writestr(f"ppt/slides/_rels/slide{i}.xml.rels", _SLIDE_RELS)

    return {
        "content_type": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "filename": f"{project}-deck.pptx",
        "bytes": bio.getvalue(),
    }
