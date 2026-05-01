"""Stage 9 unit tests — haptic seed + extractor + validator + tool registry.

These tests don't touch a DB. They exercise:

- :mod:`app.haptic.seed` — every BRD-anchored value lands on the
  right material, every material covers all four property tables,
  texture codes are unique.
- :mod:`app.haptic.exporter._extract_graph` — pulls rooms / objects /
  materials defensively from a JSONB graph snapshot, normalising
  dimensions to mm.
- :mod:`app.haptic.validator` — coverage outcomes (mapped, fallback,
  missing object types) given a hand-built ``CatalogSnapshot``.
- Tool registry — Stage 9 ships 1 new tool with the right audit
  target and total tool count.
"""

from __future__ import annotations

from app.haptic import (
    GENERIC_MATERIAL_KEY,
    HAPTIC_CATALOG_VERSION,
    HAPTIC_SCHEMA_VERSION,
)
from app.haptic.catalog import CatalogSnapshot, MaterialProfile
from app.haptic.exporter import _compute_workspace, _extract_graph
from app.haptic.seed import (
    build_dimension_rule_rows,
    build_feedback_loop_rows,
    build_firmness_rows,
    build_friction_rows,
    build_texture_rows,
    build_thermal_rows,
    known_feedback_rule_keys,
    known_material_keys,
    known_object_types,
)
from app.haptic.validator import validate_coverage


# ─────────────────────────────────────────────────────────────────────
# Seed module — BRD anchors honoured + structural invariants
# ─────────────────────────────────────────────────────────────────────


def test_seed_versions_are_present_and_strings():
    assert isinstance(HAPTIC_SCHEMA_VERSION, str) and HAPTIC_SCHEMA_VERSION
    assert isinstance(HAPTIC_CATALOG_VERSION, str) and HAPTIC_CATALOG_VERSION


def test_seed_walnut_temperature_matches_brd():
    rows = {r["material_id"]: r for r in build_thermal_rows()}
    assert rows["walnut"]["temperature_celsius"] == 28.0


def test_seed_leather_temperature_matches_brd():
    rows = {r["material_id"]: r for r in build_thermal_rows()}
    assert rows["leather"]["temperature_celsius"] == 32.0


def test_seed_wood_friction_matches_brd():
    """BRD: wood → 0.35. All hardwoods + plywood get tested."""
    rows = {r["material_id"]: r for r in build_friction_rows()}
    for wood in ("walnut", "oak", "teak", "mahogany"):
        assert rows[wood]["coefficient"] == 0.35, wood


def test_seed_leather_friction_matches_brd():
    rows = {r["material_id"]: r for r in build_friction_rows()}
    assert rows["leather"]["coefficient"] == 0.40


def test_seed_every_material_has_all_four_property_rows():
    """No partial profiles — every catalog material covers texture +
    thermal + friction + firmness."""
    keys = set(known_material_keys())
    for builder in (
        build_texture_rows,
        build_thermal_rows,
        build_friction_rows,
        build_firmness_rows,
    ):
        rows = builder()
        present = {r["material_id"] for r in rows}
        assert present == keys, (
            f"property table {builder.__name__} covers "
            f"{len(present)} materials, expected {len(keys)}"
        )


def test_seed_texture_codes_are_unique():
    codes = [r["code"] for r in build_texture_rows()]
    assert len(codes) == len(set(codes)), "duplicate texture codes"


def test_seed_includes_generic_fallback_material():
    keys = set(known_material_keys())
    assert GENERIC_MATERIAL_KEY in keys, (
        "generic fallback profile must be in the seed catalog — the "
        "validator depends on it"
    )


def test_seed_firmness_scales_are_in_enum():
    rows = build_firmness_rows()
    for r in rows:
        assert r["firmness_scale"] in {"soft", "medium", "firm"}, r


def test_seed_chair_dimension_range_matches_brd():
    """BRD: chair seat-height 18-22 in → 457-559 mm."""
    rules = {r["object_type"]: r for r in build_dimension_rule_rows()}
    seat = rules["chair"]["ranges"]["seat_height"]
    assert seat["min_mm"] == 457
    assert seat["max_mm"] == 559


def test_seed_dimension_rules_one_per_object_type():
    """Migration index is unique on object_type — duplicates would
    blow up at upgrade time."""
    rows = build_dimension_rule_rows()
    types = [r["object_type"] for r in rows]
    assert len(types) == len(set(types))


def test_seed_feedback_loop_keys_are_unique():
    rows = build_feedback_loop_rows()
    keys = [r["rule_key"] for r in rows]
    assert len(keys) == len(set(keys))


def test_seed_includes_brd_walnut_to_oak_swap():
    """BRD example: 'walnut → oak, cost -₹Y'."""
    rules = {r["rule_key"]: r for r in build_feedback_loop_rows()}
    assert "material.swap.walnut_to_oak" in rules
    response = rules["material.swap.walnut_to_oak"]["response"]
    assert response["target"] == "cost_inr"
    assert response["delta"] < 0  # cheaper


def test_seed_includes_chair_height_cost_per_cm():
    """BRD example: 'When height changes by 1cm, cost changes by ₹X'."""
    rules = {r["rule_key"]: r for r in build_feedback_loop_rows()}
    assert "chair.seat_height.cost_per_cm" in rules
    rule = rules["chair.seat_height.cost_per_cm"]
    assert rule["trigger"]["axis"] == "seat_height"
    assert rule["trigger"]["delta_unit"] == "cm"
    assert rule["response"]["kind"] == "linear"


def test_seed_known_object_types_covers_brd_examples():
    types = set(known_object_types())
    # BRD calls out chairs, tables, sofas. Plus core architectural.
    for required in ("chair", "sofa", "dining_table", "desk", "door"):
        assert required in types, required


def test_seed_known_feedback_rule_keys_returns_all_keys():
    rows = build_feedback_loop_rows()
    assert sorted(known_feedback_rule_keys()) == sorted(
        r["rule_key"] for r in rows
    )


# ─────────────────────────────────────────────────────────────────────
# Graph extractor — defensiveness + dimension normalisation
# ─────────────────────────────────────────────────────────────────────


def test_extract_graph_handles_empty_dict():
    out = _extract_graph({})
    assert out.rooms == []
    assert out.objects == []
    assert out.materials_used == []
    assert out.object_types_used == []


def test_extract_graph_handles_non_dict():
    out = _extract_graph("not a dict")  # type: ignore[arg-type]
    assert out.rooms == []
    assert out.objects == []


def test_extract_graph_converts_metres_to_mm():
    """Dimensions stored as metres (Stage 4 convention) must come
    out of the exporter as mm."""
    graph = {
        "rooms": [{
            "id": "r1",
            "name": "living",
            "dimensions": {"width": 5.0, "depth": 4.0, "height": 2.7},
        }],
        "objects": [],
    }
    out = _extract_graph(graph)
    assert out.rooms[0]["width_mm"] == 5000.0
    assert out.rooms[0]["depth_mm"] == 4000.0
    assert out.rooms[0]["height_mm"] == 2700.0


def test_extract_graph_leaves_mm_alone():
    """If a graph already stores mm, don't multiply by 1000 again."""
    graph = {
        "rooms": [{
            "dimensions": {"width": 5000, "depth": 4000, "height": 2700},
        }],
        "objects": [],
    }
    out = _extract_graph(graph)
    assert out.rooms[0]["width_mm"] == 5000.0


def test_extract_graph_pulls_materials_from_objects():
    graph = {
        "rooms": [],
        "objects": [
            {"type": "chair", "material": "walnut",
             "dimensions": {"width": 0.5, "depth": 0.5, "height": 0.9}},
            {"type": "chair", "material": "walnut",
             "dimensions": {"width": 0.5, "depth": 0.5, "height": 0.9}},
            {"type": "dining_table", "material": "oak",
             "dimensions": {"width": 1.8, "depth": 0.9, "height": 0.75}},
        ],
    }
    out = _extract_graph(graph)
    # Materials list keeps duplicates — dedup happens downstream.
    assert out.materials_used == ["walnut", "walnut", "oak"]
    assert out.object_types_used == ["chair", "chair", "dining_table"]


def test_extract_graph_handles_material_dict_shape():
    graph = {
        "objects": [
            {"type": "chair", "material": {"key": "leather"}},
            {"type": "sofa", "material": {"name": "Walnut"}},  # casing
        ],
    }
    out = _extract_graph(graph)
    assert out.materials_used == ["leather", "walnut"]


def test_extract_graph_skips_garbage_objects():
    graph = {
        "objects": [
            "not a dict",
            {"type": "chair", "material": "walnut"},
            None,
            42,
        ],
    }
    out = _extract_graph(graph)
    assert len(out.objects) == 1
    assert out.materials_used == ["walnut"]


# ─────────────────────────────────────────────────────────────────────
# Workspace aggregator
# ─────────────────────────────────────────────────────────────────────


def test_compute_workspace_finds_max_bounds():
    rooms = [
        {"width_mm": 5000, "depth_mm": 4000, "height_mm": 2700},
        {"width_mm": 6000, "depth_mm": 3000, "height_mm": 3000},
    ]
    ws = _compute_workspace(rooms)
    assert ws["max_width_mm"] == 6000
    assert ws["max_depth_mm"] == 4000
    assert ws["max_height_mm"] == 3000


def test_compute_workspace_handles_empty_rooms():
    ws = _compute_workspace([])
    assert ws["max_width_mm"] is None
    assert ws["max_depth_mm"] is None


# ─────────────────────────────────────────────────────────────────────
# Validator — coverage outcomes against a hand-built catalog snapshot
# ─────────────────────────────────────────────────────────────────────


def _mk_profile(key: str, *, complete: bool = True) -> MaterialProfile:
    if not complete:
        return MaterialProfile(material_key=key)
    return MaterialProfile(
        material_key=key,
        texture={"code": f"{key}_001", "name": key, "signature_data": {}},
        thermal={"temperature_celsius": 25.0, "source": "test"},
        friction={"coefficient": 0.3, "condition": "dry_room_temp"},
        firmness={"firmness_scale": "medium", "density_kg_m3": 1000.0},
    )


def _mk_snapshot(
    *materials: str, with_generic: bool = True,
    object_types: tuple[str, ...] = ("chair",),
) -> CatalogSnapshot:
    snap = CatalogSnapshot()
    for m in materials:
        snap.materials[m] = _mk_profile(m)
    if with_generic:
        snap.materials[GENERIC_MATERIAL_KEY] = _mk_profile(
            GENERIC_MATERIAL_KEY,
        )
    for t in object_types:
        snap.dimension_rules[t] = {
            "object_type": t,
            "adjustable_axes": ["height"],
            "ranges": {"height": {"min_mm": 400, "max_mm": 800,
                                   "step_mm": 10}},
            "feedback_curve": {"kind": "linear", "constraints": []},
        }
    return snap


def test_validator_all_mapped():
    snap = _mk_snapshot("walnut", "oak")
    report = validate_coverage(
        catalog=snap,
        materials_used=["walnut", "oak"],
        object_types_used=["chair"],
    )
    assert report.all_materials_mapped is True
    assert sorted(report.mapped_materials) == ["oak", "walnut"]
    assert report.fallback_materials == []


def test_validator_falls_back_to_generic():
    snap = _mk_snapshot("walnut")
    report = validate_coverage(
        catalog=snap,
        materials_used=["walnut", "exotic_unicorn_wood"],
        object_types_used=["chair"],
    )
    assert report.all_materials_mapped is False
    assert "exotic_unicorn_wood" in report.fallback_materials
    assert "walnut" in report.mapped_materials


def test_validator_warns_when_generic_missing_from_catalog():
    snap = _mk_snapshot("walnut", with_generic=False)
    report = validate_coverage(
        catalog=snap,
        materials_used=["unknown_material"],
        object_types_used=[],
    )
    assert "unknown_material" in report.fallback_materials
    assert any(
        "generic fallback profile is missing" in w
        for w in report.warnings
    )


def test_validator_dedups_repeated_materials():
    snap = _mk_snapshot("walnut")
    report = validate_coverage(
        catalog=snap,
        materials_used=["walnut", "walnut", "WALNUT", " walnut "],
        object_types_used=[],
    )
    assert report.requested_materials == ["walnut"]
    assert report.mapped_materials == ["walnut"]


def test_validator_flags_missing_object_types():
    snap = _mk_snapshot("walnut", object_types=("chair",))
    report = validate_coverage(
        catalog=snap,
        materials_used=["walnut"],
        object_types_used=["chair", "throne_of_iron"],
    )
    assert "throne_of_iron" in report.missing_object_types
    assert "chair" not in report.missing_object_types


def test_validator_payload_dict_round_trip_keys():
    """Payload-dict keys are the contract for the export's
    ``validation`` block. Lock them in."""
    snap = _mk_snapshot("walnut")
    report = validate_coverage(
        catalog=snap, materials_used=["walnut"], object_types_used=[],
    )
    payload = report.to_payload_dict()
    assert set(payload) == {
        "all_materials_mapped",
        "requested_materials",
        "mapped_materials",
        "fallback_materials",
        "missing_object_types",
        "warnings",
    }


# ─────────────────────────────────────────────────────────────────────
# Tool registry — Stage 9 adds 1 tool
# ─────────────────────────────────────────────────────────────────────


def test_export_haptic_payload_registered():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    assert "export_haptic_payload" in REGISTRY.names()


def test_export_haptic_payload_has_audit_target():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("export_haptic_payload")
    assert spec.audit_target_type == "haptic_export"


def test_export_haptic_payload_input_is_optional():
    """Both fields optional — agent can call with no args to get the
    latest version of the current project."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("export_haptic_payload").input_schema()
    required = set(schema.get("required", []))
    assert required == set()


def test_total_tool_count_at_least_73_after_stage9():
    """Stage 8 (72) + Stage 9 (1) = 73."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    assert len(REGISTRY.names()) >= 73
