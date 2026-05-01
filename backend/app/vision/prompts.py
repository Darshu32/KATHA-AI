"""Stage 7 — purpose-specific vision prompts + JSON schemas.

Each of the 5 purposes carries:

- A ``system_prompt`` — the role the model plays.
- A ``user_template`` — the per-call instruction (formatted with
  any caller-supplied focus / context).
- An ``output_schema`` — a JSON schema for the structured output.
  Providers with native JSON-mode will round-trip cleanly; the
  stub returns canned fixtures matching the same shape.

We ship deliberate, structured shapes — the agent's downstream
tools rely on them. Loosening a schema is a breaking change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class PurposeSpec:
    purpose: str
    system_prompt: str
    user_template: str
    output_schema: dict[str, Any]


# ─────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────


_SITE_PHOTO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "orientation": {
            "type": "object",
            "properties": {
                "facing": {"type": "string"},  # north / south / east / west / unknown
                "confidence": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["facing", "confidence", "rationale"],
        },
        "surroundings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},  # building / street / vegetation / water / sky
                    "side": {"type": "string"},  # left / right / front / back / above
                    "note": {"type": "string"},
                },
                "required": ["kind", "side", "note"],
            },
        },
        "lighting": {"type": "string"},
        "vegetation": {
            "type": "array",
            "items": {"type": "string"},
        },
        "scale_clues": {
            "type": "array",
            "items": {"type": "string"},
        },
        "watch_outs": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "summary", "orientation", "surroundings",
        "lighting", "vegetation", "scale_clues", "watch_outs",
    ],
    "additionalProperties": False,
}


_AESTHETIC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "palette": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "hex": {"type": "string"},
                    "role": {"type": "string"},  # base / accent / highlight
                },
                "required": ["name", "role"],
            },
        },
        "materials": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},  # wood / metal / fabric / stone / etc.
                    "specifics": {"type": "string"},
                    "finish": {"type": "string"},
                },
                "required": ["category", "specifics", "finish"],
            },
        },
        "era_or_movement": {"type": "string"},
        "style_tags": {
            "type": "array",
            "items": {"type": "string"},
        },
        "signature_moves": {
            "type": "array",
            "items": {"type": "string"},
        },
        "watch_outs": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": [
        "summary", "palette", "materials", "era_or_movement",
        "style_tags", "signature_moves", "watch_outs",
    ],
    "additionalProperties": False,
}


_DESIGN_GRAPH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "confidence": {"type": "number"},
        "room": {
            "type": "object",
            "properties": {
                "type": {"type": "string"},
                "dimensions": {
                    "type": "object",
                    "properties": {
                        "length": {"type": "number"},
                        "width": {"type": "number"},
                        "height": {"type": "number"},
                    },
                },
                "label": {"type": "string"},
            },
            "required": ["type", "dimensions"],
        },
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string"},
                    "name": {"type": "string"},
                    "position": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"},
                            "z": {"type": "number"},
                        },
                    },
                    "dimensions": {
                        "type": "object",
                        "properties": {
                            "length": {"type": "number"},
                            "width": {"type": "number"},
                            "height": {"type": "number"},
                        },
                    },
                    "rotation_deg": {"type": "number"},
                },
                "required": ["id", "type"],
            },
        },
        "openings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},  # door / window / opening
                    "wall": {"type": "string"},  # north / south / east / west
                    "width_mm": {"type": "number"},
                    "position_normalised": {"type": "number"},
                },
                "required": ["kind", "wall"],
            },
        },
        "watch_outs": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["summary", "confidence", "room", "objects", "openings", "watch_outs"],
    "additionalProperties": False,
}


# ─────────────────────────────────────────────────────────────────────
# Per-purpose prompt specs
# ─────────────────────────────────────────────────────────────────────


_SITE_PHOTO_PROMPT = PurposeSpec(
    purpose="site_photo",
    system_prompt=(
        "You are an architect surveying a site from one or more photos. "
        "Read the image(s) carefully and produce a structured JSON report "
        "covering orientation, surroundings, lighting, vegetation, scale "
        "clues, and watch-outs. Be specific. Use cardinal directions where "
        "shadows or sun position make them inferable; otherwise mark "
        "facing as 'unknown' with a low confidence value. Do not invent "
        "context you can't see."
    ),
    user_template=(
        "Survey this site photo. {focus_addendum}"
    ),
    output_schema=_SITE_PHOTO_SCHEMA,
)


_REFERENCE_PROMPT = PurposeSpec(
    purpose="reference",
    system_prompt=(
        "You are a senior interior designer extracting the aesthetic from "
        "a reference image. Read the image and return a structured JSON "
        "summary of the palette, materials, era / movement, style tags, "
        "signature moves, and watch-outs. Cite hex codes when colour is "
        "discernible. Be conservative — if you can't tell whether a "
        "surface is oak or walnut, say 'medium-tone hardwood' rather "
        "than guess."
    ),
    user_template=(
        "Extract the aesthetic from this reference. {focus_addendum}"
    ),
    output_schema=_AESTHETIC_SCHEMA,
)


_MOOD_BOARD_PROMPT = PurposeSpec(
    purpose="mood_board",
    system_prompt=(
        "You are a senior interior designer reading a mood board (multiple "
        "reference images presented together). Synthesise their *common* "
        "aesthetic into one structured JSON brief: palette, materials, era, "
        "style tags, signature moves. Where the images conflict, weight by "
        "frequency and call the conflict out under watch-outs. Do not "
        "summarise each image individually — produce ONE brief."
    ),
    user_template=(
        "Synthesise the mood board into one aesthetic brief. {focus_addendum}"
    ),
    output_schema=_AESTHETIC_SCHEMA,
)


_HAND_SKETCH_PROMPT = PurposeSpec(
    purpose="hand_sketch",
    system_prompt=(
        "You are an architect translating a hand sketch into a structured "
        "DesignGraph. Read the sketch, infer room shape + dimensions "
        "(metres), identify furniture / fixture objects with positions, "
        "and locate openings (doors, windows). Use sensible defaults where "
        "the sketch is ambiguous, and report confidence honestly. List "
        "anything you had to guess in watch_outs. Coordinate convention: "
        "x = horizontal, z = depth (both metres, room corner at origin)."
    ),
    user_template=(
        "Convert this hand sketch into a DesignGraph. {focus_addendum}"
    ),
    output_schema=_DESIGN_GRAPH_SCHEMA,
)


_EXISTING_FLOOR_PLAN_PROMPT = PurposeSpec(
    purpose="existing_floor_plan",
    system_prompt=(
        "You are a draughtsperson digitising a printed floor plan into a "
        "structured DesignGraph. Read the plan: extract room dimensions "
        "(metres), labelled object positions, openings (doors/windows) "
        "with widths and wall positions. The plan is an authoritative "
        "source — be precise, not creative. Anything illegible or "
        "ambiguous goes in watch_outs."
    ),
    user_template=(
        "Digitise this floor plan into a DesignGraph. {focus_addendum}"
    ),
    output_schema=_DESIGN_GRAPH_SCHEMA,
)


_PROMPTS: dict[str, PurposeSpec] = {
    "site_photo": _SITE_PHOTO_PROMPT,
    "reference": _REFERENCE_PROMPT,
    "mood_board": _MOOD_BOARD_PROMPT,
    "hand_sketch": _HAND_SKETCH_PROMPT,
    "existing_floor_plan": _EXISTING_FLOOR_PLAN_PROMPT,
}

SUPPORTED_PURPOSES: tuple[str, ...] = tuple(_PROMPTS.keys())


def prompt_for_purpose(
    purpose: str,
    *,
    focus: str = "",
) -> PurposeSpec:
    """Return the :class:`PurposeSpec` for ``purpose``.

    ``focus`` is optional caller-supplied context ("Pay attention to
    the kitchen island geometry") that gets folded into the user
    message.

    Raises :class:`KeyError` for unknown purposes — the caller (the
    agent tool layer) validates the slug before getting here.
    """
    spec = _PROMPTS.get(purpose)
    if spec is None:
        raise KeyError(
            f"Unknown vision purpose {purpose!r}. "
            f"Allowed: {SUPPORTED_PURPOSES}"
        )

    addendum = f" Focus areas: {focus}." if focus else ""
    return PurposeSpec(
        purpose=spec.purpose,
        system_prompt=spec.system_prompt,
        user_template=spec.user_template.format(focus_addendum=addendum).strip(),
        output_schema=spec.output_schema,
    )
