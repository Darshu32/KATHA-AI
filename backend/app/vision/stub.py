"""Stub vision provider — deterministic fixtures for tests.

Returns canned-but-shape-correct results per purpose. Tests can
override individual fixtures by passing ``fixtures={"site_photo":
{...}}`` to the constructor.

Why this lives in production code (not just tests)
---------------------------------------------------
- Same import path used in dev environments without an Anthropic key.
- Tests inject this provider into :class:`VisionAnalyzer` via the
  ``provider=`` kwarg.
- Schema sketches (the ``parsed`` dicts below) double as docs of
  what the real model is expected to produce.
"""

from __future__ import annotations

from typing import Any, Optional

from app.vision.base import (
    VisionError,
    VisionProvider,
    VisionRequest,
    VisionResult,
)


_DEFAULT_FIXTURES: dict[str, dict[str, Any]] = {
    "site_photo": {
        "summary": "Stub site survey",
        "orientation": {
            "facing": "south",
            "confidence": 0.4,
            "rationale": "stub — shadows not analysed",
        },
        "surroundings": [
            {"kind": "building", "side": "left", "note": "low-rise residential"},
            {"kind": "vegetation", "side": "front", "note": "mature tree, ~6m"},
        ],
        "lighting": "midday, hard light",
        "vegetation": ["mature tree", "shrubs"],
        "scale_clues": ["parked car ~4.5m"],
        "watch_outs": ["stub fixture — not real analysis"],
    },
    "reference": {
        "summary": "Stub aesthetic extraction",
        "palette": [
            {"name": "warm walnut", "hex": "#5C3D2E", "role": "base"},
            {"name": "ivory", "hex": "#F4EDE0", "role": "accent"},
        ],
        "materials": [
            {"category": "wood", "specifics": "walnut", "finish": "oiled"},
            {"category": "metal", "specifics": "brass", "finish": "antique"},
        ],
        "era_or_movement": "mid-century modern",
        "style_tags": ["warm minimal", "tactile", "earth tones"],
        "signature_moves": ["tapered legs", "exposed grain"],
        "watch_outs": ["stub fixture"],
    },
    "mood_board": {
        "summary": "Stub mood-board synthesis",
        "palette": [
            {"name": "linen", "hex": "#E6DFCF", "role": "base"},
            {"name": "olive", "hex": "#5A6B3C", "role": "accent"},
        ],
        "materials": [
            {"category": "fabric", "specifics": "linen", "finish": "natural"},
            {"category": "wood", "specifics": "oak", "finish": "white-washed"},
        ],
        "era_or_movement": "contemporary scandinavian",
        "style_tags": ["calm", "natural"],
        "signature_moves": ["soft contrasts"],
        "watch_outs": ["stub fixture"],
    },
    "hand_sketch": {
        "summary": "Stub sketch → DesignGraph",
        "confidence": 0.3,
        "room": {
            "type": "living_room",
            "dimensions": {"length": 5.0, "width": 4.0, "height": 2.7},
            "label": "Living room (sketch)",
        },
        "objects": [
            {
                "id": "obj-1", "type": "sofa", "name": "Sofa",
                "position": {"x": 1.0, "z": 1.5},
                "dimensions": {"length": 2.2, "width": 0.9, "height": 0.85},
                "rotation_deg": 0,
            },
        ],
        "openings": [
            {"kind": "door", "wall": "north", "width_mm": 900, "position_normalised": 0.5},
        ],
        "watch_outs": ["stub fixture — placeholder room", "rough dimensions"],
    },
    "existing_floor_plan": {
        "summary": "Stub floor-plan digitisation",
        "confidence": 0.6,
        "room": {
            "type": "bedroom",
            "dimensions": {"length": 4.2, "width": 3.4, "height": 2.7},
            "label": "Bedroom (existing)",
        },
        "objects": [
            {
                "id": "obj-1", "type": "bed", "name": "Bed",
                "position": {"x": 0.5, "z": 0.3},
                "dimensions": {"length": 1.9, "width": 1.5, "height": 0.6},
                "rotation_deg": 0,
            },
        ],
        "openings": [
            {"kind": "door", "wall": "east", "width_mm": 850, "position_normalised": 0.4},
            {"kind": "window", "wall": "south", "width_mm": 1500, "position_normalised": 0.5},
        ],
        "watch_outs": ["stub fixture"],
    },
}


class StubVisionProvider(VisionProvider):
    """Deterministic vision stub for tests + offline dev."""

    name = "stub_vision"

    def __init__(
        self,
        *,
        fixtures: Optional[dict[str, dict[str, Any]]] = None,
    ) -> None:
        self._fixtures = dict(_DEFAULT_FIXTURES)
        if fixtures:
            self._fixtures.update(fixtures)

    def set_fixture(self, purpose: str, payload: dict[str, Any]) -> None:
        """Replace one fixture — used in tests to drive a specific case."""
        self._fixtures[purpose] = dict(payload)

    async def analyze(self, request: VisionRequest) -> VisionResult:
        if not request.images:
            raise VisionError("StubVisionProvider received no images")

        purpose = request.purpose or ""
        parsed = self._fixtures.get(purpose)
        if parsed is None:
            # No fixture for this purpose — return a sensible empty
            # shape so downstream parsers don't crash.
            parsed = {"summary": f"Stub: no fixture for purpose {purpose!r}"}

        return VisionResult(
            parsed=dict(parsed),
            raw_text="(stub)",
            model="stub",
            provider_name=self.name,
            input_tokens=0,
            output_tokens=0,
        )
