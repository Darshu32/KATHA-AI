"""Stage 15 — knowledge migration unit tests.

Pattern C ("DB-first, Python-fallback") validation:

1. ``inject_knowledge`` is now ``async`` and accepts an optional session.
2. Without a session, it returns the legacy Python-literal bundle
   (backward compatible — no breakage during migration).
3. With a session that has DB rows, the codes block carries the DB
   values + a ``_provenance.source = "db"`` marker.
4. With a session that lacks the row (DB lookup returns None), the
   codes block falls back to Python literals AND still works without
   raising.
5. ``build_prompt_preamble`` requires a pre-computed bundle now (the
   old single-arg form is removed).

All tests run in-process — no real DB. We mock the codes_lookup
module to simulate DB hits / misses.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.models.brief import (
    BriefThemeEnum,
    ClientRequirements,
    ClimaticZoneEnum,
    DesignBriefOut,
    ProjectTypeEnum,
    ProjectTypeSection,
    RegulatoryContext,
    SpaceParameters,
    SpaceDimensions,
    SiteConditions,
    ThemeSection,
)


def _sample_brief() -> DesignBriefOut:
    return DesignBriefOut(
        brief_id="bf_test123",
        status="accepted",
        project_type=ProjectTypeSection(
            type=ProjectTypeEnum.RESIDENTIAL, sub_type="3bhk_apartment"
        ),
        theme=ThemeSection(theme=BriefThemeEnum.CONTEMPORARY),
        space=SpaceParameters(
            dimensions=SpaceDimensions(length=10, width=6, height=3, unit="m"),
            site_conditions=SiteConditions(orientation="north"),
        ),
        requirements=ClientRequirements(
            functional_needs=["open kitchen"],
            aesthetic_preferences=["warm wood"],
            budget=2_500_000,
            currency="INR",
            timeline_weeks=12,
        ),
        regulatory=RegulatoryContext(
            country="IN",
            state="Maharashtra",
            city="Mumbai",
            building_codes=["NBC-2016"],
            climatic_zone=ClimaticZoneEnum.WARM_HUMID,
        ),
        warnings=[],
    )


# ─────────────────────────────────────────────────────────────────────
# Backward compatibility
# ─────────────────────────────────────────────────────────────────────


def test_inject_knowledge_is_async():
    """Stage 15 makes the function async — inspect.iscoroutinefunction."""
    import inspect
    from app.services.knowledge_injector import inject_knowledge
    assert inspect.iscoroutinefunction(inject_knowledge)


def test_inject_knowledge_works_without_session():
    """Pre-Stage-15 callers (no session) still get a valid bundle from
    Python literals. The codes block ``_provenance.source`` reads
    ``python_literal``."""
    from app.services.knowledge_injector import inject_knowledge

    bundle = asyncio.run(inject_knowledge(_sample_brief()))
    assert bundle["brief_id"] == "bf_test123"
    assert bundle["segment"] == "residential"
    assert "building_codes" in bundle
    assert bundle["building_codes"]["_provenance"]["source"] == "python_literal"
    # Sanity: known NBC value flows through.
    assert bundle["building_codes"]["habitable_min_area_m2"] == 9.5


# ─────────────────────────────────────────────────────────────────────
# DB-first path
# ─────────────────────────────────────────────────────────────────────


def test_inject_knowledge_uses_db_when_session_provided():
    """When a session is passed AND the DB lookup returns a row, the
    DB value flows through and ``_provenance.source = "db"``."""
    from app.services.knowledge_injector import inject_knowledge

    fake_nbc_min = {
        "habitable_room_min_area_m2": 11.0,   # different from Python literal (9.5)
        "habitable_room_min_short_side_m": 2.5,
        "habitable_room_min_height_m": 2.85,
        "kitchen_min_area_m2": 5.0,
        "bathroom_min_area_m2": 2.0,
    }
    fake_egress = {
        "max_travel_residential_m": 25,
        "max_travel_commercial_m": 30,
        "min_exit_count_over_500m2_floor": 2,
        "fire_door_rating_min_hr": 2,
        "corridor_min_width_mm": 1500,
    }

    async def fake_get_code_data(session, *, slug, jurisdiction="india_nbc"):
        return {
            "minimum_room_dimensions": fake_nbc_min,
            "ventilation": {"openable_area_percent_floor": 12.0},
            "natural_light": {"glazing_percent_floor": 18.0},
            "fire_egress": fake_egress,
        }.get(slug)

    async def fake_get_acc(session):
        return {"ramp_slope_max": "1:12 (DB)"}

    async def fake_get_ecbc(session):
        return {
            "wall_u_value_w_m2k": 0.30,
            "roof_u_value_w_m2k": 0.20,
            "wwr_max": 0.35,
            "notes": "DB ECBC",
        }

    sentinel_session = object()
    with patch(
        "app.services.knowledge_injector.codes_lookup.get_code_data",
        new=fake_get_code_data,
    ), patch(
        "app.services.knowledge_injector.codes_lookup.get_accessibility",
        new=fake_get_acc,
    ), patch(
        "app.services.knowledge_injector.codes_lookup.get_ecbc_targets",
        new=fake_get_ecbc,
    ):
        bundle = asyncio.run(
            inject_knowledge(_sample_brief(), session=sentinel_session)
        )

    cd = bundle["building_codes"]
    assert cd["_provenance"]["source"] == "db"
    assert cd["habitable_min_area_m2"] == 11.0           # DB value, not 9.5
    assert cd["habitable_min_height_m"] == 2.85          # DB value
    assert cd["fire_egress"]["max_travel_distance_m"] == 25  # DB value
    assert cd["accessibility"]["ramp_slope_max"] == "1:12 (DB)"
    assert cd["energy_envelope_ecbc"]["wall_u_value_w_m2k"] == 0.30
    assert cd["energy_envelope_ecbc"]["applies_when"] == "DB ECBC"


# ─────────────────────────────────────────────────────────────────────
# DB miss → Python fallback
# ─────────────────────────────────────────────────────────────────────


def test_inject_knowledge_falls_back_when_db_returns_none():
    """When the session is passed but the DB lookups all return None
    (fresh DB, no seed yet), we silently fall back to Python literals
    and still produce a valid bundle. Provenance still says ``db``
    because we tried — but the values are the legacy ones."""
    from app.services.knowledge_injector import inject_knowledge

    async def empty(*args, **kwargs):
        return None

    sentinel_session = object()
    with patch(
        "app.services.knowledge_injector.codes_lookup.get_code_data", new=empty
    ), patch(
        "app.services.knowledge_injector.codes_lookup.get_accessibility", new=empty
    ), patch(
        "app.services.knowledge_injector.codes_lookup.get_ecbc_targets", new=empty
    ):
        bundle = asyncio.run(
            inject_knowledge(_sample_brief(), session=sentinel_session)
        )

    cd = bundle["building_codes"]
    # DB was attempted (provenance says so) but values are Python-literal.
    assert cd["_provenance"]["source"] == "db"
    assert cd["habitable_min_area_m2"] == 9.5    # Python literal


# ─────────────────────────────────────────────────────────────────────
# build_prompt_preamble contract
# ─────────────────────────────────────────────────────────────────────


def test_build_prompt_preamble_requires_bundle():
    """Stage 15 removed the single-arg form because computing the
    bundle is async. Calling without a bundle should raise TypeError."""
    from app.services.knowledge_injector import build_prompt_preamble

    with pytest.raises(TypeError):
        build_prompt_preamble(_sample_brief())  # type: ignore[call-arg]


def test_build_prompt_preamble_runs_with_precomputed_bundle():
    from app.services.knowledge_injector import (
        build_prompt_preamble,
        inject_knowledge,
    )

    bundle = asyncio.run(inject_knowledge(_sample_brief()))
    text = build_prompt_preamble(_sample_brief(), bundle)
    assert isinstance(text, str)
    assert "Input-stage knowledge" in text
    assert "residential" in text
    assert "Codes:" in text


# ─────────────────────────────────────────────────────────────────────
# Bundle shape stability — preserved across the migration
# ─────────────────────────────────────────────────────────────────────


def test_bundle_shape_unchanged():
    """The bundle's top-level keys must be unchanged so any downstream
    consumer (LLM prompt builder, tests, generation pipeline) keeps
    working. Stage 15 only added a ``_provenance`` sub-key INSIDE
    ``building_codes`` — non-breaking."""
    from app.services.knowledge_injector import inject_knowledge

    bundle = asyncio.run(inject_knowledge(_sample_brief()))
    expected_top_keys = {
        "brief_id",
        "segment",
        "theme",
        "footprint_area_m2",
        "standard_dimensions",
        "building_codes",
        "climate",
        "regional_materials",
        "structural",
        "mep",
        "room_program_reference",
    }
    assert expected_top_keys.issubset(set(bundle.keys()))
