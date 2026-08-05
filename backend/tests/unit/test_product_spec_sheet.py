"""Product spec sheet — the single-object analog of the building GA sheet.

A ``design_type == "product"`` graph must produce a spec sheet: three
orthographic views (front/side/top) projected from the real kernel solids, a
parts schedule (BOM) that folds identical parts to a quantity, and overall
bounding dimensions. ``sheet_svg``/``sheet_pdf``/``sheet_dxf`` must DISPATCH a
product to this sheet and leave the building general-arrangement path for rooms.
"""

from __future__ import annotations

import xml.dom.minidom as minidom

from app.services.spatial.drawings2d import (
    _bom_rows,
    _overall_dims_m,
    sheet_dxf,
    sheet_svg,
    spec_sheet_pdf,
    spec_sheet_svg,
)


def _chair_graph() -> dict:
    """The part list the real LLM emits for a lounge chair (seat + 4 legs + back)."""
    return {
        "design_type": "product",
        "product": {"type": "lounge_chair"},
        "spaces": [],
        "objects": [
            {"id": "seat", "type": "seat", "position": {"x": 0, "y": 0.4, "z": 0},
             "dimensions": {"length": 0.6, "width": 0.6, "height": 0.05}, "material": "tan_leather"},
            *[
                {"id": f"leg_{i}", "type": "leg",
                 "position": {"x": sx * 0.27, "y": 0, "z": sz * 0.27},
                 "dimensions": {"length": 0.05, "width": 0.05, "height": 0.4}, "material": "walnut"}
                for i, (sx, sz) in enumerate([(1, 1), (-1, 1), (1, -1), (-1, -1)], 1)
            ],
            {"id": "backrest", "type": "backrest", "position": {"x": 0, "y": 0.45, "z": -0.27},
             "dimensions": {"length": 0.6, "width": 0.05, "height": 0.45}, "material": "tan_leather"},
        ],
        "materials": [],
    }


def _room_graph() -> dict:
    return {
        "design_type": "interior",
        "room": {"type": "living_room", "dimensions": {"length": 4, "width": 3, "height": 2.7}},
        "spaces": [], "objects": [], "materials": [],
    }


# ── BOM + overall dimensions ──────────────────────────────────────────────


def test_bom_folds_identical_parts_to_quantity():
    rows = _bom_rows(_chair_graph())
    by_part = {r["part"]: r for r in rows}
    assert by_part["leg"]["qty"] == 4                      # four identical legs → one row
    assert by_part["seat"]["qty"] == 1 and by_part["backrest"]["qty"] == 1
    assert by_part["leg"]["size"] == "50×50×400"           # metres → mm
    assert by_part["seat"]["material"] == "tan leather"


def test_overall_dims_are_the_object_bounding_box():
    length, depth, height = _overall_dims_m(_chair_graph())
    assert round(length, 2) == 0.60 and round(depth, 2) == 0.60
    assert round(height, 2) == 0.90                        # floor(0) → backrest top(0.9)


# ── the SVG sheet ─────────────────────────────────────────────────────────


def test_spec_sheet_svg_is_wellformed_and_complete():
    svg = spec_sheet_svg(_chair_graph(), {"project_name": "Lounge Chair", "sheet": "P-101"})
    minidom.parseString(svg)                               # raises on malformed XML
    for token in ("FRONT", "SIDE", "TOP", "PARTS SCHEDULE", "OVERALL",
                  "PRODUCT SPECIFICATION", "walnut", "tan leather", "900 mm"):
        assert token in svg, token


def test_titleblock_labels_the_object_from_the_type_constraint():
    # a persisted DesignGraph has no raw `product` dict — the orchestrator stamps
    # the whole-object type as a `product_type` constraint instead.
    graph = _chair_graph()
    graph.pop("product")
    graph["constraints"] = [{"id": "product_type", "type": "product_meta", "value": "lounge_chair"}]
    svg = spec_sheet_svg(graph, {"project_name": "Chair"})
    assert "LOUNGE CHAIR" in svg


def test_spec_sheet_survives_empty_part_list():
    graph = {"design_type": "product", "product": {"type": "stool"}, "spaces": [], "objects": []}
    svg = spec_sheet_svg(graph, {})
    minidom.parseString(svg)                               # no crash on a partless product
    assert "PARTS SCHEDULE" in svg


# ── dispatch: product → spec sheet, room → general arrangement ────────────


def test_sheet_svg_dispatches_product_to_spec_sheet():
    prod = sheet_svg(_chair_graph(), {"project_name": "X"})
    assert "PARTS SCHEDULE" in prod and "GENERAL ARRANGEMENT" not in prod


def test_sheet_svg_keeps_general_arrangement_for_rooms():
    room = sheet_svg(_room_graph(), {"project_name": "Y", "region": "india"})
    assert "GENERAL ARRANGEMENT" in room and "PARTS SCHEDULE" not in room


def test_spec_sheet_pdf_and_dxf_dispatch():
    import io

    import ezdxf

    graph = _chair_graph()
    assert spec_sheet_pdf(graph, {}).startswith(b"%PDF")

    dxf = sheet_dxf(graph)                                 # product → FRONT/SIDE/TOP layers
    doc = ezdxf.read(io.StringIO(dxf.decode("utf-8")))     # check the layer table, not raw bytes
    layers = {layer.dxf.name for layer in doc.layers}
    assert {"FRONT", "SIDE", "TOP"} <= layers
    assert not ({"PLAN", "SECTION", "ELEVATION"} & layers)  # not the building GA layers
