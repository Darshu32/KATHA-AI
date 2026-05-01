"""Stage 9 integration tests — end-to-end haptic export.

Requires Postgres + ``alembic upgrade head`` (so the Stage 9
catalog seed is loaded). These tests:

- Build a real :class:`DesignGraphVersion` for a real project.
- Drive :func:`build_haptic_payload` directly to assert the BRD
  §Layer 7 four-bucket payload shape on real data.
- Drive :func:`export_haptic_payload` through ``call_tool`` to
  exercise the full agent path (input validation → exporter →
  audit log).
- Cover the BRD fallback policy (unmapped material → ``generic``).
- Cover the project-scope guard (cross-project access errors out).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


async def _seed_user(session, *, email: str) -> str:
    from app.models.orm import User

    user = User(
        email=email,
        hashed_password="x",
        display_name="S9 test",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _seed_project(session, *, owner_id: str, name: str = "S9") -> str:
    from app.models.orm import Project

    project = Project(
        owner_id=owner_id,
        name=name,
        description="",
        status="draft",
        latest_version=0,
    )
    session.add(project)
    await session.flush()
    return project.id


def _sample_graph() -> dict:
    """Three objects, two materials (one mapped, one falling back),
    one room. Exercises every BRD bucket simultaneously."""
    return {
        "rooms": [{
            "id": "room-1",
            "name": "living",
            "dimensions": {"width": 5.0, "depth": 4.0, "height": 2.7},
        }],
        "objects": [
            {
                "id": "chair-1",
                "type": "chair",
                "material": "walnut",
                "dimensions": {"width": 0.5, "depth": 0.5, "height": 0.9},
                "position": {"x": 1.0, "y": 0.0, "z": 1.0},
            },
            {
                "id": "table-1",
                "type": "dining_table",
                "material": "oak",
                "dimensions": {"width": 1.8, "depth": 0.9, "height": 0.75},
                "position": {"x": 2.0, "y": 0.0, "z": 2.0},
            },
            {
                "id": "sofa-1",
                "type": "sofa",
                "material": "exotic_unicorn_velvet",  # unmapped → generic
                "dimensions": {"width": 2.2, "depth": 0.9, "height": 0.85},
                "position": {"x": 3.0, "y": 0.0, "z": 1.0},
            },
        ],
    }


async def _seed_graph_version(
    session, *, project_id: str, version: int = 1,
    graph: dict | None = None,
) -> str:
    from app.models.orm import DesignGraphVersion

    row = DesignGraphVersion(
        project_id=project_id,
        version=version,
        change_type="initial",
        change_summary="haptic test seed",
        changed_object_ids=[],
        graph_data=graph if graph is not None else _sample_graph(),
    )
    session.add(row)
    await session.flush()
    return row.id


# ─────────────────────────────────────────────────────────────────────
# Direct exporter — payload structure follows BRD §Layer 7
# ─────────────────────────────────────────────────────────────────────


async def test_export_payload_has_all_four_brd_buckets(db_session):
    """BRD §Layer 7 lists four data buckets. Every export must
    expose every bucket."""
    from app.haptic.exporter import build_haptic_payload
    from app.models.orm import DesignGraphVersion

    user_id = await _seed_user(db_session, email="s9-buckets@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    version_id = await _seed_graph_version(
        db_session, project_id=project_id,
    )

    row = (await db_session.get(DesignGraphVersion, version_id))
    export = await build_haptic_payload(db_session, graph_version=row)
    payload = export.payload

    # Bucket 1 — Dimension data.
    assert "dimensions" in payload
    assert "rooms" in payload["dimensions"]
    assert "objects" in payload["dimensions"]
    assert payload["dimensions"]["rooms"][0]["width_mm"] == 5000.0

    # Bucket 2 — Material haptic properties.
    assert "materials" in payload
    assert len(payload["materials"]) >= 2
    keys = {m["key"] for m in payload["materials"]}
    assert "walnut" in keys

    # Bucket 3 — Interaction parameters.
    assert "interactions" in payload
    chair_interactions = [
        i for i in payload["interactions"] if i["object_type"] == "chair"
    ]
    assert chair_interactions, "chair has a dimension rule, must surface"
    assert "seat_height" in chair_interactions[0]["adjustable_axes"]

    # Bucket 4 — Feedback loops.
    assert "feedback_loops" in payload
    assert len(payload["feedback_loops"]) >= 1
    rule_keys = {r["rule_key"] for r in payload["feedback_loops"]}
    assert "chair.seat_height.cost_per_cm" in rule_keys


async def test_export_envelope_has_versioning_stamps(db_session):
    """Hardware drivers depend on schema_version + catalog_version."""
    from app.haptic import HAPTIC_CATALOG_VERSION, HAPTIC_SCHEMA_VERSION
    from app.haptic.exporter import build_haptic_payload
    from app.models.orm import DesignGraphVersion

    user_id = await _seed_user(db_session, email="s9-version@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    version_id = await _seed_graph_version(
        db_session, project_id=project_id,
    )

    row = await db_session.get(DesignGraphVersion, version_id)
    payload = (await build_haptic_payload(db_session, graph_version=row)).payload

    assert payload["schema_version"] == HAPTIC_SCHEMA_VERSION
    assert payload["catalog_version"] == HAPTIC_CATALOG_VERSION
    assert payload["graph_version_id"] == version_id
    assert payload["project_id"] == project_id
    assert payload["design_version"] == 1
    assert payload["generated_at"]  # ISO timestamp


async def test_export_walnut_anchored_to_brd_temperature(db_session):
    """BRD: walnut 28 °C. The seed migration should land it on the
    payload exactly."""
    from app.haptic.exporter import build_haptic_payload
    from app.models.orm import DesignGraphVersion

    user_id = await _seed_user(db_session, email="s9-walnut@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    version_id = await _seed_graph_version(
        db_session, project_id=project_id,
    )

    row = await db_session.get(DesignGraphVersion, version_id)
    payload = (await build_haptic_payload(db_session, graph_version=row)).payload

    walnut = next(
        (m for m in payload["materials"] if m["key"] == "walnut"), None,
    )
    assert walnut is not None
    assert walnut["thermal"]["temperature_celsius"] == 28.0
    assert walnut["friction"]["coefficient"] == 0.35


# ─────────────────────────────────────────────────────────────────────
# BRD fallback policy — unmapped material → generic profile
# ─────────────────────────────────────────────────────────────────────


async def test_unmapped_material_falls_back_to_generic(db_session):
    """BRD §Layer 7: material with no profile → 'generic' fallback,
    flagged in validation block."""
    from app.haptic.exporter import build_haptic_payload
    from app.models.orm import DesignGraphVersion

    user_id = await _seed_user(db_session, email="s9-fallback@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    version_id = await _seed_graph_version(
        db_session, project_id=project_id,
    )

    row = await db_session.get(DesignGraphVersion, version_id)
    export = await build_haptic_payload(db_session, graph_version=row)

    assert "exotic_unicorn_velvet" in export.coverage.fallback_materials
    assert export.coverage.all_materials_mapped is False

    # The fallback material's payload entry should still be addressable
    # by the requested key, with a fallback marker on the texture.
    velvet = next(
        (m for m in export.payload["materials"]
         if m["key"] == "exotic_unicorn_velvet"),
        None,
    )
    assert velvet is not None
    assert velvet["texture"].get("fallback_for") == "exotic_unicorn_velvet"


async def test_validation_block_lists_known_objects_too(db_session):
    """Sample graph has chair / dining_table / sofa — all three are
    seeded in the catalog. None should appear in
    ``missing_object_types``."""
    from app.haptic.exporter import build_haptic_payload
    from app.models.orm import DesignGraphVersion

    user_id = await _seed_user(db_session, email="s9-objects@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    version_id = await _seed_graph_version(
        db_session, project_id=project_id,
    )

    row = await db_session.get(DesignGraphVersion, version_id)
    payload = (await build_haptic_payload(db_session, graph_version=row)).payload

    assert payload["validation"]["missing_object_types"] == []


# ─────────────────────────────────────────────────────────────────────
# Tool path — call_tool drives the same export
# ─────────────────────────────────────────────────────────────────────


async def test_export_tool_picks_latest_version_when_unspecified(db_session):
    """Tool with no input → latest version of the current project."""
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s9-tool@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    await _seed_graph_version(
        db_session, project_id=project_id, version=1,
    )
    v2_id = await _seed_graph_version(
        db_session, project_id=project_id, version=2,
    )

    ctx = ToolContext(
        session=db_session,
        actor_id=user_id,
        project_id=project_id,
        request_id="req-s9-tool",
    )
    result = await call_tool("export_haptic_payload", {}, ctx)

    assert result["ok"] is True
    output = result["output"]
    assert output["envelope"]["graph_version_id"] == v2_id
    assert output["envelope"]["design_version"] == 2
    assert output["summary"]["material_count"] >= 1


async def test_export_tool_rejects_cross_project_access(db_session):
    """Architect A can't export Architect B's design — same shape
    of refusal whether the row exists or not (no existence leak)."""
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    a_id = await _seed_user(db_session, email="s9-a@example.com")
    b_id = await _seed_user(db_session, email="s9-b@example.com")
    a_project = await _seed_project(db_session, owner_id=a_id, name="A")
    b_project = await _seed_project(db_session, owner_id=b_id, name="B")
    b_version = await _seed_graph_version(
        db_session, project_id=b_project, version=1,
    )

    # A scopes to A's project, asks for B's version → must error.
    ctx = ToolContext(
        session=db_session,
        actor_id=a_id,
        project_id=a_project,
        request_id="req-s9-cross",
    )
    result = await call_tool(
        "export_haptic_payload",
        {"graph_version_id": b_version},
        ctx,
    )
    assert result["ok"] is False
    assert "No design-graph version found" in result["error"]["message"]


async def test_export_tool_requires_project_scope(db_session):
    """Without ``ctx.project_id`` the tool refuses outright."""
    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s9-noproject@example.com")

    ctx = ToolContext(
        session=db_session,
        actor_id=user_id,
        project_id=None,
        request_id="req-s9-no-proj",
    )
    result = await call_tool("export_haptic_payload", {}, ctx)
    assert result["ok"] is False
    assert "project scope" in result["error"]["message"].lower()


async def test_export_tool_audit_target_haptic_export(db_session):
    """Successful export writes an AuditEvent with target_type
    haptic_export."""
    from sqlalchemy import select

    from app.agents.tool import ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.db import AuditEvent

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s9-audit@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    await _seed_graph_version(
        db_session, project_id=project_id, version=1,
    )

    ctx = ToolContext(
        session=db_session,
        actor_id=user_id,
        project_id=project_id,
        request_id="req-s9-audit",
    )
    result = await call_tool("export_haptic_payload", {}, ctx)
    assert result["ok"] is True

    rows = (
        await db_session.execute(
            select(AuditEvent).where(
                AuditEvent.target_type == "haptic_export",
                AuditEvent.request_id == "req-s9-audit",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].action == "tool_call"
