"""Read-side access to the haptic catalog tables.

The catalog is small (~12 materials × 4 property tables = ~50 rows
total, plus ~8 dimension rules and ~10 feedback loops). For the
exporter we eager-load the lot per call — there's no point doing
clever per-material lookups when the entire catalog fits in a
couple of small SELECTs.

All public functions are async and take an :class:`AsyncSession`.
None of them mutate the DB — pure reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    HapticDimensionRule,
    HapticFeedbackLoop,
    HapticFirmness,
    HapticFriction,
    HapticTexture,
    HapticThermal,
)


# ─────────────────────────────────────────────────────────────────────
# Composite material profile — the unit the exporter actually wants.
# ─────────────────────────────────────────────────────────────────────


@dataclass
class MaterialProfile:
    """All four haptic aspects for one material.

    A profile is *complete* when every aspect resolves. The validator
    treats partial profiles (e.g. a material with friction but no
    thermal) as missing — the haptic arm needs all four to feel
    right, so we don't half-attach data.
    """

    material_key: str
    texture: Optional[dict[str, Any]] = None      # {code, name, signature_data}
    thermal: Optional[dict[str, Any]] = None      # {temperature_celsius, source}
    friction: Optional[dict[str, Any]] = None     # {coefficient, condition}
    firmness: Optional[dict[str, Any]] = None     # {firmness_scale, density}

    @property
    def is_complete(self) -> bool:
        return all(
            x is not None
            for x in (self.texture, self.thermal, self.friction, self.firmness)
        )

    def to_payload_dict(self) -> dict[str, Any]:
        """Shape used by the export payload (per ``docs/haptic/...``)."""
        return {
            "key": self.material_key,
            "texture": dict(self.texture or {}),
            "thermal": dict(self.thermal or {}),
            "friction": dict(self.friction or {}),
            "firmness": dict(self.firmness or {}),
        }


# ─────────────────────────────────────────────────────────────────────
# Catalog snapshot — preloaded for one export.
# ─────────────────────────────────────────────────────────────────────


@dataclass
class CatalogSnapshot:
    """One in-memory copy of the entire haptic catalog.

    The exporter loads this once at the start of a build, then hits
    its dicts instead of re-querying for every material. Cheap
    because the catalog is small; deterministic because the snapshot
    is taken at one point in time.
    """

    materials: dict[str, MaterialProfile] = field(default_factory=dict)
    dimension_rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    feedback_loops: list[dict[str, Any]] = field(default_factory=list)

    def get_material(self, key: str) -> Optional[MaterialProfile]:
        return self.materials.get((key or "").strip().lower())

    def get_dimension_rule(self, object_type: str) -> Optional[dict[str, Any]]:
        return self.dimension_rules.get((object_type or "").strip().lower())


# ─────────────────────────────────────────────────────────────────────
# Loaders — one per table, plus a top-level snapshot loader.
# ─────────────────────────────────────────────────────────────────────


async def _load_textures(session: AsyncSession) -> dict[str, dict[str, Any]]:
    rows = (await session.execute(select(HapticTexture))).scalars().all()
    return {
        r.material_id: {
            "code": r.code,
            "name": r.name,
            "signature_data": dict(r.signature_data or {}),
        }
        for r in rows
    }


async def _load_thermal(session: AsyncSession) -> dict[str, dict[str, Any]]:
    rows = (await session.execute(select(HapticThermal))).scalars().all()
    return {
        r.material_id: {
            "temperature_celsius": float(r.temperature_celsius),
            "source": r.source or "",
        }
        for r in rows
    }


async def _load_friction(session: AsyncSession) -> dict[str, dict[str, Any]]:
    rows = (await session.execute(select(HapticFriction))).scalars().all()
    return {
        r.material_id: {
            "coefficient": float(r.coefficient),
            "condition": r.condition or "dry_room_temp",
        }
        for r in rows
    }


async def _load_firmness(session: AsyncSession) -> dict[str, dict[str, Any]]:
    rows = (await session.execute(select(HapticFirmness))).scalars().all()
    return {
        r.material_id: {
            "firmness_scale": r.firmness_scale or "medium",
            "density_kg_m3": float(r.density or 0.0),
        }
        for r in rows
    }


async def _load_dimension_rules(
    session: AsyncSession,
) -> dict[str, dict[str, Any]]:
    rows = (
        await session.execute(select(HapticDimensionRule))
    ).scalars().all()
    return {
        r.object_type: {
            "object_type": r.object_type,
            "adjustable_axes": list(r.adjustable_axes or []),
            "ranges": dict(r.ranges or {}),
            "feedback_curve": dict(r.feedback_curve or {}),
        }
        for r in rows
    }


async def _load_feedback_loops(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(HapticFeedbackLoop).order_by(HapticFeedbackLoop.rule_key)
        )
    ).scalars().all()
    return [
        {
            "rule_key": r.rule_key,
            "trigger": dict(r.trigger or {}),
            "response": dict(r.response or {}),
            "formula": r.formula or "",
        }
        for r in rows
    ]


async def load_catalog_snapshot(session: AsyncSession) -> CatalogSnapshot:
    """Load every haptic catalog table into one in-memory snapshot.

    Used by the exporter at the start of every build. Idempotent
    and side-effect-free — safe to call repeatedly within one
    request.
    """
    textures = await _load_textures(session)
    thermal = await _load_thermal(session)
    friction = await _load_friction(session)
    firmness = await _load_firmness(session)
    dim_rules = await _load_dimension_rules(session)
    loops = await _load_feedback_loops(session)

    # Materials = union of keys across all four property tables.
    keys: set[str] = set(textures) | set(thermal) | set(friction) | set(firmness)
    materials: dict[str, MaterialProfile] = {}
    for key in keys:
        materials[key] = MaterialProfile(
            material_key=key,
            texture=textures.get(key),
            thermal=thermal.get(key),
            friction=friction.get(key),
            firmness=firmness.get(key),
        )

    return CatalogSnapshot(
        materials=materials,
        dimension_rules=dim_rules,
        feedback_loops=loops,
    )


# ─────────────────────────────────────────────────────────────────────
# Convenience read APIs (for the discovery / inspection use cases).
# ─────────────────────────────────────────────────────────────────────


async def get_material_profile(
    session: AsyncSession, *, material_key: str,
) -> Optional[MaterialProfile]:
    """Single-material lookup. Returns ``None`` if not in catalog."""
    snapshot = await load_catalog_snapshot(session)
    return snapshot.get_material(material_key)


async def list_material_keys(session: AsyncSession) -> list[str]:
    """All material keys with a complete profile in the catalog."""
    snapshot = await load_catalog_snapshot(session)
    return sorted(
        k for k, p in snapshot.materials.items() if p.is_complete
    )
