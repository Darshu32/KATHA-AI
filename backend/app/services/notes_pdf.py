"""Server-side PDF rendering for chat notes.

The client jsPDF / html2canvas path overlapped text badly on multi-section
notes (see the reported bug). This renders the note markdown to a clean,
properly paginated PDF with reportlab Platypus — real text flow, no overlap.
"""
from __future__ import annotations

import base64
import io
import re
from xml.sax.saxutils import escape as _esc

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Image as RLImage,
    ListFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    XPreformatted,
)

_INK = colors.HexColor("#1f1d1a")
_INK_SOFT = colors.HexColor("#3a362f")
_MUTED = colors.HexColor("#8a847a")
_CODE_BG = colors.HexColor("#f2efe9")

_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_ITAL = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)")
_LINK = re.compile(r"(?<!\!)\[([^\]]+)\]\(([^)]+)\)")  # [text](url), not ![img](url)
_IMG = re.compile(r"^!\[.*\]\((.*?)\)\s*$")
_HEAD = re.compile(r"^(#{1,3})\s+(.+)$")
_BULLET = re.compile(r"^[-*]\s+(.+)$")
_NUM = re.compile(r"^\d+[.)]\s+(.+)$")
_QUOTE = re.compile(r"^>\s?(.+)$")


def _styles() -> dict:
    ss = getSampleStyleSheet()
    body = ParagraphStyle("NBody", parent=ss["BodyText"], fontName="Helvetica",
                          fontSize=10.5, leading=15, textColor=_INK_SOFT, spaceAfter=6)
    return {
        "body": body,
        "h1": ParagraphStyle("NH1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                             fontSize=18, leading=22, textColor=_INK, spaceBefore=2, spaceAfter=8),
        "h2": ParagraphStyle("NH2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                             fontSize=13.5, leading=18, textColor=_INK, spaceBefore=12, spaceAfter=5),
        "h3": ParagraphStyle("NH3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                             fontSize=11.5, leading=15, textColor=_INK, spaceBefore=8, spaceAfter=4),
        "muted": ParagraphStyle("NMuted", parent=body, fontSize=9, textColor=_MUTED, spaceAfter=10),
        "bullet": ParagraphStyle("NBullet", parent=body, spaceAfter=3),
        "code": ParagraphStyle("NCode", parent=ss["Code"], fontName="Courier", fontSize=8.5,
                               leading=11.5, textColor=_INK, backColor=_CODE_BG,
                               borderPadding=6, leftIndent=2, spaceBefore=4, spaceAfter=8),
    }


def _inline(text: str) -> str:
    """Escape XML, then convert markdown inline spans to reportlab mini-HTML."""
    s = _esc(text)
    s = _LINK.sub(r'<a href="\2" color="#1a5fb4"><u>\1</u></a>', s)
    s = _BOLD.sub(r"<b>\1</b>", s)
    s = _CODE.sub(r'<font face="Courier">\1</font>', s)
    s = _ITAL.sub(r"<i>\1</i>", s)
    return s


def _image_flowable(key: str, images: dict | None, max_w: float):
    """Embed a base64 PNG referenced by an ``![](key)`` marker.

    ``images`` maps a marker key (e.g. a section-diagram id) to a PNG data
    URI the browser rasterised — mermaid can't render server-side, so the
    client hands us a ready-made picture. Returns None (marker skipped) when
    the key is unknown or the payload isn't decodable.
    """
    src = (images or {}).get(key)
    if not src or "base64," not in src:
        return None
    try:
        raw = base64.b64decode(src.split("base64,", 1)[1])
        iw, ih = ImageReader(io.BytesIO(raw)).getSize()
        if not iw or not ih:
            return None
        draw_w = min(max_w, iw * 0.5)          # undo the 2x export scale, cap to column
        draw_h = draw_w * ih / iw
        if draw_h > 460:                        # keep one diagram from filling a page
            draw_h = 460
            draw_w = draw_h * iw / ih
        img = RLImage(io.BytesIO(raw), width=draw_w, height=draw_h)
        img.hAlign = "CENTER"
        return img
    except Exception:
        return None


def _flowables(markdown: str, st: dict, images: dict | None, max_w: float) -> list:
    flow: list = []
    bullets: list = []
    lines = (markdown or "").split("\n")

    def flush_bullets() -> None:
        nonlocal bullets
        if bullets:
            flow.append(ListFlowable(
                [Paragraph(b, st["bullet"]) for b in bullets],
                bulletType="bullet", start="•", leftIndent=18,
                bulletFontSize=9, bulletColor=_INK_SOFT, bulletOffsetY=-1,
            ))
            flow.append(Spacer(1, 4))
            bullets = []

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        if line.startswith("```"):            # fenced code block
            flush_bullets()
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            flow.append(XPreformatted(_esc("\n".join(code)) or " ", st["code"]))
            continue
        if not line:                          # blank → paragraph break
            flush_bullets()
            i += 1
            continue
        mi = _IMG.match(line)
        if mi:                                # image marker → embed if we have it
            flush_bullets()
            img = _image_flowable(mi.group(1), images, max_w)
            if img is not None:
                flow.append(img)
                flow.append(Spacer(1, 6))
            i += 1
            continue

        mh = _HEAD.match(line)
        if mh:
            flush_bullets()
            style = st["h1"] if len(mh.group(1)) == 1 else st["h2"] if len(mh.group(1)) == 2 else st["h3"]
            flow.append(Paragraph(_inline(mh.group(2)), style))
            i += 1
            continue

        mb = _BULLET.match(line) or _NUM.match(line)
        if mb:
            bullets.append(_inline(mb.group(1)))
            i += 1
            continue

        mq = _QUOTE.match(line)
        if mq:
            flush_bullets()
            flow.append(Paragraph(_inline(mq.group(1)), st["body"]))
            i += 1
            continue

        if line.startswith("Tags:") or (line.startswith("*") and line.endswith("*") and len(line) > 2):
            flush_bullets()
            flow.append(Paragraph(_inline(line.strip("*")), st["muted"]))
            i += 1
            continue

        flush_bullets()                        # plain paragraph
        flow.append(Paragraph(_inline(line), st["body"]))
        i += 1

    flush_bullets()
    return flow


def render_notes_pdf(title: str, markdown: str, images: dict | None = None) -> bytes:
    """Render note ``markdown`` to a clean A4 PDF and return the bytes.

    ``images`` optionally maps ``![](key)`` markers to PNG data URIs (used for
    client-rasterised mermaid diagrams the server can't render itself).
    """
    buf = io.BytesIO()
    margin = 18 * mm
    doc = SimpleDocTemplate(
        buf, pagesize=A4, title=(title or "Notes"),
        topMargin=20 * mm, bottomMargin=margin, leftMargin=margin, rightMargin=margin,
    )
    max_w = A4[0] - 2 * margin
    doc.build(_flowables(markdown, _styles(), images, max_w) or [Spacer(1, 1)])
    return buf.getvalue()
