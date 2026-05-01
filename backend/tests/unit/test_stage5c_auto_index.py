"""Stage 5C unit tests — best-effort auto-indexing semantics.

We exercise :func:`auto_index_design_version` in isolation with a
fake :class:`ProjectMemoryIndexer` so:

- Happy path returns ``indexed=True`` with the chunk count.
- Missing project / owner / version_id short-circuits with the
  matching ``skipped_reason`` (no DB call attempted).
- An indexer that raises is caught and returned as
  ``skipped_reason='error'`` with the exception message.
- An indexer returning zero chunks (empty source) reports
  ``indexed=False`` with ``skipped_reason='no_content'``.
- A passed-in custom indexer is used (no implicit
  ``ProjectMemoryIndexer()`` instantiation).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.agents.auto_index import (
    AutoIndexResult,
    auto_index_design_version,
)
from app.memory import IndexResult


# ─────────────────────────────────────────────────────────────────────
# Fake indexer
# ─────────────────────────────────────────────────────────────────────


class _FakeIndexer:
    """Records the inputs it was called with; programmable result."""

    def __init__(self, *, raises: BaseException | None = None,
                 result: IndexResult | None = None) -> None:
        self._raises = raises
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def index_design_version(self, session, **kwargs):
        self.calls.append({"session": session, **kwargs})
        if self._raises is not None:
            raise self._raises
        return self._result or IndexResult(
            project_id=kwargs.get("project_id") or "",
            source_type="design_version",
            source_id=str(kwargs.get("version_id") or ""),
            source_version=f"v{kwargs.get('version') or 0}",
            chunk_count=2,
            deleted_count=0,
            embedding_model="stub",
        )


# ─────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────


async def test_auto_index_happy_path_returns_indexed_true():
    fake = _FakeIndexer()
    out = await auto_index_design_version(
        session=object(),
        project_id="p1",
        owner_id="u1",
        version_id="v-1",
        version=1,
        graph_data={"room": {"type": "kitchen"}},
        project_name="Test",
        indexer=fake,
    )
    assert isinstance(out, AutoIndexResult)
    assert out.indexed is True
    assert out.chunk_count == 2
    assert out.skipped_reason is None
    assert out.embedder == "stub"
    assert out.error is None
    # The fake was actually invoked with our scope.
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["project_id"] == "p1"
    assert call["owner_id"] == "u1"
    assert call["version_id"] == "v-1"
    assert call["version"] == 1


# ─────────────────────────────────────────────────────────────────────
# Missing scope short-circuits — no indexer call
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("missing,expected_reason", [
    ("project_id", "no_project_id"),
    ("owner_id", "no_owner_id"),
    ("version_id", "no_version_id"),
])
async def test_missing_scope_skipped_without_calling_indexer(missing, expected_reason):
    fake = _FakeIndexer()
    kwargs: dict[str, Any] = {
        "session": object(),
        "project_id": "p",
        "owner_id": "u",
        "version_id": "v",
        "version": 1,
        "graph_data": {},
        "indexer": fake,
    }
    kwargs[missing] = ""  # blank → falsy → short-circuit
    out = await auto_index_design_version(**kwargs)
    assert out.indexed is False
    assert out.skipped_reason == expected_reason
    assert out.error is None
    # Crucially: the indexer was *not* invoked.
    assert fake.calls == []


# ─────────────────────────────────────────────────────────────────────
# Empty content → no_content
# ─────────────────────────────────────────────────────────────────────


async def test_empty_source_yields_no_content_skip():
    fake = _FakeIndexer(
        result=IndexResult(
            project_id="p1",
            source_type="design_version",
            source_id="v-1",
            source_version="v1",
            chunk_count=0,
            deleted_count=0,
            embedding_model="stub",
            skipped_reason="no_content",
        ),
    )
    out = await auto_index_design_version(
        session=object(),
        project_id="p1",
        owner_id="u1",
        version_id="v-1",
        version=1,
        graph_data={},
        indexer=fake,
    )
    assert out.indexed is False
    assert out.chunk_count == 0
    assert out.skipped_reason == "no_content"
    # Treat a no-op as an explicit skip — not an error.
    assert out.error is None


# ─────────────────────────────────────────────────────────────────────
# Errors are caught + reported, never raised
# ─────────────────────────────────────────────────────────────────────


async def test_indexer_runtime_error_caught_and_surfaced():
    fake = _FakeIndexer(raises=RuntimeError("embedder offline"))
    out = await auto_index_design_version(
        session=object(),
        project_id="p1",
        owner_id="u1",
        version_id="v-1",
        version=1,
        graph_data={"room": {"type": "kitchen"}},
        indexer=fake,
    )
    assert out.indexed is False
    assert out.skipped_reason == "error"
    assert out.error is not None
    assert "embedder offline" in out.error
    assert out.chunk_count == 0


async def test_indexer_value_error_also_caught():
    """All exceptions — not just RuntimeError — get swallowed."""
    fake = _FakeIndexer(raises=ValueError("bad embedding shape"))
    out = await auto_index_design_version(
        session=object(),
        project_id="p1",
        owner_id="u1",
        version_id="v-1",
        version=1,
        graph_data={"x": "y"},
        indexer=fake,
    )
    assert out.indexed is False
    assert out.skipped_reason == "error"
    assert "bad embedding shape" in (out.error or "")


# ─────────────────────────────────────────────────────────────────────
# AutoIndexResult helpers
# ─────────────────────────────────────────────────────────────────────


def test_from_index_result_marks_indexed_true_when_chunks_present():
    out = AutoIndexResult.from_index_result(IndexResult(
        project_id="p", source_type="x", source_id="y", source_version="",
        chunk_count=3, deleted_count=2, embedding_model="openai",
    ))
    assert out.indexed is True
    assert out.chunk_count == 3
    assert out.deleted_count == 2
    assert out.embedder == "openai"


def test_from_index_result_marks_indexed_false_when_empty():
    out = AutoIndexResult.from_index_result(IndexResult(
        project_id="p", source_type="x", source_id="y", source_version="",
        chunk_count=0, deleted_count=0, embedding_model="stub",
        skipped_reason="no_content",
    ))
    assert out.indexed is False
    assert out.skipped_reason == "no_content"


def test_from_error_packs_exception_type_into_message():
    out = AutoIndexResult.from_error(TimeoutError("oops"))
    assert out.indexed is False
    assert out.skipped_reason == "error"
    assert "TimeoutError" in (out.error or "")
    assert "oops" in (out.error or "")
