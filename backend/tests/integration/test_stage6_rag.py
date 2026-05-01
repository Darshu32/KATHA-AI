"""Stage 6 integration tests — end-to-end RAG against real Postgres.

Requires Postgres + pgvector + ``alembic upgrade head`` so the
``content_tsv`` column + GIN index + IVFFlat index are present.
Tests use :class:`StubEmbedder` so they don't burn OpenAI calls,
but the DB-side cosine search + tsvector FTS are real.

Coverage:

- Ingest a synthetic plain-text "code book" → chunks land with
  the right citation metadata (page, section, jurisdiction).
- Re-ingesting the same logical document replaces the chunks
  (idempotency).
- ``search_knowledge`` tool returns hits with the citation contract
  fully populated.
- Jurisdiction filter excludes other corpora.
- ``list_knowledge_sources`` reflects what's been indexed.
- BM25 path matches exact code references even when the embedder
  is just a hash.
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
        display_name="S6 test",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.id


def _stub_ingester():
    from app.corpus import CorpusIngester
    from app.memory import StubEmbedder
    return CorpusIngester(embedder=StubEmbedder())


def _stub_retriever():
    from app.corpus import CorpusRetriever
    from app.memory import StubEmbedder
    return CorpusRetriever(embedder=StubEmbedder())


# A synthetic "code book" we can ingest deterministically. The
# content includes:
#  - A heading-like first line so section anchors propagate.
#  - Distinct keywords on each page so BM25 has something to match.
_NBC_CORRIDOR_EXCERPT = (
    "Part 4 — General Building Requirements\n\n"
    "3.2 Corridor widths shall be a minimum of 1500 mm in hospitals\n"
    "to allow for stretcher movement and accessibility.\n"
    "\f"
    "3.2.1 In residential buildings the minimum corridor width\n"
    "shall be 900 mm. Wider clearances are recommended where\n"
    "occupancy exceeds 20 persons.\n"
    "\f"
    "3.3 Doorways and openings shall accommodate 1100 mm clear\n"
    "for primary entries and 900 mm for internal doors.\n"
)

_IBC_FIRE_EXCERPT = (
    "Chapter 5 — Fire Resistance\n\n"
    "503.1 Fire-rated walls in office occupancies shall achieve\n"
    "a minimum 1-hour rating per ASTM E119.\n"
    "\f"
    "503.2 Fire dampers required in any duct penetrating a\n"
    "fire-rated assembly. Maximum spacing 200 mm from the\n"
    "rated surface.\n"
)


# ─────────────────────────────────────────────────────────────────────
# Ingestion
# ─────────────────────────────────────────────────────────────────────


async def test_ingest_plain_text_creates_document_and_chunks(db_session):
    """Ingest a synthetic code excerpt and verify everything landed
    with the right citation hooks."""
    from app.corpus import extract_plain_text
    from app.repositories.knowledge_corpus import (
        KnowledgeChunkRepository,
        KnowledgeDocumentRepository,
    )

    doc = extract_plain_text(
        source_id="nbc-corridor-test",
        title="NBC India 2016 — Corridor excerpt",
        text=_NBC_CORRIDOR_EXCERPT,
        source_type="pdf",
        jurisdiction="nbc_india_2016",
        publisher="BIS",
        edition="2016",
    )

    ingester = _stub_ingester()
    result = await ingester.ingest(db_session, document=doc)

    assert result.chunk_count >= 1
    assert result.skipped_reason is None
    assert result.embedder == "stub"

    # Document row written with full citation metadata.
    row = await KnowledgeDocumentRepository.get_by_id(db_session, result.document_id)
    assert row is not None
    assert row.jurisdiction == "nbc_india_2016"
    assert row.publisher == "BIS"
    assert row.edition == "2016"
    assert row.status == "indexed"

    # Chunks all carry the document's jurisdiction (denormalised).
    rows = await KnowledgeChunkRepository.count(
        db_session, jurisdiction="nbc_india_2016",
    )
    assert rows >= 1


async def test_re_ingest_replaces_prior_chunks(db_session):
    """Ingesting the same (jurisdiction, title, edition) twice
    replaces all chunks."""
    from app.corpus import extract_plain_text
    from app.repositories.knowledge_corpus import KnowledgeChunkRepository

    ingester = _stub_ingester()

    doc_v1 = extract_plain_text(
        source_id="reingest-1",
        title="Test code",
        text="Part 1 alpha\n\nFirst paragraph.",
        jurisdiction="test_jur",
        edition="v1",
    )
    r1 = await ingester.ingest(db_session, document=doc_v1)
    assert r1.deleted_count == 0
    pre_chunks = await KnowledgeChunkRepository.count(
        db_session, jurisdiction="test_jur",
    )
    assert pre_chunks >= 1

    # Re-ingest same logical key, different content.
    doc_v1b = extract_plain_text(
        source_id="reingest-1",
        title="Test code",
        text="Part 1 alpha\n\nDifferent first paragraph.\n\nNew content.",
        jurisdiction="test_jur",
        edition="v1",
    )
    r2 = await ingester.ingest(db_session, document=doc_v1b)
    # Old chunks were deleted, fresh ones inserted.
    assert r2.deleted_count == pre_chunks
    # Document id is unchanged.
    assert r2.document_id == r1.document_id


async def test_ingest_empty_document_is_no_content(db_session):
    """Empty source → zero chunks + skipped_reason='no_content',
    document still upserted."""
    from app.corpus import extract_plain_text

    doc = extract_plain_text(
        source_id="empty",
        title="Empty",
        text="",
        jurisdiction="empty_jur",
    )
    ingester = _stub_ingester()
    result = await ingester.ingest(db_session, document=doc)
    assert result.chunk_count == 0
    assert result.skipped_reason == "no_content"


# ─────────────────────────────────────────────────────────────────────
# Hybrid retrieval
# ─────────────────────────────────────────────────────────────────────


async def test_hybrid_search_finds_indexed_chunks(db_session):
    from app.corpus import extract_plain_text

    ingester = _stub_ingester()
    retriever = _stub_retriever()

    doc = extract_plain_text(
        source_id="search-1",
        title="NBC India 2016",
        text=_NBC_CORRIDOR_EXCERPT,
        jurisdiction="nbc_india_2016",
        edition="2016",
    )
    await ingester.ingest(db_session, document=doc)

    hits = await retriever.search(
        db_session,
        query="corridor width",
        top_k=5,
    )
    assert len(hits) >= 1
    top = hits[0]
    # Citation contract fields populated.
    assert top.source.startswith("NBC India 2016")
    assert top.jurisdiction == "nbc_india_2016"
    assert top.page >= 1
    assert top.content


async def test_jurisdiction_filter_excludes_other_corpora(db_session):
    """NBC + IBC ingested; search filtered to NBC must not return IBC."""
    from app.corpus import extract_plain_text

    ingester = _stub_ingester()
    retriever = _stub_retriever()

    await ingester.ingest(
        db_session,
        document=extract_plain_text(
            source_id="nbc-1", title="NBC India",
            text=_NBC_CORRIDOR_EXCERPT,
            jurisdiction="nbc_india_2016", edition="2016",
        ),
    )
    await ingester.ingest(
        db_session,
        document=extract_plain_text(
            source_id="ibc-1", title="IBC US",
            text=_IBC_FIRE_EXCERPT,
            jurisdiction="ibc_us_2021", edition="2021",
        ),
    )

    hits = await retriever.search(
        db_session,
        query="corridor",
        jurisdiction="nbc_india_2016",
        top_k=10,
    )
    assert all(h.jurisdiction == "nbc_india_2016" for h in hits)


async def test_bm25_path_matches_exact_code_references(db_session):
    """The stub embedder doesn't model semantics, so a query against
    an exact phrase like '503.1' relies on BM25 to find it."""
    from app.corpus import extract_plain_text

    ingester = _stub_ingester()
    retriever = _stub_retriever()

    await ingester.ingest(
        db_session,
        document=extract_plain_text(
            source_id="ibc-503", title="IBC", text=_IBC_FIRE_EXCERPT,
            jurisdiction="ibc_us_2021", edition="2021",
        ),
    )

    hits = await retriever.search(
        db_session,
        query="fire-rated walls",
        jurisdiction="ibc_us_2021",
        top_k=5,
    )
    assert len(hits) >= 1
    # The matched chunk should mention the keyword.
    assert any("fire-rated walls" in h.content.lower() for h in hits)


async def test_search_returns_empty_for_empty_query(db_session):
    retriever = _stub_retriever()
    hits = await retriever.search(db_session, query="   ", top_k=5)
    assert hits == []


# ─────────────────────────────────────────────────────────────────────
# Agent tools end-to-end
# ─────────────────────────────────────────────────────────────────────


async def test_search_knowledge_tool_e2e(monkeypatch, db_session):
    """Drive ``search_knowledge`` through ``call_tool`` and confirm
    the citation contract is intact."""
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.corpus import extract_plain_text
    from app.memory import StubEmbedder

    # Force StubEmbedder so the tool's CorpusRetriever() instantiation
    # doesn't try to reach OpenAI.
    monkeypatch.setattr(
        "app.memory.embeddings.get_embedder", lambda: StubEmbedder(),
    )

    ensure_tools_registered()
    user_id = await _seed_user(db_session, email="s6-search@example.com")

    # Seed the corpus.
    ingester = _stub_ingester()
    await ingester.ingest(
        db_session,
        document=extract_plain_text(
            source_id="nbc-search-tool",
            title="NBC India 2016",
            text=_NBC_CORRIDOR_EXCERPT,
            jurisdiction="nbc_india_2016",
            edition="2016",
        ),
    )

    ctx = ToolContext(
        session=db_session, actor_id=user_id, request_id="s6-search",
    )
    result = await call_tool(
        "search_knowledge",
        {"query": "hospital corridor width", "top_k": 5,
         "jurisdiction": "nbc_india_2016"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["query"] == "hospital corridor width"
    assert out["jurisdiction"] == "nbc_india_2016"
    assert out["embedder"] == "stub"
    assert out["reranker"] == "noop"
    assert out["returned_count"] >= 1

    top = out["hits"][0]
    # Citation contract — every required field is present + non-empty.
    assert top["content"]
    assert top["source"].startswith("NBC India 2016")
    assert top["jurisdiction"] == "nbc_india_2016"
    assert top["page"] >= 1
    assert top["chunk_id"]
    assert top["document_id"]


async def test_search_knowledge_requires_actor(db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    ctx = ToolContext(
        session=db_session, actor_id=None, request_id="s6-noactor",
    )
    result = await call_tool(
        "search_knowledge",
        {"query": "corridor"},
        ctx, registry=REGISTRY,
    )
    assert result["ok"] is False
    assert "actor" in result["error"]["message"].lower()


async def test_list_knowledge_sources_tool(monkeypatch, db_session):
    from app.agents.tool import REGISTRY, ToolContext, call_tool
    from app.agents.tools import ensure_tools_registered
    from app.corpus import extract_plain_text
    from app.memory import StubEmbedder

    monkeypatch.setattr(
        "app.memory.embeddings.get_embedder", lambda: StubEmbedder(),
    )
    ensure_tools_registered()

    user_id = await _seed_user(db_session, email="s6-list@example.com")
    ingester = _stub_ingester()
    await ingester.ingest(
        db_session,
        document=extract_plain_text(
            source_id="nbc-list-1", title="NBC India 2016",
            text=_NBC_CORRIDOR_EXCERPT,
            jurisdiction="nbc_india_2016", edition="2016",
        ),
    )
    await ingester.ingest(
        db_session,
        document=extract_plain_text(
            source_id="ibc-list-1", title="IBC US",
            text=_IBC_FIRE_EXCERPT,
            jurisdiction="ibc_us_2021", edition="2021",
        ),
    )

    ctx = ToolContext(
        session=db_session, actor_id=user_id, request_id="s6-list",
    )

    # Unfiltered — both docs.
    result = await call_tool(
        "list_knowledge_sources", {}, ctx, registry=REGISTRY,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["total_documents"] >= 2
    titles = {s["title"] for s in out["sources"]}
    assert "NBC India 2016" in titles
    assert "IBC US" in titles
    # Each source carries chunk count.
    for s in out["sources"]:
        assert s["chunk_count"] >= 1

    # Filtered to NBC only.
    result_nbc = await call_tool(
        "list_knowledge_sources",
        {"jurisdiction": "nbc_india_2016"},
        ctx, registry=REGISTRY,
    )
    assert result_nbc["ok"]
    titles_nbc = {s["title"] for s in result_nbc["output"]["sources"]}
    assert titles_nbc == {"NBC India 2016"}
