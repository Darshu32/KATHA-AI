"""Stage 6 unit tests — hybrid retriever logic + re-ranker contract.

We exercise the parts of the retriever that don't need a real DB:

- ``_normalise`` min-max behaviour.
- ``_hybrid_merge`` weighted blend across two candidate lists.
- ``NoopReranker`` truncation + ordering.
- ``CorpusRetriever`` weight validation.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.corpus.re_ranker import NoopReranker, RerankCandidate
from app.corpus.retriever import (
    CorpusRetriever,
    _hybrid_merge,
    _normalise,
)
from app.repositories.knowledge_corpus.chunk_repo import HybridSearchRow


# ─────────────────────────────────────────────────────────────────────
# _normalise
# ─────────────────────────────────────────────────────────────────────


def test_normalise_min_max_scales_into_unit_range():
    out = _normalise([1.0, 2.0, 5.0])
    assert out[0] == pytest.approx(0.0)
    assert out[-1] == pytest.approx(1.0)
    assert 0.0 <= out[1] <= 1.0


def test_normalise_empty_returns_empty():
    assert _normalise([]) == []


def test_normalise_all_equal_returns_all_ones():
    """No spread → no information; treat every score as max."""
    assert _normalise([0.5, 0.5, 0.5]) == [1.0, 1.0, 1.0]


def test_normalise_negatives_handled():
    out = _normalise([-1.0, 0.0, 1.0])
    assert out[0] == pytest.approx(0.0)
    assert out[-1] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────
# _hybrid_merge
# ─────────────────────────────────────────────────────────────────────


def _row(chunk_id: str, score: float, *, distance=None, bm25=None):
    """Build a fake HybridSearchRow with just the attributes the
    merger reads."""
    chunk = SimpleNamespace(id=chunk_id)
    return HybridSearchRow(chunk=chunk, score=score, distance=distance, bm25_rank=bm25)


def test_hybrid_merge_blends_vector_and_bm25():
    """Same chunk on both sides → blended score is a weighted mix."""
    vec = [_row("a", 1.0, distance=0.0)]    # normalised → 1.0
    bm = [_row("a", 0.5, bm25=0.5)]         # normalised → 1.0
    merged = _hybrid_merge(vec, bm, vector_weight=0.7, bm25_weight=0.3)
    assert len(merged) == 1
    row, score = merged[0]
    assert row.chunk.id == "a"
    assert score == pytest.approx(1.0)


def test_hybrid_merge_includes_unique_rows_from_each_side():
    """Vector finds A; BM25 finds B; both should appear."""
    vec = [_row("a", 1.0, distance=0.0)]
    bm = [_row("b", 0.5, bm25=0.5)]
    merged = _hybrid_merge(vec, bm, vector_weight=0.7, bm25_weight=0.3)
    ids = {row.chunk.id for row, _ in merged}
    assert ids == {"a", "b"}


def test_hybrid_merge_orders_by_blended_score_desc():
    """Higher blended score must come first."""
    vec = [
        _row("a", 1.0, distance=0.0),    # vec norm 1.0
        _row("b", 0.0, distance=2.0),    # vec norm 0.0
    ]
    bm = []
    merged = _hybrid_merge(vec, bm, vector_weight=0.7, bm25_weight=0.3)
    assert [row.chunk.id for row, _ in merged] == ["a", "b"]


def test_hybrid_merge_handles_empty_inputs():
    assert _hybrid_merge([], [], vector_weight=0.7, bm25_weight=0.3) == []


# ─────────────────────────────────────────────────────────────────────
# NoopReranker
# ─────────────────────────────────────────────────────────────────────


async def test_noop_reranker_keeps_descending_score_order():
    rr = NoopReranker()
    cands = [
        RerankCandidate(content="low", score=0.2, opaque=1),
        RerankCandidate(content="high", score=0.9, opaque=2),
        RerankCandidate(content="mid", score=0.5, opaque=3),
    ]
    out = await rr.rerank("anything", cands, top_k=10)
    assert [c.score for c in out] == [0.9, 0.5, 0.2]
    assert [c.opaque for c in out] == [2, 3, 1]


async def test_noop_reranker_truncates_at_top_k():
    rr = NoopReranker()
    cands = [RerankCandidate(content=str(i), score=float(i), opaque=i) for i in range(10)]
    out = await rr.rerank("q", cands, top_k=3)
    assert len(out) == 3
    assert [c.opaque for c in out] == [9, 8, 7]


async def test_noop_reranker_empty_input_empty_output():
    rr = NoopReranker()
    assert await rr.rerank("q", [], top_k=5) == []


# ─────────────────────────────────────────────────────────────────────
# CorpusRetriever weight validation
# ─────────────────────────────────────────────────────────────────────


def test_retriever_rejects_weights_that_dont_sum_to_one():
    from app.memory import StubEmbedder

    with pytest.raises(ValueError):
        CorpusRetriever(
            embedder=StubEmbedder(),
            vector_weight=0.5,
            bm25_weight=0.3,  # sum = 0.8
        )
    # Default weights must sum to exactly 1.0.
    rr = CorpusRetriever(embedder=StubEmbedder())
    assert abs((0.7 + 0.3) - 1.0) < 1e-6
    assert rr.embedder.name == "stub"


def test_retriever_default_reranker_is_noop():
    from app.memory import StubEmbedder

    rr = CorpusRetriever(embedder=StubEmbedder())
    assert rr.reranker.name == "noop"
