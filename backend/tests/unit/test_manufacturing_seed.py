"""Stage 3D manufacturing seed-extraction tests."""

from __future__ import annotations

import pytest

from app.knowledge import manufacturing as mfg_kb


@pytest.fixture(scope="module")
def seed():
    from app.services.standards.manufacturing_seed import (
        build_manufacturing_seed_rows,
    )
    return build_manufacturing_seed_rows()


# ─────────────────────────────────────────────────────────────────────
# Row hygiene
# ─────────────────────────────────────────────────────────────────────


def test_every_row_has_manufacturing_category(seed):
    for row in seed:
        assert row["category"] == "manufacturing"
        assert row["jurisdiction"] == "india_nbc"
        assert row["subcategory"] in {
            "tolerance",
            "joinery",
            "welding",
            "lead_time",
            "moq",
            "qa_gate",
            "process_spec",
        }
        assert row["source"].startswith("seed:manufacturing")


def test_every_row_has_required_fields(seed):
    for row in seed:
        for key in (
            "id",
            "slug",
            "category",
            "subcategory",
            "display_name",
            "data",
            "source",
            "source_doc",
        ):
            assert key in row, f"row missing {key!r}"


# ─────────────────────────────────────────────────────────────────────
# Tolerance coverage
# ─────────────────────────────────────────────────────────────────────


def test_every_tolerance_seeded(seed):
    by_slug = {r["slug"]: r for r in seed}
    for key in mfg_kb.TOLERANCES.keys():
        slug = f"mfg_tolerance_{key}"
        assert slug in by_slug
        legacy = mfg_kb.TOLERANCES[key]
        assert by_slug[slug]["data"]["tolerance_plus_minus_mm"] == float(legacy["+-mm"])


def test_precision_requirements_seeded(seed):
    row = next((r for r in seed if r["slug"] == "mfg_precision_requirements"), None)
    assert row is not None
    assert row["data"] == mfg_kb.PRECISION_REQUIREMENTS_BRD


# ─────────────────────────────────────────────────────────────────────
# Joinery
# ─────────────────────────────────────────────────────────────────────


def test_every_joinery_type_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for key in mfg_kb.JOINERY.keys():
        assert f"mfg_joinery_{key}" in slugs


def test_joinery_data_matches_legacy(seed):
    by_slug = {r["slug"]: r for r in seed}
    for key, legacy in mfg_kb.JOINERY.items():
        row = by_slug[f"mfg_joinery_{key}"]
        for k, v in legacy.items():
            assert row["data"][k] == v


# ─────────────────────────────────────────────────────────────────────
# Welding
# ─────────────────────────────────────────────────────────────────────


def test_every_welding_method_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for key in mfg_kb.WELDING.keys():
        assert f"mfg_welding_{key}" in slugs


def test_bending_rule_seeded(seed):
    row = next((r for r in seed if r["slug"] == "mfg_bending_rule"), None)
    assert row is not None
    assert row["data"] == mfg_kb.BENDING_RULE


# ─────────────────────────────────────────────────────────────────────
# Lead times + MOQ
# ─────────────────────────────────────────────────────────────────────


def test_every_lead_time_seeded(seed):
    by_slug = {r["slug"]: r for r in seed}
    for key, (low, high) in mfg_kb.LEAD_TIMES_WEEKS.items():
        slug = f"mfg_lead_time_{key}"
        assert slug in by_slug
        assert by_slug[slug]["data"]["weeks_low"] == int(low)
        assert by_slug[slug]["data"]["weeks_high"] == int(high)


def test_every_moq_seeded(seed):
    by_slug = {r["slug"]: r for r in seed}
    for key, value in mfg_kb.MOQ.items():
        slug = f"mfg_moq_{key}"
        assert slug in by_slug
        assert by_slug[slug]["data"]["min_order_qty"] == int(value)


# ─────────────────────────────────────────────────────────────────────
# QA gates (5 BRD-mandated stages)
# ─────────────────────────────────────────────────────────────────────


def test_all_five_qa_gates_seeded(seed):
    qa_rows = [r for r in seed if r["subcategory"] == "qa_gate"]
    assert len(qa_rows) == 5
    stages = {r["data"]["stage"] for r in qa_rows}
    assert stages == set(mfg_kb.QUALITY_GATES_BRD_SPEC)


def test_qa_gate_brd_spec_canonical_order_seeded(seed):
    row = next(
        (r for r in seed if r["slug"] == "mfg_quality_gates_brd_spec"), None
    )
    assert row is not None
    assert row["data"]["stages"] == list(mfg_kb.QUALITY_GATES_BRD_SPEC)


# ─────────────────────────────────────────────────────────────────────
# Process specs
# ─────────────────────────────────────────────────────────────────────


def test_woodworking_process_spec_seeded(seed):
    row = next(
        (r for r in seed if r["slug"] == "mfg_process_spec_woodworking"), None
    )
    assert row is not None
    assert "lead_time_weeks" in row["data"]
    # Tuples should have been coerced to lists.
    assert isinstance(row["data"]["lead_time_weeks"], list)


def test_metal_fab_process_spec_seeded(seed):
    row = next(
        (r for r in seed if r["slug"] == "mfg_process_spec_metal_fabrication"),
        None,
    )
    assert row is not None
    assert isinstance(row["data"]["structural_welding"], list)
    assert "GMAW_MIG" in row["data"]["structural_welding"]


def test_upholstery_specs_seeded(seed):
    slugs = {r["slug"] for r in seed}
    assert "mfg_process_spec_upholstery_assembly" in slugs
    assert "mfg_process_spec_upholstery_detail" in slugs


# ─────────────────────────────────────────────────────────────────────
# Counts
# ─────────────────────────────────────────────────────────────────────


def test_subcategory_counts_match_legacy(seed):
    counts: dict[str, int] = {}
    for row in seed:
        counts[row["subcategory"]] = counts.get(row["subcategory"], 0) + 1
    assert counts["tolerance"] == len(mfg_kb.TOLERANCES)
    assert counts["joinery"] == len(mfg_kb.JOINERY)
    assert counts["welding"] == len(mfg_kb.WELDING)
    assert counts["lead_time"] == len(mfg_kb.LEAD_TIMES_WEEKS)
    assert counts["moq"] == len(mfg_kb.MOQ)
    assert counts["qa_gate"] == len(mfg_kb.QA_GATES)
    # process_spec includes precision_requirements + bending_rule + 4
    # process specs + 1 quality_gates_brd_spec rollup = 7.
    assert counts["process_spec"] == 7
