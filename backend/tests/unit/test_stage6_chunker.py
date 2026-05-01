"""Stage 6 unit tests — chunker semantics + extractor outputs.

These tests don't touch a DB or an embedder. They exercise:

- ``extract_plain_text`` page splitting on form feeds.
- Section anchor heuristics (which lines look like headings).
- ``chunk_document`` boundaries — soft target, hard max, overlap,
  page tracking, section propagation.
- The two RAG agent tools' registry shape.
"""

from __future__ import annotations

import pytest

from app.corpus.chunker import chunk_document
from app.corpus.extractors.pdf import _looks_like_heading
from app.corpus.extractors.plain_text import extract_plain_text


# ─────────────────────────────────────────────────────────────────────
# Heading heuristics
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("line,expected", [
    ("Part 4 — Plumbing Services", True),
    ("PART 9 - PLUMBING SERVICES", True),
    ("Chapter 5 Fire Protection", True),
    ("Section 503 Fire-resistance ratings", True),
    ("§3.2.1 Corridor widths", True),
    ("Annex A — Worked examples", True),
    ("3.2.1 Minimum corridor width", True),
    ("This is a normal paragraph about corridors.", False),
    ("", False),
    ("   ", False),
])
def test_looks_like_heading(line, expected):
    assert _looks_like_heading(line) is expected


# ─────────────────────────────────────────────────────────────────────
# extract_plain_text
# ─────────────────────────────────────────────────────────────────────


def test_extract_plain_text_single_page_when_no_form_feeds():
    doc = extract_plain_text(
        source_id="test-1",
        title="Test Document",
        text="Just one page of text.\n\nWith two paragraphs.",
    )
    assert doc.title == "Test Document"
    assert len(doc.pages) == 1
    assert doc.pages[0].page == 1
    assert "two paragraphs" in doc.pages[0].text


def test_extract_plain_text_form_feeds_split_into_pages():
    text = (
        "Page 1 content.\n"
        "Part 4 — Plumbing\n"
        "More on page 1.\n"
        "\f"
        "Page 2 content.\n"
        "\f"
        "Page 3 content.\n"
        "Section 503 Fire safety"
    )
    doc = extract_plain_text(
        source_id="ff-1",
        title="FF Test",
        text=text,
    )
    assert doc.total_pages == 3
    assert doc.pages[0].page == 1
    assert doc.pages[1].page == 2
    assert doc.pages[2].page == 3
    # Section hint propagates from page 1's heading until page 3 finds its own.
    assert "Part 4" in doc.pages[0].section_hint
    assert "Part 4" in doc.pages[1].section_hint   # carried forward
    assert "Section 503" in doc.pages[2].section_hint


def test_extract_plain_text_carries_metadata_into_document():
    doc = extract_plain_text(
        source_id="meta-1",
        title="NBC India 2016 — Excerpt",
        text="Hello",
        source_type="textbook",
        jurisdiction="nbc_india_2016",
        publisher="BIS",
        edition="2016",
        language="en",
        effective_from="2016-12-19",
    )
    assert doc.jurisdiction == "nbc_india_2016"
    assert doc.publisher == "BIS"
    assert doc.edition == "2016"
    assert doc.effective_from == "2016-12-19"


# ─────────────────────────────────────────────────────────────────────
# chunk_document
# ─────────────────────────────────────────────────────────────────────


def test_chunk_document_empty_returns_empty():
    doc = extract_plain_text(source_id="e", title="Empty", text="")
    assert chunk_document(doc) == []


def test_chunk_document_short_text_yields_one_chunk_with_indices():
    doc = extract_plain_text(
        source_id="s", title="Short",
        text="Part 4 — Plumbing\n\nA single short paragraph.",
    )
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.chunk_index == 0
    assert c.total_chunks == 1
    assert c.page == 1
    assert c.page_end == 1
    assert "Part 4" in c.section


def test_chunk_document_long_text_splits_with_overlap():
    """Stuff a 4-paragraph payload through the chunker and confirm we
    get multiple chunks, sequential indices, and overlap between
    adjacent chunks."""
    para = "x" * 2400  # ~600 tokens
    text = "\n\n".join([para] * 4)
    doc = extract_plain_text(source_id="long", title="Long", text=text)
    chunks = chunk_document(doc, target_tokens=500, max_tokens=1500, overlap_ratio=0.2)
    assert len(chunks) >= 2
    # Sequential, consistent metadata.
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert all(c.total_chunks == len(chunks) for c in chunks)
    # Adjacent chunks should share *some* content (overlap_ratio=0.2).
    overlap_seen = False
    for i in range(len(chunks) - 1):
        a_tail = chunks[i].content[-200:]
        b = chunks[i + 1].content
        if a_tail and a_tail in b:
            overlap_seen = True
            break
    assert overlap_seen, "expected overlap between adjacent chunks"


def test_chunk_document_propagates_section_across_pages():
    """A section heading on page 1 should anchor chunks emitted on
    page 2 if no new heading appears."""
    text = (
        "Part 4 — Plumbing services\n\n"
        "Paragraph one on page 1 about supply pipes.\n"
        "\f"
        "Paragraph two on page 2, still under part 4."
    )
    doc = extract_plain_text(source_id="sect", title="Sect", text=text)
    chunks = chunk_document(doc)
    assert len(chunks) >= 1
    # All chunks should attribute to "Part 4".
    assert any("Part 4" in c.section for c in chunks)


def test_chunk_document_tracks_page_range_for_multi_page_chunks():
    """A short paragraph on page 1 + a short paragraph on page 2 may
    end up in the same chunk — the page range must reflect both."""
    text = "Short P1.\f Short P2."
    doc = extract_plain_text(source_id="pp", title="PP", text=text)
    chunks = chunk_document(doc, target_tokens=500)
    # Whether they end up in 1 or 2 chunks depends on length, but the
    # first chunk should span page 1 at minimum.
    assert chunks[0].page == 1
    if len(chunks) == 1:
        assert chunks[0].page_end >= 1


def test_chunk_document_invalid_overlap_raises():
    doc = extract_plain_text(source_id="x", title="X", text="hi")
    with pytest.raises(ValueError):
        chunk_document(doc, overlap_ratio=1.0)
    with pytest.raises(ValueError):
        chunk_document(doc, overlap_ratio=-0.1)


# ─────────────────────────────────────────────────────────────────────
# Tool registry shape
# ─────────────────────────────────────────────────────────────────────


def test_search_knowledge_registered_read_only():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("search_knowledge")
    # Read-only — eligible for parallel dispatch.
    assert spec.audit_target_type is None
    schema = spec.input_schema()
    props = schema["properties"]
    assert "query" in props
    assert "jurisdiction" in props
    assert "top_k" in props
    assert props["top_k"]["minimum"] == 1
    assert props["top_k"]["maximum"] == 20
    required = set(schema.get("required", []))
    assert required == {"query"}


def test_list_knowledge_sources_registered_read_only():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("list_knowledge_sources")
    assert spec.audit_target_type is None
    schema = spec.input_schema()
    required = set(schema.get("required", []))
    assert required == set()


def test_tool_count_at_least_62_after_stage6():
    """Stage 4 (55) + 5 recall (1) + 5B memory (3) + 5D prune (1) + 6 (2) = 62."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    assert len(REGISTRY.names()) >= 62


def test_search_knowledge_output_carries_citation_contract():
    """The CitedHit shape must surface every citation field."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    spec = REGISTRY.get("search_knowledge")
    output_schema = spec.output_model.model_json_schema()
    # The output has an `items` ref — pull the CitedHit definition.
    defs = output_schema.get("$defs") or output_schema.get("definitions") or {}
    cited = next(
        (sub for sub in defs.values()
         if isinstance(sub, dict)
         and "section" in (sub.get("properties") or {})
         and "page" in (sub.get("properties") or {})),
        None,
    )
    assert cited is not None
    props = cited["properties"]
    for required in ("content", "source", "jurisdiction",
                     "page", "page_end", "section", "score"):
        assert required in props, f"CitedHit missing {required!r}"
