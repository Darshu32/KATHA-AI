"""Stage 5D integration tests — async indexing + eviction.

Covers two pieces:

1. **Eager Celery** — flip ``celery_app.conf.task_always_eager`` so the
   Celery task body runs synchronously in the test process. This
   exercises the full async path (auto_index → dispatch →
   memory_tasks task body → indexer.index_design_version → DB) end
   to end without spinning up a real worker.

2. **Pruning** — populate a project with several design-version
   chunks at known version numbers, then prune; verify the right
   rows survived.

Real Postgres + pgvector required. Stub embedder used everywhere.
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
        display_name="S5D test",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _seed_project(session, *, owner_id: str, name: str = "S5D") -> str:
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


def _force_stub_embedder(monkeypatch):
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
# Async dispatch — wiring through pipeline tool with stubbed dispatcher
# ─────────────────────────────────────────────────────────────────────


async def test_async_mode_sets_task_id_and_skips_inline_indexing(
    monkeypatch, db_session,
):
    """Drive ``generate_initial_design`` with the global flag on. The
    pipeline tool should dispatch to (mocked) Celery and return
    ``index_skipped_reason='queued'`` + a task id, with no chunks
    written inline."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.repositories.project_memory import ProjectMemoryRepository

    monkeypatch.setenv("ASYNC_INDEXING_ENABLED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    captured = {}

    def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return "task-pipeline-1"

    monkeypatch.setattr(
        "app.workers.memory_tasks.dispatch_index_design_version",
        fake_dispatch,
    )

    async def fake_initial(*, db, project_id, prompt, room_type, style, **kwargs):
        return {
            "project_id": project_id,
            "version": 1,
            "version_id": "v-async-pipe-1",
            "graph_data": {
                "room": {"type": "kitchen"},
                "style": {"primary": style},
            },
            "estimate": {},
            "status": "completed",
        }

    monkeypatch.setattr(
        "app.agents.tools.pipeline._run_initial_generation", fake_initial,
    )

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s5d-async@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="s5d-async",
    )

    result = await call_tool(
        "generate_initial_design",
        {"prompt": "design a modern kitchen async path"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["indexed"] is False
    assert out["index_skipped_reason"] == "queued"
    assert out["index_task_id"] == "task-pipeline-1"
    assert out["index_chunk_count"] == 0
    assert captured["project_id"] == project_id
    assert captured["owner_id"] == user_id
    assert captured["version_id"] == "v-async-pipe-1"

    # No chunks were written inline — the worker would do that.
    count = await ProjectMemoryRepository.count_for_project(
        db_session, project_id=project_id,
    )
    assert count == 0


async def test_eager_celery_task_actually_writes_chunks(monkeypatch, db_session):
    """Run the Celery task body directly — same code the worker
    executes — and verify chunks land in the DB.

    This skips the broker dispatch and just calls the task function
    so the test exercises the real indexer + DB path."""
    from app.repositories.project_memory import ProjectMemoryRepository
    from app.workers.memory_tasks import index_design_version_task

    _force_stub_embedder(monkeypatch)

    # Patch async_session_factory inside the task so it uses our
    # transactional fixture session, not a fresh real connection.
    # We do this by replacing the lookup inside the task's `_run`.
    # Easiest: monkey-patch ``async_session_factory`` to return a
    # context manager that yields our existing session.
    class _FakeSessionCtx:
        def __init__(self, session):
            self._s = session

        async def __aenter__(self):
            return self._s

        async def __aexit__(self, *exc):
            return False

    def fake_factory():
        return _FakeSessionCtx(db_session)

    monkeypatch.setattr(
        "app.database.async_session_factory", fake_factory,
    )

    # The task ``commit``s — that would close our outer rollback. Stub
    # commit so our test fixture cleans up normally.
    async def _noop():
        return None
    monkeypatch.setattr(db_session, "commit", _noop)

    user_id = await _seed_user(db_session, email="s5d-eager@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)

    # Run the task function directly (Celery's own machinery isn't
    # involved — we're testing the task body's correctness).
    # ``bind=True`` puts ``self`` as first arg; pass a dummy.
    class _DummyTask:
        request = type("R", (), {"id": "test-task-1"})()
    fn = index_design_version_task.__wrapped__  # the underlying callable

    result = fn(
        _DummyTask(),
        project_id=project_id,
        owner_id=user_id,
        version_id="v-eager-1",
        version=1,
        graph_data={
            "room": {"type": "bedroom",
                     "dimensions": {"length": 4, "width": 3, "height": 2.7}},
            "style": {"primary": "modern"},
        },
        project_name="Eager Test",
    )

    assert result["ok"] is True
    assert result["chunk_count"] >= 1
    assert result["embedder"] == "stub"

    # Chunks are really in the DB.
    count = await ProjectMemoryRepository.count_for_project(
        db_session, project_id=project_id,
    )
    assert count >= 1


# ─────────────────────────────────────────────────────────────────────
# Pruning
# ─────────────────────────────────────────────────────────────────────


async def test_prune_keeps_latest_versions_drops_older(monkeypatch, db_session):
    """Index 6 design versions, prune to keep 3; the 3 oldest go away."""
    from app.memory import ProjectMemoryIndexer, StubEmbedder
    from app.repositories.project_memory import ProjectMemoryRepository

    user_id = await _seed_user(db_session, email="s5d-prune@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    indexer = ProjectMemoryIndexer(embedder=StubEmbedder())

    for v in range(1, 7):  # versions 1..6
        await indexer.index_design_version(
            db_session,
            project_id=project_id,
            owner_id=user_id,
            version_id=f"v-{v}",
            version=v,
            graph_data={"room": {"type": f"room_v{v}"}},
        )

    pre_count = await ProjectMemoryRepository.count_for_project(
        db_session, project_id=project_id,
    )
    assert pre_count >= 6  # at least one chunk per version

    removed = await ProjectMemoryRepository.prune_old_design_versions(
        db_session, project_id=project_id, keep_latest=3,
    )
    assert removed >= 3  # versions 1, 2, 3 dropped

    # The chunks for v4, v5, v6 are still there.
    for kept in (4, 5, 6):
        rows = await ProjectMemoryRepository.list_for_source(
            db_session, project_id=project_id,
            source_type="design_version", source_id=f"v-{kept}",
        )
        assert len(rows) >= 1, f"v{kept} should not have been pruned"

    # The chunks for v1, v2, v3 are gone.
    for dropped in (1, 2, 3):
        rows = await ProjectMemoryRepository.list_for_source(
            db_session, project_id=project_id,
            source_type="design_version", source_id=f"v-{dropped}",
        )
        assert rows == [], f"v{dropped} should have been pruned"


async def test_prune_preserves_other_source_types(monkeypatch, db_session):
    """Pruning only touches ``design_version`` rows — spec / cost /
    drawing chunks must survive."""
    from app.memory import ProjectMemoryIndexer, StubEmbedder
    from app.repositories.project_memory import ProjectMemoryRepository

    user_id = await _seed_user(db_session, email="s5d-prune-mixed@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    indexer = ProjectMemoryIndexer(embedder=StubEmbedder())

    # 3 design versions + 1 cost engine + 1 drawing.
    for v in range(1, 4):
        await indexer.index_design_version(
            db_session, project_id=project_id, owner_id=user_id,
            version_id=f"dv-{v}", version=v,
            graph_data={"room": {"type": "kitchen"}},
        )
    await indexer.index_cost_engine(
        db_session, project_id=project_id, owner_id=user_id,
        snapshot_id="snap-1",
        cost_engine={
            "header": {"piece_name": "island"},
            "total_manufacturing_cost_inr": 100000,
            "summary": {},
            "material_cost": {"material_subtotal_inr": 60000},
            "labor_cost": {"labor_subtotal_inr": 25000},
            "overhead": {"overhead_subtotal_inr": 15000},
        },
    )
    await indexer.index_drawing_or_diagram(
        db_session, project_id=project_id, owner_id=user_id,
        kind="plan_view", artefact_id="dr-1",
        spec={"scale": "1:50"},
    )

    # Prune to 1 latest design version → drops dv-1, dv-2.
    removed = await ProjectMemoryRepository.prune_old_design_versions(
        db_session, project_id=project_id, keep_latest=1,
    )
    assert removed >= 2

    # The cost engine + drawing chunks are untouched.
    cost_rows = await ProjectMemoryRepository.list_for_source(
        db_session, project_id=project_id,
        source_type="cost_engine", source_id="snap-1",
    )
    assert len(cost_rows) >= 1
    plan_rows = await ProjectMemoryRepository.list_for_source(
        db_session, project_id=project_id,
        source_type="plan_view", source_id="dr-1",
    )
    assert len(plan_rows) >= 1
    # Latest design version (dv-3) still there.
    dv3 = await ProjectMemoryRepository.list_for_source(
        db_session, project_id=project_id,
        source_type="design_version", source_id="dv-3",
    )
    assert len(dv3) >= 1


async def test_prune_with_keep_zero_is_noop(db_session):
    """Defence: ``keep_latest <= 0`` must NOT truncate the project."""
    from app.memory import ProjectMemoryIndexer, StubEmbedder
    from app.repositories.project_memory import ProjectMemoryRepository

    user_id = await _seed_user(db_session, email="s5d-prune-zero@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    indexer = ProjectMemoryIndexer(embedder=StubEmbedder())
    await indexer.index_design_version(
        db_session, project_id=project_id, owner_id=user_id,
        version_id="dv-1", version=1, graph_data={"room": {"type": "x"}},
    )

    pre = await ProjectMemoryRepository.count_for_project(
        db_session, project_id=project_id,
    )
    removed = await ProjectMemoryRepository.prune_old_design_versions(
        db_session, project_id=project_id, keep_latest=0,
    )
    assert removed == 0
    post = await ProjectMemoryRepository.count_for_project(
        db_session, project_id=project_id,
    )
    assert post == pre


# ─────────────────────────────────────────────────────────────────────
# prune_project_memory tool — end to end
# ─────────────────────────────────────────────────────────────────────


async def test_prune_tool_through_call_tool(monkeypatch, db_session):
    """Drive ``prune_project_memory`` via the dispatcher and verify
    the output shape."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.memory import ProjectMemoryIndexer, StubEmbedder

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s5d-prune-tool@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    indexer = ProjectMemoryIndexer(embedder=StubEmbedder())
    for v in range(1, 5):
        await indexer.index_design_version(
            db_session, project_id=project_id, owner_id=user_id,
            version_id=f"dv-{v}", version=v,
            graph_data={"room": {"type": "kitchen"}},
        )

    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="s5d-prune-tool",
    )
    result = await call_tool(
        "prune_project_memory",
        {"keep_latest_versions": 2},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["project_id"] == project_id
    assert out["keep_latest_versions"] == 2
    assert out["removed_count"] >= 2  # dropped at least dv-1, dv-2
    assert out["chunks_remaining"] >= 1


async def test_prune_tool_requires_project(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    ctx = ToolContext(
        session=db_session, actor_id="someone",
        project_id=None, request_id="s5d-prune-noproj",
    )
    result = await call_tool(
        "prune_project_memory",
        {"keep_latest_versions": 5},
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "project" in result["error"]["message"].lower()


async def test_prune_tool_rejects_zero(db_session):
    """``keep_latest_versions`` ge=1 — zero must fail validation."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s5d-prune-zero-tool@example.com")
    project_id = await _seed_project(db_session, owner_id=user_id)
    ctx = ToolContext(
        session=db_session, actor_id=user_id, project_id=project_id,
        request_id="s5d-prune-zero-tool",
    )
    result = await call_tool(
        "prune_project_memory",
        {"keep_latest_versions": 0},
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"
