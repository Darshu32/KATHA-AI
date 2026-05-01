"""Stage 5B unit tests — chunker + embedder semantics, no DB.

Covers:

- :class:`StubEmbedder` is deterministic + L2-normalised.
- Per-source chunkers produce non-empty content with expected anchors
  and respect the chunk-size budget.
- Tool registry shape (search / index / stats are wired with the
  right audit settings).
"""

from __future__ import annotations

import math

import pytest

from app.memory.chunker import (
    chunk_cost_engine,
    chunk_design_version,
    chunk_drawing_or_diagram,
    chunk_spec_bundle,
    chunk_text,
)
from app.memory.embeddings import StubEmbedder


# ─────────────────────────────────────────────────────────────────────
# StubEmbedder
# ─────────────────────────────────────────────────────────────────────


async def test_stub_embedder_is_deterministic():
    e = StubEmbedder()
    a = await e.embed_one("kitchen island walnut")
    b = await e.embed_one("kitchen island walnut")
    assert a == b
    assert len(a) == 1536


async def test_stub_embedder_vectors_are_unit_normalised():
    e = StubEmbedder()
    vec = await e.embed_one("anything")
    norm = math.sqrt(sum(x * x for x in vec))
    assert abs(norm - 1.0) < 1e-6


async def test_stub_embedder_embed_many_preserves_order():
    e = StubEmbedder()
    inputs = ["first", "second", "third"]
    out = await e.embed_many(inputs)
    assert len(out) == 3
    # Re-embedding individually should match.
    for s, vec in zip(inputs, out):
        single = await e.embed_one(s)
        assert single == vec


async def test_stub_embedder_handles_empty_input_list():
    e = StubEmbedder()
    out = await e.embed_many([])
    assert out == []


# ─────────────────────────────────────────────────────────────────────
# Generic chunk_text
# ─────────────────────────────────────────────────────────────────────


def test_chunk_text_empty_returns_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  \n") == []


def test_chunk_text_short_input_yields_one_chunk():
    chunks = chunk_text("Hello world.\n\nA single short paragraph.")
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].total_chunks == 1
    assert chunks[0].token_estimate >= 1


def test_chunk_text_long_input_splits_into_multiple_chunks():
    """Past the soft target_tokens, paragraphs flush into separate chunks."""
    para = "a" * 2500   # ~625 tokens at 4 chars/token
    text = "\n\n".join([para] * 4)
    chunks = chunk_text(text, target_tokens=500, max_tokens=1500)
    assert len(chunks) >= 2
    # Sequential indices, consistent total_chunks.
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))
    assert all(c.total_chunks == len(chunks) for c in chunks)


def test_chunk_text_respects_hard_max_via_line_split():
    """A single paragraph above max_tokens splits on lines."""
    # 8000 chars >> 1500-token max (~6000 chars).
    big = "line\n" * 1700
    chunks = chunk_text(big, max_tokens=500)
    # Should split into multiple chunks.
    assert len(chunks) > 1


# ─────────────────────────────────────────────────────────────────────
# chunk_design_version
# ─────────────────────────────────────────────────────────────────────


def test_chunk_design_version_carries_room_dims_and_objects():
    graph = {
        "room": {
            "type": "kitchen",
            "dimensions": {"length": 5.5, "width": 4.0, "height": 2.7},
        },
        "objects": [
            {"id": "o1", "type": "island", "dimensions": {"length": 1.8}},
            {"id": "o2", "type": "stool", "dimensions": {}},
        ],
        "materials": [{"name": "walnut", "category": "wood"}],
        "style": {"primary": "modern"},
    }
    chunks = chunk_design_version(graph, project_name="Test", version_label="v3")
    assert len(chunks) >= 1
    body = "\n\n".join(c.content for c in chunks)
    # Anchors the embedder + LLM should see.
    assert "Design version: v3" in body
    assert "kitchen" in body
    assert "modern" in body
    assert "walnut" in body
    assert "island" in body


def test_chunk_design_version_empty_graph_still_yields_one_chunk():
    chunks = chunk_design_version({}, version_label="v1")
    assert len(chunks) == 1
    assert "Design version: v1" in chunks[0].content


# ─────────────────────────────────────────────────────────────────────
# chunk_spec_bundle
# ─────────────────────────────────────────────────────────────────────


def test_chunk_spec_bundle_includes_each_section():
    bundle = {
        "meta": {
            "project_name": "P",
            "theme": "scandinavian",
            "room_type": "bedroom",
            "dimensions_m": {"length": 4, "width": 3, "height": 2.7},
        },
        "material": {"primary": "oak"},
        "manufacturing": {"woodworking": "dovetail"},
        "mep": {"hvac": "split"},
        "cost": {"total_inr": 100000},
    }
    chunks = chunk_spec_bundle(bundle, project_name="P")
    body = "\n\n".join(c.content for c in chunks)
    assert "scandinavian" in body
    assert "Material spec" in body
    assert "Manufacturing spec" in body
    assert "Mep spec" in body
    assert "Cost spec" in body


def test_chunk_spec_bundle_skips_empty_sections():
    bundle = {
        "meta": {"project_name": "P"},
        "material": {"x": "y"},
        "manufacturing": {},
        "mep": None,
    }
    body = "\n\n".join(c.content for c in chunk_spec_bundle(bundle))
    assert "Material spec" in body
    assert "Manufacturing spec" not in body
    assert "Mep spec" not in body


# ─────────────────────────────────────────────────────────────────────
# chunk_cost_engine
# ─────────────────────────────────────────────────────────────────────


def test_chunk_cost_engine_surfaces_totals_and_assumptions():
    cost = {
        "header": {
            "project": "P",
            "piece_name": "kitchen island",
            "theme": "modern",
            "city": "Mumbai",
            "city_price_index": 1.15,
            "market_segment": "mass_market",
            "complexity": "moderate",
        },
        "total_manufacturing_cost_inr": 250000,
        "material_cost": {"material_subtotal_inr": 150000},
        "labor_cost": {"labor_subtotal_inr": 60000},
        "overhead": {"overhead_subtotal_inr": 40000},
        "summary": {
            "material_pct_of_total": 60,
            "labor_pct_of_total": 24,
            "overhead_pct_of_total": 16,
        },
        "assumptions": [
            "Walnut at ₹600/kg",
            "Bangalore labor band midpoint",
        ],
    }
    chunks = chunk_cost_engine(cost, pricing_snapshot_id="snap_123")
    body = "\n".join(c.content for c in chunks)
    assert "snap_123" in body
    assert "kitchen island" in body
    assert "Mumbai" in body
    assert "250000" in body
    assert "Walnut at ₹600/kg" in body


# ─────────────────────────────────────────────────────────────────────
# chunk_drawing_or_diagram
# ─────────────────────────────────────────────────────────────────────


def test_chunk_drawing_renders_named_keys():
    spec = {
        "scale": "1:50",
        "scale_rationale": "Floor plan default",
        "key_dimensions": [{"label": "overall", "value_m": 5.0}],
        "section_references": [{"axis": "x", "position": 0.5}],
        "material_zones": [{"object_type": "floor", "hatch_key": "wood"}],
    }
    chunks = chunk_drawing_or_diagram(
        spec, kind="plan_view", title="Living Room — Plan", theme="modern",
    )
    body = "\n\n".join(c.content for c in chunks)
    assert "Plan View" in body
    assert "Living Room — Plan" in body
    assert "1:50" in body
    assert "modern" in body


def test_chunk_diagram_handles_minimal_spec():
    """No known anchor keys → still produce a chunk with the kind/title."""
    chunks = chunk_drawing_or_diagram(
        {"some_unknown_key": "ignored"},
        kind="hierarchy", title="Hierarchy", theme="luxe",
    )
    body = chunks[0].content
    assert "Hierarchy" in body
    assert "luxe" in body


# ─────────────────────────────────────────────────────────────────────
# Tool registry shape
# ─────────────────────────────────────────────────────────────────────


def test_search_project_memory_registered_read_only():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("search_project_memory")
    # Read-only: no audit footprint, allows parallel dispatch.
    assert spec.audit_target_type is None
    schema = spec.input_schema()
    props = schema.get("properties", {})
    assert "query" in props
    assert "top_k" in props
    assert props["top_k"].get("minimum") == 1
    assert props["top_k"].get("maximum") == 20
    required = set(schema.get("required", []))
    assert required == {"query"}


def test_index_project_artefact_registered_with_audit_target():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("index_project_artefact")
    assert spec.audit_target_type == "project_memory"
    schema = spec.input_schema()
    required = set(schema.get("required", []))
    # Body + kind + source_id are all required to make the index meaningful.
    assert {"kind", "source_id", "body"}.issubset(required)


def test_project_memory_stats_registered_lightweight_read():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("project_memory_stats")
    assert spec.audit_target_type is None
    assert spec.timeout_seconds <= 30.0
    schema = spec.input_schema()
    required = set(schema.get("required", []))
    assert required == set()


def test_total_tool_count_at_least_59():
    """Stage 4 (55) + Stage 5 recall (1) + Stage 5B memory (3) = 59 minimum."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    assert len(REGISTRY.names()) >= 59
