"""Stage 4C integration tests — orchestration of the cost-engine across
multiple scenarios and sensitivity sweeps.

The Stage 2 cost engine (``generate_cost_engine``) makes a live LLM
call. To keep the test suite hermetic and free of external API spend,
these tests **monkeypatch** the engine with a deterministic fake that
returns the same shape :func:`_summarise_run` consumes. This exercises:

- Input-schema validation (length caps, enum on ``parameter``)
- Baseline delta math
- Cheapest / most-expensive selection
- Sensitivity elasticity for numeric parameters
- Partial-failure handling (one variant raising)
- Snapshot id propagation

A separate ``KATHA_LLM_INTEGRATION_TESTS`` knob would pull in the live
engine — out of scope for Stage 4C.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
async def ctx(db_session):
    from app.agents.tool import ToolContext
    return ToolContext(session=db_session, actor_id=None, request_id="t4c")


async def _call(name: str, raw: dict, ctx) -> dict:
    from app.agents.tool import REGISTRY, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return await call_tool(name, raw, ctx, registry=REGISTRY)


def _fake_engine_factory(price_map: dict[str, float]):
    """Build a fake ``generate_cost_engine`` that prices a request based on
    a label → total map.

    Returns the same shape :func:`_summarise_run` reads from.
    """
    counter = {"snap": 0}

    async def fake(req, *, session, snapshot_id=None, actor_id=None, project_id=None):
        # Resolve "label" the orchestration treats as the dictionary key.
        # Map by piece_name for compare (each scenario has unique
        # piece_name) and by city/complexity/etc. for sensitivity.
        keys = [
            req.piece_name,
            req.city or "_no_city_",
            req.complexity,
            req.market_segment,
            f"hw={req.hardware_piece_count}",
            req.theme or "_no_theme_",
        ]
        total = None
        for k in keys:
            if k in price_map:
                total = price_map[k]
                break
        if total is None:
            total = 100_000.0  # default

        counter["snap"] += 1
        snap_id = f"snap_{counter['snap']:03d}"
        material = round(total * 0.55, 0)
        labor = round(total * 0.30, 0)
        overhead = round(total - material - labor, 0)
        return {
            "id": "cost_engine",
            "name": "Parametric Cost Engine",
            "model": "fake",
            "city": req.city or None,
            "knowledge": {
                "project": {
                    "city_price_index": 1.05 if req.city else 1.0,
                    "market_segment": req.market_segment,
                    "complexity": req.complexity,
                },
            },
            "cost_engine": {
                "total_manufacturing_cost_inr": total,
                "material_cost": {"material_subtotal_inr": material},
                "labor_cost": {"labor_subtotal_inr": labor},
                "overhead": {"overhead_subtotal_inr": overhead},
                "summary": {
                    "material_pct_of_total": round(material / total * 100, 2),
                    "labor_pct_of_total": round(labor / total * 100, 2),
                    "overhead_pct_of_total": round(overhead / total * 100, 2),
                },
            },
            "validation": {"currency_is_inr": True},
            "pricing_snapshot_id": snap_id,
        }

    return fake


# ─────────────────────────────────────────────────────────────────────
# compare_cost_scenarios — validation envelope (no LLM needed)
# ─────────────────────────────────────────────────────────────────────


async def test_compare_rejects_single_scenario(ctx):
    """min_length=2 — one scenario must fail validation."""
    result = await _call(
        "compare_cost_scenarios",
        {
            "scenarios": [
                {"label": "only one"},
            ],
        },
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_compare_rejects_five_scenarios(ctx):
    """max_length=4 — five scenarios must fail validation."""
    result = await _call(
        "compare_cost_scenarios",
        {
            "scenarios": [
                {"label": f"s{i}"} for i in range(5)
            ],
        },
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_compare_rejects_duplicate_labels(ctx):
    result = await _call(
        "compare_cost_scenarios",
        {
            "scenarios": [
                {"label": "Same"},
                {"label": "same"},
            ],
        },
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


# ─────────────────────────────────────────────────────────────────────
# compare_cost_scenarios — orchestration (engine monkeypatched)
# ─────────────────────────────────────────────────────────────────────


async def test_compare_cheapest_and_deltas(monkeypatch, ctx):
    fake = _fake_engine_factory({
        "Baseline": 100_000.0,
        "Premium": 150_000.0,
        "Budget": 80_000.0,
    })
    monkeypatch.setattr(
        "app.agents.tools.cost_extensions.generate_cost_engine",
        fake,
    )

    result = await _call(
        "compare_cost_scenarios",
        {
            "scenarios": [
                {"label": "baseline", "piece_name": "Baseline"},
                {"label": "premium", "piece_name": "Premium"},
                {"label": "budget", "piece_name": "Budget"},
            ],
        },
        ctx,
    )

    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["baseline_label"] == "baseline"
    assert out["cheapest_label"] == "budget"
    assert out["most_expensive_label"] == "premium"
    assert out["spread_inr"] == 70_000.0

    rows = {r["label"]: r for r in out["scenarios"]}
    # Baseline is itself — delta 0.
    assert rows["baseline"]["delta_vs_baseline_inr"] == 0.0
    assert rows["baseline"]["delta_vs_baseline_pct"] == 0.0
    # Premium is +50%.
    assert rows["premium"]["delta_vs_baseline_inr"] == 50_000.0
    assert rows["premium"]["delta_vs_baseline_pct"] == 50.0
    # Budget is -20%.
    assert rows["budget"]["delta_vs_baseline_inr"] == -20_000.0
    assert rows["budget"]["delta_vs_baseline_pct"] == -20.0
    # Each gets a snapshot id.
    for label in ("baseline", "premium", "budget"):
        assert rows[label]["pricing_snapshot_id"]


async def test_compare_partial_failure_keeps_others(monkeypatch, ctx):
    """One scenario raises — the others still report, with a note."""
    from app.services.cost_engine_service import CostEngineError

    async def fake(req, *, session, snapshot_id=None, actor_id=None, project_id=None):
        if req.piece_name == "Broken":
            raise CostEngineError("LLM timed out")
        return {
            "city": req.city or None,
            "knowledge": {"project": {"city_price_index": 1.0}},
            "cost_engine": {
                "total_manufacturing_cost_inr": 100_000.0,
                "material_cost": {"material_subtotal_inr": 55_000.0},
                "labor_cost": {"labor_subtotal_inr": 30_000.0},
                "overhead": {"overhead_subtotal_inr": 15_000.0},
                "summary": {
                    "material_pct_of_total": 55.0,
                    "labor_pct_of_total": 30.0,
                    "overhead_pct_of_total": 15.0,
                },
            },
            "validation": {},
            "pricing_snapshot_id": "snap_x",
        }

    monkeypatch.setattr(
        "app.agents.tools.cost_extensions.generate_cost_engine",
        fake,
    )

    result = await _call(
        "compare_cost_scenarios",
        {
            "scenarios": [
                {"label": "ok-one", "piece_name": "Good"},
                {"label": "broken", "piece_name": "Broken"},
            ],
        },
        ctx,
    )

    assert result["ok"]
    out = result["output"]
    rows = {r["label"]: r for r in out["scenarios"]}
    assert rows["broken"]["error"] is not None
    assert "LLM timed out" in rows["broken"]["error"]
    assert rows["ok-one"]["summary"]["total_manufacturing_cost_inr"] == 100_000.0
    assert any("broken" in note for note in out["notes"])


# ─────────────────────────────────────────────────────────────────────
# cost_sensitivity — validation envelope
# ─────────────────────────────────────────────────────────────────────


async def test_sensitivity_rejects_unknown_parameter(ctx):
    result = await _call(
        "cost_sensitivity",
        {
            "base": {"label": "base"},
            "parameter": "moon_phase",
            "values": ["full", "new"],
        },
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_sensitivity_rejects_six_values(ctx):
    result = await _call(
        "cost_sensitivity",
        {
            "base": {"label": "base"},
            "parameter": "city",
            "values": ["mumbai", "bangalore", "delhi", "pune", "chennai", "kolkata"],
        },
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_sensitivity_rejects_duplicate_values(ctx):
    result = await _call(
        "cost_sensitivity",
        {
            "base": {"label": "base"},
            "parameter": "city",
            "values": ["mumbai", "Mumbai"],
        },
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


# ─────────────────────────────────────────────────────────────────────
# cost_sensitivity — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_sensitivity_city_axis(monkeypatch, ctx):
    fake = _fake_engine_factory({
        # base has no city → "_no_city_" key, total 100k
        "_no_city_": 100_000.0,
        "mumbai": 120_000.0,
        "bangalore": 105_000.0,
        "delhi": 110_000.0,
    })
    monkeypatch.setattr(
        "app.agents.tools.cost_extensions.generate_cost_engine",
        fake,
    )

    result = await _call(
        "cost_sensitivity",
        {
            "base": {"label": "base"},
            "parameter": "city",
            "values": ["mumbai", "bangalore", "delhi"],
        },
        ctx,
    )

    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["parameter"] == "city"
    assert out["base_summary"]["total_manufacturing_cost_inr"] == 100_000.0
    # Categorical → no elasticity.
    assert out["elasticity_pct_per_unit"] is None
    by_value = {v["parameter_value"]: v for v in out["variants"]}
    assert by_value["mumbai"]["delta_vs_base_pct"] == 20.0
    assert by_value["bangalore"]["delta_vs_base_pct"] == 5.0
    assert by_value["delhi"]["delta_vs_base_pct"] == 10.0


async def test_sensitivity_hardware_piece_count_elasticity(monkeypatch, ctx):
    """Numeric axis → elasticity computed.

    Base = 10 pieces → 100k; vary to 20 → 110k (+10%); 30 → 120k (+20%).
    Elasticity = avg of (10/(20-10), 20/(30-10)) = avg(1.0, 1.0) = 1.0 % per piece.
    """
    fake = _fake_engine_factory({
        "hw=10": 100_000.0,
        "hw=20": 110_000.0,
        "hw=30": 120_000.0,
    })
    monkeypatch.setattr(
        "app.agents.tools.cost_extensions.generate_cost_engine",
        fake,
    )

    result = await _call(
        "cost_sensitivity",
        {
            "base": {"label": "base", "hardware_piece_count": 10},
            "parameter": "hardware_piece_count",
            "values": [20, 30],
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["parameter"] == "hardware_piece_count"
    assert out["elasticity_pct_per_unit"] == 1.0
    by_value = {v["parameter_value"]: v for v in out["variants"]}
    assert by_value[20]["delta_vs_base_pct"] == 10.0
    assert by_value[30]["delta_vs_base_pct"] == 20.0


async def test_sensitivity_base_failure_surfaces_as_tool_error(monkeypatch, ctx):
    """If the base scenario can't price, the whole tool fails cleanly."""
    from app.services.cost_engine_service import CostEngineError

    async def fake(req, *, session, snapshot_id=None, actor_id=None, project_id=None):
        raise CostEngineError("OpenAI key missing")

    monkeypatch.setattr(
        "app.agents.tools.cost_extensions.generate_cost_engine",
        fake,
    )

    result = await _call(
        "cost_sensitivity",
        {
            "base": {"label": "base"},
            "parameter": "city",
            "values": ["mumbai", "delhi"],
        },
        ctx,
    )
    assert result["ok"] is False
    assert "Base scenario could not be priced" in result["error"]["message"]


async def test_sensitivity_partial_variant_failure(monkeypatch, ctx):
    """Base prices fine; one variant raises — base + good variant land,
    bad one carries an error."""
    from app.services.cost_engine_service import CostEngineError

    state = {"calls": 0}

    async def fake(req, *, session, snapshot_id=None, actor_id=None, project_id=None):
        state["calls"] += 1
        if req.city == "mars":
            raise CostEngineError("unknown city")
        total = 100_000.0 if not req.city else 110_000.0
        return {
            "city": req.city or None,
            "knowledge": {"project": {"city_price_index": 1.0}},
            "cost_engine": {
                "total_manufacturing_cost_inr": total,
                "material_cost": {"material_subtotal_inr": total * 0.55},
                "labor_cost": {"labor_subtotal_inr": total * 0.30},
                "overhead": {"overhead_subtotal_inr": total * 0.15},
                "summary": {
                    "material_pct_of_total": 55.0,
                    "labor_pct_of_total": 30.0,
                    "overhead_pct_of_total": 15.0,
                },
            },
            "validation": {},
            "pricing_snapshot_id": f"snap_{state['calls']}",
        }

    monkeypatch.setattr(
        "app.agents.tools.cost_extensions.generate_cost_engine",
        fake,
    )

    result = await _call(
        "cost_sensitivity",
        {
            "base": {"label": "base"},
            "parameter": "city",
            "values": ["mumbai", "mars"],
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    by_value = {v["parameter_value"]: v for v in out["variants"]}
    assert by_value["mars"]["error"] is not None
    assert by_value["mumbai"]["delta_vs_base_pct"] == 10.0
    assert any("mars" in n for n in out["notes"])
