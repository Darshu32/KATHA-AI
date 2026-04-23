"""Technical specification generators (BRD Layer 3).

Produce pure structured-data spec sheets — material, manufacturing, MEP,
cost — from a DesignGraph. The exporters (PDF/DOCX/XLSX) then render
these into client-facing documents.

Nothing in this package knows about file formats — only shape + content.
"""

from app.services.specs.builder import build_spec_bundle

__all__ = ["build_spec_bundle"]
