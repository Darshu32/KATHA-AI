"""Stage 5D unit tests — async dispatch path + Celery task wiring.

These tests don't run a real Celery worker — they monkey-patch
:func:`dispatch_index_design_version` so the test can verify the
inputs the dispatcher would have sent. The actual indexing path
under eager Celery is exercised in the integration tests.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.auto_index import (
    AutoIndexResult,
    auto_index_design_version,
)


# ─────────────────────────────────────────────────────────────────────
# AutoIndexResult.from_queued
# ─────────────────────────────────────────────────────────────────────


def test_from_queued_with_task_id_marks_queued():
    out = AutoIndexResult.from_queued("task-abc")
    assert out.indexed is False
    assert out.skipped_reason == "queued"
    assert out.task_id == "task-abc"
    assert out.error is None
    assert out.chunk_count == 0


def test_from_queued_with_no_task_id_marks_dispatch_failed():
    out = AutoIndexResult.from_queued(None)
    assert out.indexed is False
    assert out.skipped_reason == "dispatch_failed"
    assert out.task_id is None
    assert out.error and "broker" in out.error


# ─────────────────────────────────────────────────────────────────────
# Mode selection
# ─────────────────────────────────────────────────────────────────────


async def test_async_mode_explicit_true_dispatches_to_celery(monkeypatch):
    """When async_mode=True the inline indexer must NOT be invoked;
    the dispatcher receives the same args."""
    captured: dict[str, Any] = {}

    def fake_dispatch(**kwargs):
        captured.update(kwargs)
        return "task-fake-1"

    monkeypatch.setattr(
        "app.workers.memory_tasks.dispatch_index_design_version",
        fake_dispatch,
    )

    class _MustNotBeCalledIndexer:
        async def index_design_version(self, *args, **kwargs):
            raise AssertionError(
                "indexer.index_design_version called in async_mode=True"
            )

    out = await auto_index_design_version(
        session=object(),
        project_id="p1",
        owner_id="u1",
        version_id="v-async-1",
        version=2,
        graph_data={"room": {"type": "kitchen"}},
        project_name="Async Test",
        async_mode=True,
        indexer=_MustNotBeCalledIndexer(),
    )

    assert out.skipped_reason == "queued"
    assert out.task_id == "task-fake-1"
    assert out.chunk_count == 0
    assert out.indexed is False
    # Wiring sanity — dispatcher saw all our args.
    assert captured["project_id"] == "p1"
    assert captured["owner_id"] == "u1"
    assert captured["version_id"] == "v-async-1"
    assert captured["version"] == 2
    assert captured["graph_data"]["room"]["type"] == "kitchen"
    assert captured["project_name"] == "Async Test"


async def test_async_mode_explicit_false_runs_inline(monkeypatch):
    """async_mode=False overrides the global flag and forces inline."""
    monkeypatch.setenv("ASYNC_INDEXING_ENABLED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    class _RecordingIndexer:
        called = False

        async def index_design_version(self, *args, **kwargs):
            type(self).called = True
            from app.memory import IndexResult
            return IndexResult(
                project_id="p1", source_type="design_version",
                source_id="v-1", source_version="v1",
                chunk_count=2, deleted_count=0,
                embedding_model="stub",
            )

    indexer = _RecordingIndexer()

    out = await auto_index_design_version(
        session=object(),
        project_id="p1", owner_id="u1",
        version_id="v-1", version=1,
        graph_data={"x": "y"},
        async_mode=False,
        indexer=indexer,
    )
    assert out.indexed is True
    assert out.chunk_count == 2
    assert _RecordingIndexer.called is True
    assert out.task_id is None


async def test_async_mode_default_consults_settings_flag(monkeypatch):
    """When async_mode=None, the settings flag decides."""
    monkeypatch.setenv("ASYNC_INDEXING_ENABLED", "true")
    from app.config import get_settings
    get_settings.cache_clear()

    captured = {}

    def fake_dispatch(**kwargs):
        captured["called"] = True
        return "task-from-flag"

    monkeypatch.setattr(
        "app.workers.memory_tasks.dispatch_index_design_version",
        fake_dispatch,
    )

    out = await auto_index_design_version(
        session=object(),
        project_id="p1", owner_id="u1",
        version_id="v-1", version=1,
        graph_data={},
        async_mode=None,
    )
    assert captured.get("called") is True
    assert out.skipped_reason == "queued"
    assert out.task_id == "task-from-flag"


async def test_async_mode_dispatch_returns_none_marks_dispatch_failed(monkeypatch):
    """If the dispatcher returns None (broker outage), surface
    ``dispatch_failed`` rather than silent loss."""
    def fake_dispatch(**kwargs):
        return None

    monkeypatch.setattr(
        "app.workers.memory_tasks.dispatch_index_design_version",
        fake_dispatch,
    )

    out = await auto_index_design_version(
        session=object(),
        project_id="p1", owner_id="u1",
        version_id="v-1", version=1,
        graph_data={},
        async_mode=True,
    )
    assert out.skipped_reason == "dispatch_failed"
    assert out.task_id is None
    assert out.error and "broker" in out.error


# ─────────────────────────────────────────────────────────────────────
# Tool registry shape — Stage 5D adds 1 tool
# ─────────────────────────────────────────────────────────────────────


def test_prune_project_memory_registered_with_audit_target():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("prune_project_memory")
    assert spec.audit_target_type == "project_memory"
    schema = spec.input_schema()
    props = schema.get("properties", {})
    assert "keep_latest_versions" in props
    assert props["keep_latest_versions"].get("minimum") == 1
    assert props["keep_latest_versions"].get("maximum") == 200
    assert props["keep_latest_versions"].get("default") == 10


def test_total_tool_count_at_least_60():
    """Stage 4 (55) + 5 recall (1) + 5B memory (3) + 5D prune (1) = 60."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    assert len(REGISTRY.names()) >= 60


def test_pipeline_tools_output_includes_index_task_id():
    """Stage 5D extends GenerationOutput with index_task_id."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    for name in ("generate_initial_design", "apply_theme", "edit_design_object"):
        spec = REGISTRY.get(name)
        output_schema = spec.output_model.model_json_schema()
        props = output_schema.get("properties", {})
        assert "index_task_id" in props, f"{name}: missing index_task_id field"
        assert "index_skipped_reason" in props
