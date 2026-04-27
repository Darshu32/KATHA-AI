"""KATHA AI — Layer 1 Knowledge Base.

Structured reference data the AI uses to:
  1. Ground LLM outputs (inject standards into system prompt).
  2. Validate generated design graphs (post-gen range checks).
  3. Feed parametric theme rules into design generation.

Everything here is pure Python data + small helpers — no I/O, no DB.
"""

from app.knowledge import (
    clearances,
    climate,
    codes,
    costing,
    ergonomics,
    ibc,
    manufacturing,
    materials,
    mep,
    regional_materials,
    space_standards,
    structural,
    themes,
    variations,
)
from app.knowledge.summary import build_knowledge_brief

__all__ = [
    "clearances",
    "climate",
    "codes",
    "costing",
    "ergonomics",
    "ibc",
    "manufacturing",
    "materials",
    "mep",
    "regional_materials",
    "space_standards",
    "structural",
    "themes",
    "variations",
    "build_knowledge_brief",
]
