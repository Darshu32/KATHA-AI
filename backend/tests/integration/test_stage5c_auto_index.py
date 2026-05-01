"""Stage 5C integration tests — pipeline tools auto-index into
project memory.

We monkey-patch the orchestrator pipeline functions (so no LLM call
goes out) and the embedder (StubEmbedder), then drive
``generate_initial_design`` / ``apply_theme`` / ``edit_design_object``
via ``call_tool`` and confirm:

- The new ``GenerationOutput`` carries ``indexed=True`` /
  ``index_chunk_count > 0`` / ``index_skipped_reason=None``.
- Real ``project_memory_chunks`` rows are written for each version.
- ``search_project_memory`` finds the freshly auto-indexed content.
- An indexer crash is caught — the parent generation still succeeds
  with ``indexed=False`` + ``index_skipped_reason='error'``.
- Missing ``actor_id`` short-circuits ``index_skipped_reason='no_owner_id'``
  without calling the indexer.

Real Postgres + pgvector are required (the test marker is
``integration`` so the whole module is skipped without
``KATHA_INTEGRATION_TESTS=1``).
"""

from __future__ import annotations

from typing import Any

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
        display_name="S5C test",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _seed_project(session, *, owner_id: str, name: str = "S5C") -> str:
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


def _stub_graph(theme: str = "modern") -> dict[str, Any]:
    return {
        "room": {
            "type": "kitchen",
            "dimensions": {"length": 5.0, "width": 4.0, "height": 2.7},
        },
        "objects": [
            {"id": "obj-1", "type": "island"},
            {"id": "obj-2", "type": "stool"},
        ],
        "materials": [{"name": "walnut", "category": "wood"}],
        "style": {"primary": theme},
    }


def _patch_stub_embedder(monkeypatch):
    """Force StubEmbedder everywhere the indexer / retriever look it up."""
    from app.memory import StubEmbedder

    monkeypatch.setattr(
        "app.memory.embeddings.get_embedder", lambda: StubEmbedder(),
    )
    monkeypatch.setattr(
        "app.memory.indexer.get_embedder", lambda: StubEmbedder(),
    )
    monkeypatch.setattr(
        "app.memory.retriever.get_embedder", lambda: StubEmbedder(),
    )


# ─────────────────────────────────────────────────────────────────────
# Happy-path: each of the 3 write tools auto-indexes
# ─────────────────────────────────────────────────────────────────────


async def test_generate_initial_design_auto_indexes(monkeypatch, db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.project_memory import ProjectMemoryRepository

    _patch_stub_embedder(monkeypatch)
    ensure_tools_registered()

    # Stub the AI orchestrator pipeline.
    async def fake_initial(*, db, project_id, prompt, room_type, style, **kwargs):
        return {
            "project_id": project_id,
            "version": 1,
            "version_id": "v-init-1",
            "graph_data": _stub_graph(theme=style),
            "estimate": {"total": 200000, "currency": "INR"},
            "status": "completed",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_initial_generation", fake_initial,
    )

    user_id = await _seed_user(db_session, email="s5c-init@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="s5c-init",
    )

    result = await call_tool(
        "generate_initial_design",
        {"prompt": "design a modern kitchen for me", "style": "modern"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["indexed"] is True
    assert out["index_chunk_count"] >= 1
    assert out["index_skipped_reason"] is None
    # The chunks really exist.
    count = await ProjectMemoryRepository.count_for_project(
        db_session, project_id=project_id,
    )
    assert count >= 1


async def test_apply_theme_auto_indexes(monkeypatch, db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.project_memory import ProjectMemoryRepository

    _patch_stub_embedder(monkeypatch)
    ensure_tools_registered()

    async def fake_theme(*, db, project_id, new_style, preserve_layout):
        return {
            "project_id": project_id,
            "version": 2,
            "version_id": "v-theme-1",
            "graph_data": _stub_graph(theme=new_style),
            "estimate": {"total": 250000},
            "status": "completed",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_theme_switch", fake_theme,
    )

    user_id = await _seed_user(db_session, email="s5c-theme@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="s5c-theme",
    )

    result = await call_tool(
        "apply_theme",
        {"new_style": "scandinavian"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["change_type"] == "theme_switch"
    assert out["indexed"] is True
    assert out["index_chunk_count"] >= 1
    assert out["index_skipped_reason"] is None
    count = await ProjectMemoryRepository.count_for_project(
        db_session, project_id=project_id,
    )
    assert count >= 1


async def test_edit_design_object_auto_indexes(monkeypatch, db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    _patch_stub_embedder(monkeypatch)
    ensure_tools_registered()

    async def fake_edit(*, db, project_id, object_id, edit_prompt):
        return {
            "project_id": project_id,
            "version": 3,
            "version_id": "v-edit-1",
            "graph_data": _stub_graph(),
            "estimate": {},
            "changed_objects": [object_id],
            "status": "completed",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_local_edit", fake_edit,
    )

    user_id = await _seed_user(db_session, email="s5c-edit@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="s5c-edit",
    )

    result = await call_tool(
        "edit_design_object",
        {"object_id": "obj-1", "edit_prompt": "make this 1.8 m long"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["change_type"] == "prompt_edit"
    assert out["indexed"] is True
    assert out["index_chunk_count"] >= 1


# ─────────────────────────────────────────────────────────────────────
# Auto-indexed content is searchable
# ─────────────────────────────────────────────────────────────────────


async def test_auto_indexed_version_is_searchable(monkeypatch, db_session):
    """Generate, then immediately search — the new version's content
    should come back as a hit."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    _patch_stub_embedder(monkeypatch)
    ensure_tools_registered()

    async def fake_initial(**kwargs):
        return {
            "project_id": kwargs["project_id"],
            "version": 1,
            "version_id": "v-search-1",
            "graph_data": _stub_graph(theme="industrial"),
            "estimate": {},
            "status": "completed",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_initial_generation", fake_initial,
    )

    user_id = await _seed_user(db_session, email="s5c-search@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="s5c-search",
    )

    # 1. Generate (auto-indexes).
    gen = await call_tool(
        "generate_initial_design",
        {"prompt": "industrial kitchen with island", "style": "industrial"},
        ctx, registry=REGISTRY,
    )
    assert gen["ok"], gen.get("error")
    assert gen["output"]["indexed"] is True

    # 2. Search — the freshly indexed chunk is in scope.
    search = await call_tool(
        "search_project_memory",
        {"query": "industrial kitchen island", "top_k": 5},
        ctx, registry=REGISTRY,
    )
    assert search["ok"], search.get("error")
    out = search["output"]
    assert out["returned_count"] >= 1
    # At least one hit should be the design_version we just indexed.
    assert any(
        h["source_type"] == "design_version" and h["source_id"] == "v-search-1"
        for h in out["hits"]
    )


# ─────────────────────────────────────────────────────────────────────
# Failure modes — generation still succeeds
# ─────────────────────────────────────────────────────────────────────


async def test_indexer_failure_does_not_break_generation(monkeypatch, db_session):
    """Embedder explodes; the design generation must still return ok=True
    with indexed=False + skipped_reason='error'."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()

    async def fake_initial(**kwargs):
        return {
            "project_id": kwargs["project_id"],
            "version": 1,
            "version_id": "v-fail-1",
            "graph_data": _stub_graph(),
            "estimate": {},
            "status": "completed",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_initial_generation", fake_initial,
    )

    # Replace the indexer at the auto_index module's lookup point so
    # *any* embedding attempt explodes.
    class _ExplodingIndexer:
        async def index_design_version(self, *args, **kwargs):
            raise RuntimeError("embedder unavailable")

    # The auto_index helper instantiates ProjectMemoryIndexer() lazily
    # via `indexer or ProjectMemoryIndexer()`. We patch the constructor
    # so the helper always receives the exploder.
    monkeypatch.setattr(
        "app.agents.auto_index.ProjectMemoryIndexer",
        lambda: _ExplodingIndexer(),
    )

    user_id = await _seed_user(db_session, email="s5c-fail@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="s5c-fail",
    )

    result = await call_tool(
        "generate_initial_design",
        {"prompt": "any prompt that is long enough"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")  # parent still succeeded
    out = result["output"]
    assert out["version"] == 1
    assert out["indexed"] is False
    assert out["index_skipped_reason"] == "error"
    assert out["index_chunk_count"] == 0


async def test_missing_owner_id_skips_index_without_error(
    monkeypatch, db_session,
):
    """When ctx has no actor_id the indexer must short-circuit with
    skipped_reason='no_owner_id' — no exception, no DB call."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    _patch_stub_embedder(monkeypatch)
    ensure_tools_registered()

    async def fake_initial(**kwargs):
        return {
            "project_id": kwargs["project_id"],
            "version": 1,
            "version_id": "v-noowner-1",
            "graph_data": _stub_graph(),
            "estimate": {},
            "status": "completed",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_initial_generation", fake_initial,
    )

    # Seed a project (using a real user) but build the ctx with
    # actor_id=None to simulate an anonymous / system run.
    user_id = await _seed_user(db_session, email="s5c-noowner@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=None, project_id=project_id,
        request_id="s5c-noowner",
    )

    result = await call_tool(
        "generate_initial_design",
        {"prompt": "anonymous design generation prompt"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["indexed"] is False
    assert out["index_skipped_reason"] == "no_owner_id"
    assert out["index_chunk_count"] == 0
