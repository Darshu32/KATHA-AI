"""Stage 8 integration tests — decisions + profiles + privacy guard.

Real Postgres. The Celery extraction tasks are exercised by calling
their underlying ``_extract_*_async`` helpers directly so we don't
need a worker or broker.

Coverage:

- Decisions: record + recall round-trip via the agent tools.
- Search: query filters across title / summary / rationale.
- Owner-guarded client lookup: cross-architect reads return ToolError.
- Architect fingerprint: extractor → DB → tool reads it back.
- Privacy: ``learning_enabled=False`` skips the architect extractor
  and surfaces ``learning_enabled=False`` on the tool output.
- Resume context: composite read returns versions + decisions + chunk
  count.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


async def _seed_user(session, *, email: str, learning_enabled: bool = True) -> str:
    from app.models.orm import User

    u = User(
        email=email,
        hashed_password="x",
        display_name="S8 test",
        is_active=True,
        learning_enabled=learning_enabled,
    )
    session.add(u)
    await session.flush()
    return u.id


async def _seed_project(session, *, owner_id: str, name: str = "S8",
                         client_id: str | None = None) -> str:
    from app.models.orm import Project

    p = Project(
        owner_id=owner_id,
        client_id=client_id,
        name=name,
        description="",
        status="draft",
        latest_version=0,
    )
    session.add(p)
    await session.flush()
    return p.id


async def _seed_design_version(session, *, project_id: str, version: int,
                                graph_data: dict) -> str:
    from app.models.orm import DesignGraphVersion

    v = DesignGraphVersion(
        project_id=project_id,
        version=version,
        change_type="initial",
        change_summary=f"v{version}",
        graph_data=graph_data,
    )
    session.add(v)
    await session.flush()
    return v.id


async def _seed_client(session, *, primary_user_id: str, name: str = "Acme") -> str:
    from app.models.orm import Client

    c = Client(
        primary_user_id=primary_user_id,
        name=name,
        contact_email="acme@example.com",
        notes="",
        status="active",
    )
    session.add(c)
    await session.flush()
    return c.id


# ─────────────────────────────────────────────────────────────────────
# Decisions — record + recall via agent tools
# ─────────────────────────────────────────────────────────────────────


async def test_record_and_recall_decision_roundtrip(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s8-rt@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    ctx = ToolContext(
        session=db_session,
        actor_id=user_id,
        project_id=project_id,
        request_id="s8-rt",
    )

    record = await call_tool(
        "record_design_decision",
        {
            "title": "Picked walnut for island",
            "summary": "Island in walnut after comparing oak.",
            "rationale": "Client prefers darker tones; durability.",
            "category": "material",
            "version": 1,
            "rejected_alternatives": [
                {"option": "oak", "reason_rejected": "too light"},
            ],
            "sources": ["tool_call:cost_engine_abc"],
            "tags": ["client_preference"],
        },
        ctx, registry=REGISTRY,
    )
    assert record["ok"], record.get("error")
    decision_id = record["output"]["decision"]["id"]

    recall = await call_tool(
        "recall_design_decisions",
        {"category": "material"},
        ctx, registry=REGISTRY,
    )
    assert recall["ok"]
    decisions = recall["output"]["decisions"]
    assert len(decisions) == 1
    assert decisions[0]["id"] == decision_id
    assert decisions[0]["title"] == "Picked walnut for island"
    assert recall["output"]["total_for_project"] == 1


async def test_recall_search_query_matches_rationale(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s8-search@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="s8-search",
    )

    # 3 decisions; one mentions "teak" only in rationale.
    for title, summary, rationale, cat in [
        ("Skylight", "Add skylight in living room", "Daylighting needs", "lighting"),
        ("Bedside lights", "Wall sconces over bed", "Soft reading light", "lighting"),
        ("Floor", "Solid wood floor", "Picked teak after walnut sample", "material"),
    ]:
        await call_tool(
            "record_design_decision",
            {"title": title, "summary": summary, "rationale": rationale, "category": cat},
            ctx, registry=REGISTRY,
        )

    result = await call_tool(
        "recall_design_decisions",
        {"query": "teak"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"]
    decisions = result["output"]["decisions"]
    # Only the third decision mentions teak.
    assert len(decisions) == 1
    assert decisions[0]["title"] == "Floor"


async def test_record_decision_unknown_category_rejected(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s8-bad-cat@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="s8-bad-cat",
    )
    result = await call_tool(
        "record_design_decision",
        {
            "title": "Something",
            "summary": "Something happened.",
            "category": "phantom_category",
        },
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "phantom_category" in result["error"]["message"]


async def test_decision_tools_require_project(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s8-noproj@example.com")
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=None,
        request_id="s8-noproj",
    )
    result = await call_tool(
        "record_design_decision",
        {"title": "x", "summary": "abcdefghij"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "project" in result["error"]["message"].lower()


# ─────────────────────────────────────────────────────────────────────
# Architect fingerprint — extractor → DB → tool
# ─────────────────────────────────────────────────────────────────────


async def test_architect_fingerprint_extractor_writes_profile(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.profiles import extract_architect_fingerprint
    from app.repositories.architects import ArchitectProfileRepository

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s8-arch-fp@example.com")
    p1 = await _seed_project(db_session, owner_id=user_id, name="P1")
    p2 = await _seed_project(db_session, owner_id=user_id, name="P2")
    await _seed_design_version(
        db_session, project_id=p1, version=1,
        graph_data={
            "room": {"type": "kitchen", "dimensions": {"length": 5, "width": 4, "height": 2.7}},
            "materials": [{"name": "walnut"}],
            "style": {"primary": "modern"},
        },
    )
    await _seed_design_version(
        db_session, project_id=p2, version=1,
        graph_data={
            "room": {"type": "bedroom", "dimensions": {"length": 4, "width": 3.5, "height": 2.7}},
            "materials": [{"name": "walnut"}, {"name": "brass"}],
            "style": {"primary": "modern"},
        },
    )

    fp = extract_architect_fingerprint(
        user_id=user_id,
        design_graphs=[
            {
                "room": {"type": "kitchen", "dimensions": {"length": 5, "width": 4, "height": 2.7}},
                "materials": [{"name": "walnut"}],
                "style": {"primary": "modern"},
            },
            {
                "room": {"type": "bedroom", "dimensions": {"length": 4, "width": 3.5, "height": 2.7}},
                "materials": [{"name": "walnut"}, {"name": "brass"}],
                "style": {"primary": "modern"},
            },
        ],
    )
    await ArchitectProfileRepository.upsert(
        db_session,
        user_id=fp.user_id,
        project_count=fp.project_count,
        preferred_themes=fp.preferred_themes,
        preferred_materials=fp.preferred_materials,
        preferred_palette_hexes=fp.preferred_palette_hexes,
        typical_room_dimensions_m=fp.typical_room_dimensions_m,
        tool_usage=fp.tool_usage,
        last_project_at=None,
    )

    ctx = ToolContext(
        session=db_session, actor_id=user_id, request_id="s8-arch-fp",
    )
    result = await call_tool(
        "get_architect_fingerprint", {}, ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["learning_enabled"] is True
    assert out["profile_exists"] is True
    assert out["project_count"] == 2
    by_theme = {t["name"]: t for t in out["preferred_themes"]}
    assert by_theme["modern"]["count"] == 2
    assert "walnut" in {m["name"] for m in out["preferred_materials"]}


async def test_architect_extractor_skips_when_learning_disabled(db_session):
    """The Celery task body short-circuits when learning is off."""
    from app.workers.memory_extraction import _extract_architect_async

    user_id = await _seed_user(
        db_session, email="s8-learning-off@example.com",
        learning_enabled=False,
    )
    # Even with projects + graphs, the extractor must skip.
    p = await _seed_project(db_session, owner_id=user_id)
    await _seed_design_version(
        db_session, project_id=p, version=1,
        graph_data={
            "style": {"primary": "modern"},
            "room": {"type": "kitchen", "dimensions": {"length": 4, "width": 3, "height": 2.7}},
        },
    )

    # The async session inside the task body uses async_session_factory,
    # not our test fixture session. Patch it to return our session.
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _yield_test_session():
        # Don't commit — let the test fixture's transaction handle it.
        yield db_session

    import app.workers.memory_extraction as m
    orig = m.__dict__.get("async_session_factory")  # may not be in dict
    # Use monkey-patch via the import inside _extract_architect_async.
    import app.database
    orig_factory = app.database.async_session_factory
    app.database.async_session_factory = _yield_test_session  # type: ignore[assignment]
    try:
        result = await _extract_architect_async(user_id)
    finally:
        app.database.async_session_factory = orig_factory  # type: ignore[assignment]

    assert result["ok"] is True
    assert result["skipped_reason"] == "learning_disabled"


async def test_get_architect_fingerprint_no_profile_yet(db_session):
    """Fresh user — no extractor has run yet. Tool returns
    profile_exists=False, learning_enabled True."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s8-fresh@example.com")
    ctx = ToolContext(
        session=db_session, actor_id=user_id, request_id="s8-fresh",
    )
    result = await call_tool(
        "get_architect_fingerprint", {}, ctx, registry=REGISTRY,
    )
    assert result["ok"]
    out = result["output"]
    assert out["learning_enabled"] is True
    assert out["profile_exists"] is False
    assert out["project_count"] == 0


async def test_get_architect_fingerprint_surfaces_learning_disabled(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(
        db_session, email="s8-learning-flag@example.com",
        learning_enabled=False,
    )
    ctx = ToolContext(
        session=db_session, actor_id=user_id, request_id="s8-flag",
    )
    result = await call_tool(
        "get_architect_fingerprint", {}, ctx, registry=REGISTRY,
    )
    assert result["ok"]
    assert result["output"]["learning_enabled"] is False


# ─────────────────────────────────────────────────────────────────────
# Client profile
# ─────────────────────────────────────────────────────────────────────


async def test_get_client_profile_owner_guard(db_session):
    """Architect A creates a client; architect B can't read it."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    a_id = await _seed_user(db_session, email="s8-cli-a@example.com")
    b_id = await _seed_user(db_session, email="s8-cli-b@example.com")
    client_id = await _seed_client(db_session, primary_user_id=a_id)

    # B tries to read A's client.
    ctx = ToolContext(
        session=db_session, actor_id=b_id, request_id="s8-cross-cli",
    )
    result = await call_tool(
        "get_client_profile",
        {"client_id": client_id},
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "not found" in result["error"]["message"].lower()


async def test_get_client_profile_no_profile_yet(db_session):
    """Client exists, no profile extraction has run yet."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s8-cli-fresh@example.com")
    client_id = await _seed_client(db_session, primary_user_id=user_id, name="Acme Co")

    ctx = ToolContext(
        session=db_session, actor_id=user_id, request_id="s8-cli-fresh",
    )
    result = await call_tool(
        "get_client_profile",
        {"client_id": client_id},
        ctx, registry=REGISTRY,
    )
    assert result["ok"]
    out = result["output"]
    assert out["name"] == "Acme Co"
    assert out["profile_exists"] is False


# ─────────────────────────────────────────────────────────────────────
# resume_project_context
# ─────────────────────────────────────────────────────────────────────


async def test_resume_project_context_returns_versions_decisions_count(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.decisions import DesignDecisionRepository

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s8-resume@example.com")
    client_id = await _seed_client(db_session, primary_user_id=user_id, name="Wing Studio")
    project_id = await _seed_project(
        db_session, owner_id=user_id, name="Resume project", client_id=client_id,
    )
    # Two versions.
    await _seed_design_version(
        db_session, project_id=project_id, version=1,
        graph_data={"style": {"primary": "modern"}},
    )
    await _seed_design_version(
        db_session, project_id=project_id, version=2,
        graph_data={"style": {"primary": "modern"}},
    )
    # Three decisions.
    for i in range(3):
        await DesignDecisionRepository.record(
            db_session,
            project_id=project_id,
            actor_id=user_id,
            title=f"Decision {i}",
            summary="...",
            category="material",
        )

    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="s8-resume",
    )
    result = await call_tool(
        "resume_project_context",
        {"decision_limit": 5, "version_limit": 5},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["project_name"] == "Resume project"
    assert out["client_name"] == "Wing Studio"
    assert out["client_id"] == client_id
    assert out["decision_count"] == 3
    assert len(out["recent_decisions"]) == 3
    assert len(out["recent_versions"]) == 2
    # Versions surface newest first.
    assert out["recent_versions"][0]["version"] == 2
    assert out["recent_versions"][1]["version"] == 1


async def test_resume_project_context_requires_project(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s8-resume-noproj@example.com")
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=None,
        request_id="s8-resume-noproj",
    )
    result = await call_tool(
        "resume_project_context", {}, ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "project" in result["error"]["message"].lower()
