"""Stage 7 — vision pipeline.

The agent's vision tools live in :mod:`app.agents.tools.vision`.
This package provides the underlying abstraction:

- :class:`VisionProvider` — async ABC. Two implementations:
  :class:`AnthropicVisionProvider` (Claude Vision; production) and
  :class:`StubVisionProvider` (deterministic; tests).
- :func:`get_vision_provider` — factory keyed on settings.
- :func:`prompt_for_purpose` — selects the system prompt + JSON
  output schema for one of the 5 supported purposes.
- :class:`VisionAnalyzer` — orchestrator: load asset → call provider
  with the right prompt → parse JSON output.

The 5 purposes
--------------
- ``site_photo`` — site survey reads (orientation, surroundings,
  vegetation, lighting, scale clues).
- ``reference`` — mood / aesthetic extraction (palette, materials,
  era, style tags).
- ``mood_board`` — multi-image aesthetic synthesis (treats inputs
  as a set; same shape as ``reference``).
- ``hand_sketch`` — sketch → structured DesignGraph (rough room
  shape, objects, dimensions).
- ``existing_floor_plan`` — printed plan → DesignGraph (labels,
  dimensions, openings).
"""

from app.vision.analyzer import VisionAnalyzer, VisionAnalyzeError
from app.vision.anthropic_vision import AnthropicVisionProvider
from app.vision.base import (
    VisionError,
    VisionProvider,
    VisionRequest,
    VisionResult,
)
from app.vision.factory import get_vision_provider
from app.vision.prompts import (
    SUPPORTED_PURPOSES,
    PurposeSpec,
    prompt_for_purpose,
)
from app.vision.stub import StubVisionProvider

__all__ = [
    "AnthropicVisionProvider",
    "PurposeSpec",
    "SUPPORTED_PURPOSES",
    "StubVisionProvider",
    "VisionAnalyzeError",
    "VisionAnalyzer",
    "VisionError",
    "VisionProvider",
    "VisionRequest",
    "VisionResult",
    "get_vision_provider",
    "prompt_for_purpose",
]
