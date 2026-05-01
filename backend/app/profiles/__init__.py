"""Stage 8 — pure-Python profile extractors.

Both extractors are deterministic + LLM-free. They read structured
DB data (design graphs, audit events, decisions) and emit
:class:`ArchitectFingerprint` / :class:`ClientPattern` dicts that
land in ``architect_profiles`` / ``client_profiles`` rows.

Why pure-Python?
----------------
- Predictable. Same inputs → same fingerprint, run after run.
- Cheap. Nightly batch over hundreds of projects costs nothing.
- Privacy-friendly. No data leaves the DB host.

A future stage could layer an LLM polish pass on top — e.g. taking
the structured fingerprint and writing a prose summary. For now
the structured shape is enough for the agent's system prompt
injection.
"""

from app.profiles.architect_extractor import (
    ArchitectFingerprint,
    extract_architect_fingerprint,
)
from app.profiles.client_extractor import (
    ClientPattern,
    extract_client_pattern,
)

__all__ = [
    "ArchitectFingerprint",
    "ClientPattern",
    "extract_architect_fingerprint",
    "extract_client_pattern",
]
