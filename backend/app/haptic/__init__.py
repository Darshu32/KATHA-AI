"""Stage 9 — Haptic data structure (BRD Layer 7).

This package holds:

- :mod:`app.haptic.seed` — deterministic seed-row builders the
  Stage 9 migration calls during ``upgrade()``.
- :mod:`app.haptic.catalog` — read-side access to the haptic
  catalog tables (textures / thermal / friction / firmness /
  dimension rules / feedback loops).
- :mod:`app.haptic.exporter` — assembles the haptic export payload
  from a :class:`DesignGraphVersion` snapshot.
- :mod:`app.haptic.validator` — coverage check that asserts every
  material in a design graph has a haptic profile (or falls back
  to the ``"generic"`` profile per BRD Layer 7 spec).

The catalog itself ships as migration seed data — engineers update
values via a new migration, not through the agent. Hardware vendors
read the documented JSON payload format (see ``/docs/haptic/
data-structure.md``) and don't touch the DB directly.

Versioning
----------
Two version strings are stamped on every export:

- ``HAPTIC_SCHEMA_VERSION`` — payload structure version. Bump on
  breaking changes to the export JSON shape.
- ``HAPTIC_CATALOG_VERSION`` — catalog data version. Bumps with
  every Stage 9.x migration that edits seed values.

Hardware drivers compare both before consuming a payload.
"""

from __future__ import annotations

# ── Versioning ─────────────────────────────────────────────────────
# Bump on breaking changes to the export JSON shape (semver).
HAPTIC_SCHEMA_VERSION = "9.0.0"

# Bumps with every migration that edits the haptic catalog seed.
# Stage 9 ships catalog v1; later seed migrations roll it forward.
HAPTIC_CATALOG_VERSION = "2026.05.01"

# Sentinel material key used when a design graph references a
# material with no haptic profile in the catalog. The exporter
# attaches the ``"generic"`` profile and flags the material in the
# payload's ``validation.fallback_materials`` list. Per BRD Layer 7
# this is the documented fallback behaviour.
GENERIC_MATERIAL_KEY = "generic"


__all__ = [
    "HAPTIC_SCHEMA_VERSION",
    "HAPTIC_CATALOG_VERSION",
    "GENERIC_MATERIAL_KEY",
]
