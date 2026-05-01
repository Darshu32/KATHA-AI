"""Stage 11 — provenance / source-of-truth banner.

Every tool output, every BOQ, every spec, every design decision in
KATHA-AI carries a provenance banner — a small JSON block stamping
exactly which catalog versions, which tool, which agent loop
produced the artefact. Architects (and auditors) can trace any
number back to the data + code that produced it.

The banner is **declarative and free** — no external service call,
no LLM round-trip, just a dict of version constants assembled at
the moment the artefact is finalised. Cache-friendly per request.

Public surface:

- :func:`build_banner` — returns a fresh banner dict.
- :class:`Provenance` — typed dataclass wrapping the same content
  for callers that prefer attribute access.

The framework's :func:`app.agents.tool.call_tool` dispatcher
attaches a banner to every successful tool result envelope (Stage 11
retrofit), so all 78+ tools surface provenance without touching
their individual modules.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# Stage 9 catalogue versions — re-exported so the banner can stamp
# them without import cycles.
from app.haptic import HAPTIC_CATALOG_VERSION, HAPTIC_SCHEMA_VERSION


# ─────────────────────────────────────────────────────────────────────
# Versioning constants — single source of truth for the banner.
# ─────────────────────────────────────────────────────────────────────


# Bump on breaking changes to the banner JSON shape (semver).
PROVENANCE_SCHEMA_VERSION = "11.0.0"

# Tooling generation — bumps when the agent toolset signature
# changes (new stages of tools, breaking input/output reshapes).
# Stage 10 closed Phase 1 → tooling generation 1.0.0.
TOOLING_GENERATION = "1.0.0"

# Knowledge corpus generation — bumps when the global RAG corpus is
# re-indexed against a substantively different source set. The
# Stage 6 corpus is generation 1; reindexes within the same source
# set don't bump this.
CORPUS_GENERATION = "1"

# Theme catalog generation — bumps when theme rule packs change.
# Stage 3A seeded the original themes; subsequent admin edits bump
# this via a migration.
THEME_CATALOG_GENERATION = "1"

# Pricing catalog generation — bumps when the pricing knowledge
# table is reseeded against a new market snapshot.
PRICING_CATALOG_GENERATION = "1"


@dataclass
class Provenance:
    """Typed view of the provenance banner.

    Most callers should use :func:`build_banner` and pass the dict
    around; this dataclass is for callers that prefer attribute
    access (e.g. the cost/spec services that compose banners).
    """

    schema_version: str = PROVENANCE_SCHEMA_VERSION
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Code generation — bumps with code changes that materially
    # alter outputs. Currently a constant; pulled into a setting if
    # CI starts stamping the build.
    tooling_generation: str = TOOLING_GENERATION

    # Catalog versions — keep them flat so a banner consumer can
    # `banner["catalog_versions"]["haptic"]` without nested loops.
    catalog_versions: dict[str, str] = field(default_factory=dict)

    # Per-tool stamps — set by the framework when the banner is
    # attached to a tool result envelope. May be empty when the
    # banner is built outside a tool dispatch (e.g. in the spec
    # bundle assembler).
    tool: Optional[str] = None
    tool_invocation_kind: Optional[str] = None
    request_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ─────────────────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────────────────


def _catalog_versions() -> dict[str, str]:
    """All catalog versions stamped on every banner.

    Centralised so a future migration that bumps a generation
    propagates without grep-and-replace across the codebase.
    """
    return {
        "haptic_catalog": HAPTIC_CATALOG_VERSION,
        "haptic_schema": HAPTIC_SCHEMA_VERSION,
        "themes": THEME_CATALOG_GENERATION,
        "pricing": PRICING_CATALOG_GENERATION,
        "knowledge_corpus": CORPUS_GENERATION,
    }


def build_banner(
    *,
    tool: Optional[str] = None,
    tool_invocation_kind: Optional[str] = None,
    request_id: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Assemble a fresh provenance banner.

    Parameters
    ----------
    tool:
        Name of the agent tool whose output this banner accompanies.
        ``None`` when the banner is built outside an agent dispatch
        (e.g. from a service composing a spec bundle).
    tool_invocation_kind:
        Free-form classifier — ``"agent_call" | "scheduled_task" |
        "http_route" | "service_internal"``. Stamped so log
        consumers can filter by call surface.
    request_id:
        Observability join-key — matches the request_id on
        :class:`AuditEvent` rows for the same call.
    extra:
        Free-form key/value pairs the caller wants stamped.
        Common: ``{"design_version_id": "...", "snapshot_id": "..."}``.
        Merged on top — caller can override defaults if they need to.

    Returns
    -------
    dict
        JSON-safe banner ready to drop into any tool / route /
        service output.
    """
    banner: dict[str, Any] = {
        "schema_version": PROVENANCE_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tooling_generation": TOOLING_GENERATION,
        "catalog_versions": _catalog_versions(),
        "tool": tool,
        "tool_invocation_kind": tool_invocation_kind,
        "request_id": request_id,
    }
    if extra:
        banner.update(dict(extra))
    return banner


__all__ = [
    "PROVENANCE_SCHEMA_VERSION",
    "TOOLING_GENERATION",
    "CORPUS_GENERATION",
    "THEME_CATALOG_GENERATION",
    "PRICING_CATALOG_GENERATION",
    "Provenance",
    "build_banner",
]
