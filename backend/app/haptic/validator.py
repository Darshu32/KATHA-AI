"""Coverage validator for haptic exports.

Walks the materials referenced in a design graph and reports which
ones lack a complete haptic profile in the catalog. Per BRD §Layer 7
the policy is *fall back to the ``"generic"`` profile* — the
validator never blocks an export, it just flags the substitution
on the payload's ``validation`` block so vendors can decide whether
they trust a "partially generic" export.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.haptic import GENERIC_MATERIAL_KEY
from app.haptic.catalog import CatalogSnapshot


@dataclass
class CoverageReport:
    """Outcome of running the validator over one design graph."""

    requested_materials: list[str] = field(default_factory=list)
    """Every distinct material key referenced by the graph."""

    mapped_materials: list[str] = field(default_factory=list)
    """Materials that resolved to a complete catalog profile."""

    fallback_materials: list[str] = field(default_factory=list)
    """Materials that fell back to the ``generic`` profile.

    These exports still go through, but vendors should review them
    before relying on physical accuracy.
    """

    missing_object_types: list[str] = field(default_factory=list)
    """Object types referenced by the graph with no dimension rule
    in the catalog. Haptic can still render them statically; the
    arm just won't expose adjustment sliders."""

    warnings: list[str] = field(default_factory=list)
    """Free-form human-readable notes for the export's audit log."""

    @property
    def all_materials_mapped(self) -> bool:
        """True iff every referenced material had a complete profile.

        ``False`` means at least one fell back to ``generic``. The
        export still succeeds.
        """
        return not self.fallback_materials

    def to_payload_dict(self) -> dict[str, object]:
        """Shape used inside the export payload's ``validation`` block."""
        return {
            "all_materials_mapped": self.all_materials_mapped,
            "requested_materials": list(self.requested_materials),
            "mapped_materials": list(self.mapped_materials),
            "fallback_materials": list(self.fallback_materials),
            "missing_object_types": list(self.missing_object_types),
            "warnings": list(self.warnings),
        }


def validate_coverage(
    *,
    catalog: CatalogSnapshot,
    materials_used: Iterable[str],
    object_types_used: Iterable[str],
) -> CoverageReport:
    """Cross-check graph-referenced keys against the catalog.

    Returns a report listing the resolution outcome per material
    and per object type. Pure function — no DB, no I/O.

    The ``generic`` profile itself counts as fallback when used,
    even though it's a real catalog row.
    """
    report = CoverageReport()

    # ── Materials ────────────────────────────────────────────────────
    seen_materials: set[str] = set()
    for raw in materials_used:
        key = (raw or "").strip().lower()
        if not key or key in seen_materials:
            continue
        seen_materials.add(key)
        report.requested_materials.append(key)

        profile = catalog.get_material(key)
        if profile is not None and profile.is_complete:
            report.mapped_materials.append(key)
            continue

        # Anything else falls back to the generic profile per BRD.
        report.fallback_materials.append(key)
        if catalog.get_material(GENERIC_MATERIAL_KEY) is None:
            report.warnings.append(
                f"material={key!r} unmapped and the generic fallback "
                "profile is missing from the catalog — re-run the "
                "Stage 9 seed migration."
            )

    # ── Object types ─────────────────────────────────────────────────
    seen_objects: set[str] = set()
    for raw in object_types_used:
        key = (raw or "").strip().lower()
        if not key or key in seen_objects:
            continue
        seen_objects.add(key)
        if catalog.get_dimension_rule(key) is None:
            report.missing_object_types.append(key)

    return report
