"""Tool registry — every imported tool registers itself with
``app.agents.tool.REGISTRY`` at import time.

Adding a new tool? Two steps:

1. Build it in a sibling module (e.g. ``app/agents/tools/<name>.py``)
   using the ``@tool`` decorator from :mod:`app.agents.tool`.
2. Import it here so ``ensure_tools_registered()`` picks it up.

That's it. The registry is global and the agent loop reads from it.

Stage 2 ships exactly one tool: cost engine.
Stage 4 will add ~30 more (drawings, specs, MEP, exports …).
"""

from __future__ import annotations

# Import side-effects register the tools.
from app.agents.tools import cost as _cost  # noqa: F401


def ensure_tools_registered() -> None:
    """Idempotent — calling this guarantees all built-in tools are in
    the registry. Safe to call from app startup or a test fixture.
    """
    _ = _cost  # keep import alive if linters trim unused
