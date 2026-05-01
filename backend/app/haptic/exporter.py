"""Build a haptic export payload from a :class:`DesignGraphVersion`.

The payload mirrors BRD §Layer 7's four data buckets verbatim:

1. **Dimension data** — rooms + objects with width/depth/height in mm
2. **Material haptic properties** — texture / thermal / friction /
   firmness for every material the design uses
3. **Interaction parameters** — per-object adjustable axes + ranges +
   constraints (proportions held during adjustment)
4. **Feedback loops** — declarative rules for cost / proportion
   responses

Plus an envelope (schema/catalog version + timestamps + validation
block) and a workspace block with arm-reach metadata derived from
the room bounds.

Defensive against partial graphs — design data in this repo is
JSONB and shapes vary across versions. The exporter tolerates
missing fields rather than raising; missing data shows up as
empty arrays and warning notes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.haptic import (
    GENERIC_MATERIAL_KEY,
    HAPTIC_CATALOG_VERSION,
    HAPTIC_SCHEMA_VERSION,
)
from app.haptic.catalog import (
    CatalogSnapshot,
    MaterialProfile,
    load_catalog_snapshot,
)
from app.haptic.validator import CoverageReport, validate_coverage
from app.models.orm import DesignGraphVersion


# ─────────────────────────────────────────────────────────────────────
# Graph extraction — pulls the bits of graph_data we care about.
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _ExtractedGraph:
    rooms: list[dict[str, Any]]
    objects: list[dict[str, Any]]
    materials_used: list[str]
    object_types_used: list[str]


def _to_mm(value: Any, *, assume_unit: str = "m") -> Optional[float]:
    """Coerce a number to millimetres.

    Design graphs in this codebase store dimensions in metres by
    convention (Stage 4 onward). When the value already looks like
    millimetres (>= 100) we leave it alone — best-effort heuristic
    for legacy graphs.
    """
    if value is None:
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num <= 0:
        return None
    if assume_unit == "mm":
        return num
    # assume_unit == "m"
    if num >= 100:
        # Already mm — leave alone.
        return num
    return num * 1000.0


def _pluck_dim(d: Any, key: str, *, assume_unit: str = "m") -> Optional[float]:
    if not isinstance(d, dict):
        return None
    return _to_mm(d.get(key), assume_unit=assume_unit)


def _pluck_material(obj: dict[str, Any]) -> Optional[str]:
    """Best-effort material key extraction from an object dict.

    Accepts:
      - ``material: "walnut"``
      - ``material: {"key": "walnut"}``
      - ``material: {"name": "walnut"}``
    """
    raw = obj.get("material")
    if isinstance(raw, str):
        return raw.strip().lower() or None
    if isinstance(raw, dict):
        for k in ("key", "id", "name", "slug"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip().lower()
    return None


def _pluck_object_type(obj: dict[str, Any]) -> Optional[str]:
    for k in ("type", "object_type", "category", "kind"):
        v = obj.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    return None


def _extract_graph(graph_data: dict[str, Any]) -> _ExtractedGraph:
    """Pull rooms + objects + material/object-type sets from a graph."""
    if not isinstance(graph_data, dict):
        return _ExtractedGraph([], [], [], [])

    raw_rooms = graph_data.get("rooms") or []
    raw_objects = graph_data.get("objects") or []
    if not isinstance(raw_rooms, list):
        raw_rooms = []
    if not isinstance(raw_objects, list):
        raw_objects = []

    rooms: list[dict[str, Any]] = []
    for r in raw_rooms:
        if not isinstance(r, dict):
            continue
        dims = r.get("dimensions") or r
        rooms.append({
            "id": str(r.get("id") or "") or None,
            "name": (r.get("name") or r.get("type") or "") or None,
            "width_mm":  _pluck_dim(dims, "width"),
            "depth_mm":  _pluck_dim(dims, "depth"),
            "height_mm": _pluck_dim(dims, "height"),
        })

    objects: list[dict[str, Any]] = []
    materials: list[str] = []
    object_types: list[str] = []
    for o in raw_objects:
        if not isinstance(o, dict):
            continue
        dims = o.get("dimensions") or {}
        position = o.get("position") or {}
        material_key = _pluck_material(o)
        object_type = _pluck_object_type(o)

        if material_key:
            materials.append(material_key)
        if object_type:
            object_types.append(object_type)

        objects.append({
            "id": str(o.get("id") or "") or None,
            "type": object_type,
            "material_key": material_key,
            "dimensions_mm": {
                "width":  _pluck_dim(dims, "width"),
                "depth":  _pluck_dim(dims, "depth"),
                "height": _pluck_dim(dims, "height"),
            },
            "position_mm": {
                "x": _pluck_dim(position, "x"),
                "y": _pluck_dim(position, "y"),
                "z": _pluck_dim(position, "z"),
            } if isinstance(position, dict) else None,
        })

    return _ExtractedGraph(
        rooms=rooms,
        objects=objects,
        materials_used=materials,
        object_types_used=object_types,
    )


# ─────────────────────────────────────────────────────────────────────
# Workspace — derived arm-reach metadata.
# ─────────────────────────────────────────────────────────────────────


def _compute_workspace(rooms: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate room bounds into one arm-workspace declaration.

    Returns the bounding box of all rooms in mm. Hardware drivers
    use this to confirm the haptic arm's physical reach is wide
    enough to cover the design at the chosen scale; if not, they
    pick a smaller display scale and re-map coordinates.
    """
    widths = [r["width_mm"] for r in rooms if r.get("width_mm")]
    depths = [r["depth_mm"] for r in rooms if r.get("depth_mm")]
    heights = [r["height_mm"] for r in rooms if r.get("height_mm")]
    return {
        "max_width_mm":  max(widths)  if widths  else None,
        "max_depth_mm":  max(depths)  if depths  else None,
        "max_height_mm": max(heights) if heights else None,
        "room_count": len(list(rooms)) if not isinstance(rooms, list) else len(rooms),
    }


# ─────────────────────────────────────────────────────────────────────
# Material payload assembly.
# ─────────────────────────────────────────────────────────────────────


def _resolve_material(
    catalog: CatalogSnapshot, material_key: str,
) -> tuple[MaterialProfile, bool]:
    """Look up the material; fall back to ``generic`` per BRD.

    Returns ``(profile, used_fallback)`` so the exporter can flag
    fallbacks in the payload.
    """
    profile = catalog.get_material(material_key)
    if profile is not None and profile.is_complete:
        return profile, False
    fallback = catalog.get_material(GENERIC_MATERIAL_KEY)
    if fallback is None:
        # Catalog seed missing entirely. Build a minimal profile so
        # the export doesn't crash; the validator will warn.
        return (
            MaterialProfile(material_key=GENERIC_MATERIAL_KEY),
            True,
        )
    # Note: the payload still records the *requested* material key
    # so vendors can see what was substituted.
    fallback_copy = MaterialProfile(
        material_key=material_key,
        texture=dict(fallback.texture or {}),
        thermal=dict(fallback.thermal or {}),
        friction=dict(fallback.friction or {}),
        firmness=dict(fallback.firmness or {}),
    )
    # Stamp the fallback in the texture block so a vendor parser
    # can detect substitution from the texture code alone.
    if fallback_copy.texture is not None:
        fallback_copy.texture = dict(fallback_copy.texture)
        fallback_copy.texture["fallback_for"] = material_key
    return fallback_copy, True


def _build_materials_block(
    catalog: CatalogSnapshot, materials_used: Iterable[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolved per-material profiles + the list of substituted keys."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    fallbacks: list[str] = []
    for raw in materials_used:
        key = (raw or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        profile, used_fallback = _resolve_material(catalog, key)
        out.append(profile.to_payload_dict())
        if used_fallback:
            fallbacks.append(key)
    return out, fallbacks


# ─────────────────────────────────────────────────────────────────────
# Interaction parameters block.
# ─────────────────────────────────────────────────────────────────────


def _build_interactions_block(
    catalog: CatalogSnapshot, objects: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-object adjustment metadata pulled from dimension rules.

    Skips objects whose ``type`` has no dimension rule (haptic still
    renders them, just statically — the validator records this).
    """
    out: list[dict[str, Any]] = []
    for o in objects:
        otype = (o.get("type") or "")
        rule = catalog.get_dimension_rule(otype)
        if rule is None:
            continue
        out.append({
            "object_id": o.get("id"),
            "object_type": otype,
            "adjustable_axes": list(rule["adjustable_axes"]),
            "ranges": dict(rule["ranges"]),
            "constraints": list(
                (rule.get("feedback_curve") or {}).get("constraints") or []
            ),
            "feedback_curve_kind": (
                (rule.get("feedback_curve") or {}).get("kind")
            ),
        })
    return out


# ─────────────────────────────────────────────────────────────────────
# Top-level orchestrator.
# ─────────────────────────────────────────────────────────────────────


@dataclass
class HapticExport:
    """Result of a successful build.

    The agent tool returns the ``payload`` dict directly. The
    ``coverage`` report is preserved on the dataclass for callers
    (e.g. tests or future ``haptic_export_artifacts`` writes) that
    want to inspect resolution outcomes without re-parsing the JSON.
    """

    payload: dict[str, Any]
    coverage: CoverageReport


async def build_haptic_payload(
    session: AsyncSession,
    *,
    graph_version: DesignGraphVersion,
    catalog: Optional[CatalogSnapshot] = None,
) -> HapticExport:
    """Assemble one haptic export payload from a saved graph version.

    Parameters
    ----------
    session:
        Async SQLAlchemy session used to load the catalog snapshot
        when ``catalog`` is not pre-supplied.
    graph_version:
        The :class:`DesignGraphVersion` to export. Ownership /
        access checks are the caller's responsibility.
    catalog:
        Optional pre-loaded catalog snapshot (used by tests to
        avoid round-tripping through the DB). Loaded fresh when
        omitted.

    Returns
    -------
    :class:`HapticExport`
        Wrapping the JSON-serialisable ``payload`` dict and the
        :class:`CoverageReport` describing material / dimension
        resolution outcomes.
    """
    if catalog is None:
        catalog = await load_catalog_snapshot(session)

    extracted = _extract_graph(dict(graph_version.graph_data or {}))

    materials_block, fallback_keys = _build_materials_block(
        catalog, extracted.materials_used,
    )
    interactions_block = _build_interactions_block(
        catalog, extracted.objects,
    )

    # Validator runs on the same key sets — we trust it as the
    # source of truth for the payload's ``validation`` block.
    coverage = validate_coverage(
        catalog=catalog,
        materials_used=extracted.materials_used,
        object_types_used=extracted.object_types_used,
    )
    # ``_build_materials_block`` and the validator agree on which
    # keys fell back. If they ever disagree (bug), we trust the
    # validator and warn.
    if sorted(fallback_keys) != sorted(coverage.fallback_materials):
        coverage.warnings.append(
            "exporter and validator disagreed on fallback set — "
            "using validator's view"
        )

    payload: dict[str, Any] = {
        # Envelope.
        "schema_version": HAPTIC_SCHEMA_VERSION,
        "catalog_version": HAPTIC_CATALOG_VERSION,
        "graph_version_id": graph_version.id,
        "project_id": graph_version.project_id,
        "design_version": int(graph_version.version or 0),
        "generated_at": datetime.now(timezone.utc).isoformat(),

        # Bucket 1 — Dimension data (BRD §Layer 7).
        "dimensions": {
            "rooms": list(extracted.rooms),
            "objects": list(extracted.objects),
        },

        # Bucket 2 — Material haptic properties (BRD §Layer 7).
        "materials": list(materials_block),

        # Bucket 3 — Interaction parameters (BRD §Layer 7).
        "interactions": list(interactions_block),

        # Bucket 4 — Feedback loops (BRD §Layer 7).
        "feedback_loops": list(catalog.feedback_loops),

        # Workspace metadata for arm-reach planning (BRD: "Width
        # sweep distances for arm movement").
        "workspace": _compute_workspace(extracted.rooms),

        # Validation outcome.
        "validation": coverage.to_payload_dict(),
    }

    return HapticExport(payload=payload, coverage=coverage)
