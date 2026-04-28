"""DXF importer — read 2D plan entities into footprint polygons + dims.

Uses ezdxf (already a project dep). Extracts LINE / LWPOLYLINE / POLYLINE
/ INSERT / TEXT / DIMENSION entities and rolls them into a normalised
shape the LLM ingestion stage can map onto the design graph.

DWG (binary) is not supported by ezdxf without extra tooling — we
emit a polite warning and ask the caller to export DXF instead.
"""

from __future__ import annotations

import io
from typing import Any

try:  # ezdxf is a hard dep, but keep the importer load-safe.
    import ezdxf
    from ezdxf.recover import readfile as recover_readfile
except Exception:  # noqa: BLE001
    ezdxf = None
    recover_readfile = None


def _bbox(points: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    warnings: list[str] = []

    if filename.lower().endswith(".dwg"):
        warnings.append(
            "DWG (binary AutoCAD) is not supported. Export as DXF (any AutoCAD R2010+ "
            "release) and re-upload."
        )
        return {
            "format": "dwg",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "DWG cannot be parsed without proprietary libs — please re-export as DXF.",
            "extracted": {},
            "warnings": warnings,
        }

    if ezdxf is None:
        return {
            "format": "dxf",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "ezdxf is not installed in this environment.",
            "extracted": {},
            "warnings": ["ezdxf import failed — install ezdxf to parse DXF files."],
        }

    try:
        bio = io.StringIO(payload.decode("latin-1", errors="ignore"))
        doc = ezdxf.read(bio)
    except Exception:
        try:
            bio = io.BytesIO(payload)
            doc, _aud = recover_readfile(bio)
        except Exception as exc:  # noqa: BLE001
            return {
                "format": "dxf",
                "filename": filename,
                "size_bytes": len(payload),
                "summary": "Could not parse DXF.",
                "extracted": {},
                "warnings": [f"ezdxf parse failed: {exc}"],
            }

    msp = doc.modelspace()
    layers = [layer.dxf.name for layer in doc.layers]
    line_count = 0
    polyline_segments: list[list[tuple[float, float]]] = []
    inserts: list[dict] = []
    texts: list[str] = []
    dimensions: list[dict] = []

    all_points: list[tuple[float, float]] = []

    for entity in msp:
        et = entity.dxftype()
        if et == "LINE":
            line_count += 1
            try:
                a = (entity.dxf.start.x, entity.dxf.start.y)
                b = (entity.dxf.end.x, entity.dxf.end.y)
                all_points.extend([a, b])
            except Exception:
                continue
        elif et in ("LWPOLYLINE", "POLYLINE"):
            try:
                pts = [(p[0], p[1]) for p in entity.get_points("xy")] if et == "LWPOLYLINE" \
                    else [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
                polyline_segments.append(pts)
                all_points.extend(pts)
            except Exception:
                continue
        elif et == "INSERT":
            try:
                pos = entity.dxf.insert
                inserts.append({
                    "block": entity.dxf.name,
                    "x": float(pos.x), "y": float(pos.y),
                    "rotation_deg": float(entity.dxf.rotation),
                    "scale": [float(entity.dxf.xscale), float(entity.dxf.yscale)],
                    "layer": entity.dxf.layer,
                })
                all_points.append((float(pos.x), float(pos.y)))
            except Exception:
                continue
        elif et == "TEXT" or et == "MTEXT":
            try:
                texts.append(entity.dxf.text if et == "TEXT" else entity.text)
            except Exception:
                continue
        elif et == "DIMENSION":
            try:
                dimensions.append({
                    "type": entity.dxf.dimtype if hasattr(entity.dxf, "dimtype") else None,
                    "measurement": float(entity.get_measurement()) if hasattr(entity, "get_measurement") else None,
                    "text": getattr(entity.dxf, "text", "") or "",
                    "layer": entity.dxf.layer,
                })
            except Exception:
                continue

    bbox = _bbox(all_points)
    return {
        "format": "dxf",
        "filename": filename,
        "size_bytes": len(payload),
        "summary": (
            f"DXF: {len(layers)} layer(s); {line_count} line(s); "
            f"{len(polyline_segments)} polyline(s); {len(inserts)} insert(s); "
            f"{len(dimensions)} dimension(s)."
        ),
        "extracted": {
            "layers": layers,
            "line_count": line_count,
            "polylines": [
                {
                    "point_count": len(pts),
                    "closed": pts[0] == pts[-1] if len(pts) > 1 else False,
                    "bbox": _bbox(pts),
                } for pts in polyline_segments[:50]
            ],
            "inserts": inserts[:50],
            "text_excerpt": texts[:50],
            "dimensions": dimensions[:100],
            "drawing_bbox": bbox,
        },
        "warnings": warnings,
    }
