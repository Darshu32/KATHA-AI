"""Stage 2 integration test — real Anthropic call through the agent loop.

Skipped unless **both** are true:
  - ``KATHA_INTEGRATION_TESTS=1``
  - ``ANTHROPIC_API_KEY`` set to a working key

Cost note
---------
This test makes a single short Anthropic call (~few hundred tokens).
On Claude Sonnet that's a few cents at most — but it does cost real
money, so we keep the assertions cheap (1 turn, no tool execution).
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


_ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
_HAS_KEY = bool(_ANTHROPIC_KEY)


@pytest.mark.skipif(not _HAS_KEY, reason="ANTHROPIC_API_KEY not set")
async def test_agent_smoke_against_real_anthropic(db_session):
    """Send one message, verify we get a `done` event with usage > 0."""
    from app.agents.architect_agent import run_architect_agent
    from app.agents.stream import DoneEvent, ErrorEvent
    from app.agents.tool import ToolContext

    ctx = ToolContext(session=db_session, actor_id=None, request_id="smoke")
    events = []
    async for ev in run_architect_agent(
        user_message=(
            "Reply with the single word 'ack' and nothing else. "
            "Do not call any tools."
        ),
        ctx=ctx,
        max_tokens=64,
    ):
        events.append(ev)

    assert not any(isinstance(e, ErrorEvent) for e in events), (
        "Anthropic returned an error: "
        f"{[e.message for e in events if isinstance(e, ErrorEvent)]}"
    )
    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1
    # Real call → real usage.
    assert done[0].input_tokens > 0
    assert done[0].output_tokens > 0
