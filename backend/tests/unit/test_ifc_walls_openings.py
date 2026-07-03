"""IFC export: real walls voided by real openings (not floating boxes).

Guards the Step-4 upgrade: windows/doors must become ``IfcOpeningElement`` that
*void* an ``IfcWall`` (``IfcRelVoidsElement``) and are *filled* by an
``IfcWindow`` / ``IfcDoor`` (``IfcRelFillsElement``) — the coordinated topology
Revit / ArchiCAD expect — and must NOT also appear as loose furnishings.
"""

from __future__ import annotations

import pytest

pytest.importorskip("ifcopenshell")

from app.services.exporters import ifc_exporter


def _graph() -> dict:
    return {
        "site": {"unit": "metric"},
        "spaces": [{"id": "s1", "type": "Living Room",
                    "dimensions": {"length": 5.49, "width": 4.27, "height": 2.75}}],
        "objects": [
            {"id": "sofa_1", "type": "sofa", "material": "linen",
             "position": {"x": 2.6, "y": 0.0, "z": 2.1},
             "dimensions": {"length": 2.0, "width": 0.9, "height": 0.8}},
            {"id": "win_1", "type": "window", "material": "glass",
             "position": {"x": 3.6, "y": 0.9, "z": 0.0},
             "dimensions": {"length": 1.8, "width": 0.1, "height": 1.3}},
            {"id": "door_1", "type": "door", "material": "oak",
             "position": {"x": 0.0, "y": 0.0, "z": 2.0},
             "dimensions": {"length": 0.95, "width": 0.1, "height": 2.1}},
        ],
    }


def _export_text() -> str:
    out = ifc_exporter.export({"meta": {"project_name": "Living Room Demo"}}, _graph())
    assert out["filename"].endswith(".ifc")
    return out["bytes"].decode("utf-8", "ignore")


def test_has_four_perimeter_walls() -> None:
    assert _export_text().count("IFCWALL(") == 4


def test_openings_void_walls_and_are_filled() -> None:
    data = _export_text()
    # One opening per window+door, each voiding a wall and filled by the element.
    assert data.count("IFCOPENINGELEMENT(") == 2
    assert data.count("IFCRELVOIDSELEMENT(") == 2
    assert data.count("IFCRELFILLSELEMENT(") == 2
    assert data.count("IFCWINDOW(") == 1
    assert data.count("IFCDOOR(") == 1


def test_openings_not_duplicated_as_furniture() -> None:
    data = _export_text()
    # Only the sofa is furniture; the window/door are fillings, not furnishings.
    assert data.count("IFCFURNITURE(") == 1


def test_handles_graph_without_openings() -> None:
    graph = _graph()
    graph["objects"] = [graph["objects"][0]]  # sofa only
    out = ifc_exporter.export({"meta": {}}, graph)
    data = out["bytes"].decode("utf-8", "ignore")
    assert data.count("IFCWALL(") == 4           # walls still built
    assert data.count("IFCOPENINGELEMENT(") == 0  # nothing to void
    assert data.count("IFCFURNITURE(") == 1
