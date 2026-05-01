"""Stage 5B integration tests — RAG end-to-end against real Postgres.

Requires Postgres + pgvector + ``alembic upgrade head``. Tests use
:class:`StubEmbedder` so they don't burn OpenAI calls — but the
DB pgvector storage + cosine search are real.

Coverage:

- Index → search round-trip yields the exact source on a verbatim
  query (stub embedder is identity-stable).
- Re-indexing the same source replaces the prior chunks (idempotency).
- Source-type filter works.
- Owner guard: cross-owner search returns nothing.
- Each per-source-type indexer (design / spec / cost / drawing) writes
  rows with the right metadata.
- Stage 4-style tools (``search_project_memory`` / ``index_project_artefact``
  / ``project_memory_stats``) drive the same path through ``call_tool``.
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
        display_name="S5B test",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _seed_project(session, *, owner_id: str, name: str = "S5B") -> str:
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


def _stub_indexer():
    from app.memory import ProjectMemoryIndexer, StubEmbedder
    return ProjectMemoryIndexer(embedder=StubEmbedder())


def _stub_retriever():
    from app.memory import ProjectMemoryRetriever, StubEmbedder
    return ProjectMemoryRetriever(embedder=StubEmbedder())


# ─────────────────────────────────────────────────────────────────────
# Indexer + retriever round-trip
# ─────────────────────────────────────────────────────────────────────


async def test_index_design_version_then_search_recovers_it(db_session):
    user_id = await _seed_user(db_session, email="rag-rt@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    indexer = _stub_indexer()
    retriever = _stub_retriever()

    graph = {
        "room": {"type": "kitchen",
                 "dimensions": {"length": 5.5, "width": 4.0, "height": 2.7}},
        "objects": [{"id": "o1", "type": "island"}],
        "materials": [{"name": "walnut", "category": "wood"}],
        "style": {"primary": "modern"},
    }
    result = await indexer.index_design_version(
        db_session,
        project_id=project_id,
        owner_id=user_id,
        version_id="v-1",
        version=1,
        graph_data=graph,
        project_name="Test Kitchen",
    )
    assert result.chunk_count >= 1
    assert result.deleted_count == 0
    assert result.embedding_model == "stub"

    # Search using the same text the chunker produced — stub embedder
    # is deterministic, so an exact-substring query still scores well.
    hits = await retriever.search(
        db_session,
        project_id=project_id,
        query="kitchen walnut modern",
        owner_id=user_id,
        top_k=5,
    )
    assert len(hits) >= 1
    top = hits[0]
    assert top.source_type == "design_version"
    assert top.source_id == "v-1"
    assert top.source_version == "v1"
    # Stub embedder yields determinstic but unrelated vectors per
    # input string — score isn't necessarily ≥ 0.9. We just check
    # the row came back at all.
    assert -1.0 <= top.score <= 1.0


async def test_reindex_replaces_prior_chunks(db_session):
    user_id = await _seed_user(db_session, email="rag-idem@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    indexer = _stub_indexer()

    # First index — 1+ chunks.
    r1 = await indexer.index_design_version(
        db_session,
        project_id=project_id, owner_id=user_id,
        version_id="v-1", version=1,
        graph_data={"room": {"type": "kitchen"}, "objects": [{"type": "stool"}]},
    )
    assert r1.deleted_count == 0
    first_count = r1.chunk_count

    # Re-index the same source with new content — should delete prior
    # then insert fresh.
    r2 = await indexer.index_design_version(
        db_session,
        project_id=project_id, owner_id=user_id,
        version_id="v-1", version=1,
        graph_data={"room": {"type": "bedroom"}, "objects": []},
    )
    assert r2.deleted_count == first_count
    assert r2.chunk_count >= 1


async def test_search_source_type_filter_excludes_other_kinds(db_session):
    user_id = await _seed_user(db_session, email="rag-filter@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    indexer = _stub_indexer()
    retriever = _stub_retriever()

    # One design version + one cost engine row.
    await indexer.index_design_version(
        db_session, project_id=project_id, owner_id=user_id,
        version_id="v-1", version=1,
        graph_data={"room": {"type": "kitchen"}, "style": {"primary": "modern"}},
    )
    await indexer.index_cost_engine(
        db_session, project_id=project_id, owner_id=user_id,
        snapshot_id="snap-1",
        cost_engine={
            "header": {"piece_name": "kitchen island"},
            "total_manufacturing_cost_inr": 100000,
            "summary": {},
            "material_cost": {"material_subtotal_inr": 60000},
            "labor_cost": {"labor_subtotal_inr": 25000},
            "overhead": {"overhead_subtotal_inr": 15000},
        },
    )

    # Filter to design only → cost rows excluded.
    hits = await retriever.search(
        db_session, project_id=project_id,
        query="anything", owner_id=user_id,
        source_type="design_version", top_k=10,
    )
    assert all(h.source_type == "design_version" for h in hits)

    # Filter to cost only.
    hits_cost = await retriever.search(
        db_session, project_id=project_id,
        query="anything", owner_id=user_id,
        source_type="cost_engine", top_k=10,
    )
    assert all(h.source_type == "cost_engine" for h in hits_cost)


async def test_owner_filter_isolates_users(db_session):
    """Two users, same project_id — search with owner_id A must not
    see B's rows. (In practice projects are owner-scoped, but this
    guards against stale FKs / shared-tenant scenarios.)"""
    a_id = await _seed_user(db_session, email="rag-a@example.com")
    b_id = await _seed_user(db_session, email="rag-b@example.com")
    project_id = await _seed_project(db_session, owner_id=a_id)

    indexer = _stub_indexer()
    retriever = _stub_retriever()

    # A indexes a row.
    await indexer.index_design_version(
        db_session, project_id=project_id, owner_id=a_id,
        version_id="v-1", version=1,
        graph_data={"room": {"type": "kitchen"}},
    )

    # B searches the same project_id — finds nothing because owner
    # filter excludes A's rows.
    hits = await retriever.search(
        db_session, project_id=project_id,
        query="kitchen", owner_id=b_id,
        top_k=5,
    )
    assert hits == []


# ─────────────────────────────────────────────────────────────────────
# Per-source-type indexers
# ─────────────────────────────────────────────────────────────────────


async def test_index_spec_bundle_records_source_type(db_session):
    user_id = await _seed_user(db_session, email="rag-spec@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    indexer = _stub_indexer()
    bundle = {
        "meta": {"theme": "luxe", "room_type": "lounge"},
        "material": {"primary": "marble"},
        "manufacturing": {"woodworking": "..."},
        "mep": {"hvac": "split"},
        "cost": {"total_inr": 500000},
    }
    result = await indexer.index_spec_bundle(
        db_session,
        project_id=project_id, owner_id=user_id,
        version_id="v-2", version=2, bundle=bundle,
    )
    assert result.source_type == "spec_bundle"
    assert result.source_version == "v2"
    assert result.chunk_count >= 1


async def test_index_drawing_uses_kind_as_source_type(db_session):
    user_id = await _seed_user(db_session, email="rag-draw@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    indexer = _stub_indexer()
    spec = {"scale": "1:50", "key_dimensions": [{"label": "L", "value_m": 5}]}
    result = await indexer.index_drawing_or_diagram(
        db_session,
        project_id=project_id, owner_id=user_id,
        kind="plan_view", artefact_id="draw-1", spec=spec,
        title="Kitchen — Plan", theme="modern",
    )
    assert result.source_type == "plan_view"


# ─────────────────────────────────────────────────────────────────────
# Agent tools end-to-end
# ─────────────────────────────────────────────────────────────────────


async def test_search_project_memory_tool_requires_project(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    ctx = ToolContext(
        session=db_session, actor_id="someone", project_id=None,
        request_id="t5b",
    )
    result = await call_tool(
        "search_project_memory",
        {"query": "anything"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "project" in result["error"]["message"].lower()


async def test_search_project_memory_tool_requires_actor(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="rag-noactor@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=None, project_id=project_id,
        request_id="t5b-noactor",
    )
    result = await call_tool(
        "search_project_memory",
        {"query": "x"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "actor" in result["error"]["message"].lower()


async def test_index_project_artefact_tool_then_search_e2e(
    db_session, monkeypatch,
):
    """Drive both tools through ``call_tool`` so the dispatcher
    semantics (input validation, error envelope, audit) are exercised."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.memory import StubEmbedder

    ensure_tools_registered()

    # Force the stub embedder for both tools.
    monkeypatch.setattr(
        "app.memory.embeddings.get_embedder",
        lambda: StubEmbedder(),
    )
    # The tools call ``ProjectMemoryIndexer()`` / ``ProjectMemoryRetriever()``
    # which in turn call ``get_embedder`` from the same module. Patch the
    # symbol the indexer/retriever modules already imported.
    monkeypatch.setattr(
        "app.memory.indexer.get_embedder",
        lambda: StubEmbedder(),
    )
    monkeypatch.setattr(
        "app.memory.retriever.get_embedder",
        lambda: StubEmbedder(),
    )

    user_id = await _seed_user(db_session, email="rag-e2e@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="t5b-e2e",
    )

    # 1. Index a design version via the tool.
    idx = await call_tool(
        "index_project_artefact",
        {
            "kind": "design_version",
            "source_id": "v-77",
            "source_version": "v77",
            "body": {
                "room": {"type": "kitchen",
                         "dimensions": {"length": 5, "width": 4, "height": 2.7}},
                "objects": [{"id": "o1", "type": "island"}],
                "style": {"primary": "modern"},
            },
            "title": "E2E Kitchen",
        },
        ctx, registry=REGISTRY,
    )
    assert idx["ok"], idx.get("error")
    assert idx["output"]["chunk_count"] >= 1
    assert idx["output"]["source_type"] == "design_version"
    assert idx["output"]["embedder"] == "stub"

    # 2. Stats reflects the new chunks.
    stats = await call_tool(
        "project_memory_stats", {}, ctx, registry=REGISTRY,
    )
    assert stats["ok"]
    assert stats["output"]["chunk_count"] >= 1

    # 3. Search returns the indexed chunk.
    search = await call_tool(
        "search_project_memory",
        {"query": "kitchen modern island", "top_k": 3},
        ctx, registry=REGISTRY,
    )
    assert search["ok"], search.get("error")
    assert search["output"]["returned_count"] >= 1
    top = search["output"]["hits"][0]
    assert top["source_type"] == "design_version"
    assert top["source_id"] == "v-77"
    # Score comes back in [-1, 1] as documented.
    assert -1.0 <= top["score"] <= 1.0


async def test_search_project_memory_empty_query_rejected(db_session):
    """Schema-layer validation: query has min_length=2."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="rag-empty@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="t5b-empty",
    )
    result = await call_tool(
        "search_project_memory",
        {"query": "x"},  # 1 char — under the 2-char min
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_index_project_artefact_unknown_kind_surfaces_tool_error(
    db_session, monkeypatch,
):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.memory import StubEmbedder

    ensure_tools_registered()
    monkeypatch.setattr(
        "app.memory.indexer.get_embedder", lambda: StubEmbedder(),
    )

    user_id = await _seed_user(db_session, email="rag-bad@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="t5b-bad",
    )
    result = await call_tool(
        "index_project_artefact",
        {
            "kind": "phantom_kind",
            "source_id": "x-1",
            "body": {},
        },
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "phantom_kind" in result["error"]["message"]
