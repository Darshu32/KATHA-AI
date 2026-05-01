"""Tool registry — every imported tool registers itself with
``app.agents.tool.REGISTRY`` at import time.

Adding a new tool? Two steps:

1. Build it in a sibling module (e.g. ``app/agents/tools/<name>.py``)
   using the ``@tool`` decorator from :mod:`app.agents.tool`.
2. Import it here so ``ensure_tools_registered()`` picks it up.

That's it. The registry is global and the agent loop reads from it.

Tool catalogue
--------------
Stage 2  → cost (1 tool)
Stage 4A → themes (2) + clearances (3) + codes (4) + manufacturing (4) + ergonomics (2)
Stage 4B → mep_hvac (2) + mep_electrical (2) + mep_plumbing (3) + mep_cost (1)
Stage 4C → cost_extensions (2 tools — sensitivity + scenario compare)
Stage 4D → specs (3 tools — material / manufacturing / MEP, LLM-heavy)
Stage 4E → drawings (5 tools — plan / elevation / section / detail / isometric)
Stage 4F → diagrams (8 tools — concept / form / volumetric ×2 / process /
           solid-void / spatial organism / hierarchy)
Stage 4G → pipeline (5 tools — initial / theme / edit / list versions / validate)
Stage 4H → io (8 tools — list/parse/export formats + recipients +
           spec bundle + bytes export + import/export manifests)
Stage 5  → recall (1 tool — conversation recall over persisted history)
Stage 5B → memory (3 tools — search / index / stats over project memory RAG)
Stage 5D → memory (+1 tool — prune_project_memory for eviction)

Total: 60 tools as of Stage 5D.
"""

from __future__ import annotations

# Import side-effects register the tools. Order doesn't matter — each
# module is independent and each @tool registers itself.
from app.agents.tools import (  # noqa: F401
    clearances as _clearances,
    codes as _codes,
    cost as _cost,
    cost_extensions as _cost_extensions,
    diagrams as _diagrams,
    drawings as _drawings,
    ergonomics as _ergonomics,
    io as _io,
    manufacturing as _manufacturing,
    memory as _memory,
    mep_cost as _mep_cost,
    mep_electrical as _mep_electrical,
    mep_hvac as _mep_hvac,
    mep_plumbing as _mep_plumbing,
    pipeline as _pipeline,
    recall as _recall,
    specs as _specs,
    themes as _themes,
)


_REGISTERED_MODULES = (
    _clearances,
    _codes,
    _cost,
    _cost_extensions,
    _diagrams,
    _drawings,
    _ergonomics,
    _io,
    _manufacturing,
    _memory,
    _mep_cost,
    _mep_electrical,
    _mep_hvac,
    _mep_plumbing,
    _pipeline,
    _recall,
    _specs,
    _themes,
)


def ensure_tools_registered() -> None:
    """Idempotent — calling this guarantees all built-in tools are in
    the registry. Safe to call from app startup or a test fixture.
    """
    # Touch each module so any aggressive linter / dead-code stripper
    # doesn't remove them and skip the registration side-effects.
    _ = _REGISTERED_MODULES
