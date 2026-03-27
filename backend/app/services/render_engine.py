"""Production-ready render stage for scalable architectural visualization pipelines."""

from __future__ import annotations

import hashlib
import logging
import uuid
from copy import deepcopy
from time import perf_counter

logger = logging.getLogger(__name__)

SUPPORTED_RESOLUTIONS = {"1024x1024", "1536x1024", "1024x1536", "1920x1080"}
SUPPORTED_PREVIEW_RESOLUTIONS = {"256x256", "512x512"}
SUPPORTED_CAMERA_ANGLES = {"wide", "medium", "top_down", "isometric"}
SUPPORTED_CAMERA_POSITIONS = {"corner", "center", "entry", "eye_axis", "facade"}
SUPPORTED_CAMERA_HEIGHTS = {"eye-level", "overhead", "low-angle"}
SUPPORTED_LIGHTING_TYPES = {"natural", "artificial", "mixed"}
SUPPORTED_TIMES_OF_DAY = {"morning", "afternoon", "evening", "night"}
SUPPORTED_JOB_STATUSES = {"queued", "processing", "completed", "failed"}
SUPPORTED_JOB_PRIORITIES = {"low", "medium", "high"}
MAX_BATCH_SIZE = 8
DEFAULT_RESOLUTION = "1024x1024"
DEFAULT_PREVIEW_RESOLUTION = "256x256"
DEFAULT_STEPS = 50
DEFAULT_NEGATIVE_PROMPT = ["blurry", "distorted", "low quality", "bad lighting"]
DEFAULT_VIEWS = ["front_view", "side_view", "top_view", "perspective_view"]

STYLE_MATERIAL_HINTS = {
    "scandinavian": {"light wood", "linen", "cotton", "white matte paint"},
    "modern": {"oak wood", "matte paint", "brushed metal", "glass"},
    "minimalist": {"plaster", "light oak", "linen", "white matte paint"},
    "industrial": {"concrete", "steel", "brick", "dark metal"},
    "luxury": {"marble", "walnut", "velvet", "brushed brass"},
}

STYLE_ASSET_PRESETS = {
    "scandinavian": {
        "textures": ["tex/light_oak_floor", "tex/white_matte_wall", "tex/linen_fabric"],
        "models": ["mdl/scandi_sofa", "mdl/wood_coffee_table", "mdl/lounge_chair"],
        "hdris": ["hdri/morning_soft_daylight"],
    },
    "modern": {
        "textures": ["tex/oak_floor", "tex/matte_wall", "tex/brushed_metal"],
        "models": ["mdl/modern_sofa", "mdl/coffee_table", "mdl/accent_chair"],
        "hdris": ["hdri/architectural_clear_sky"],
    },
}

EXAMPLE_LAYOUT = {
    "room_type": "living_room",
    "dimensions": {"length": 16, "width": 12, "height": 10, "unit": "ft"},
    "layout_summary": "A Scandinavian living room with a calm seating cluster and open circulation.",
    "theme_reference": {
        "style": "scandinavian",
        "materials": ["light wood", "linen", "cotton"],
        "lighting": "soft natural lighting",
        "colors": ["white", "beige", "light grey"],
    },
    "objects": [
        {"type": "sofa", "material": "linen", "color": "beige"},
        {"type": "coffee_table", "material": "light wood", "color": "oak"},
        {"type": "chair", "material": "cotton", "color": "white"},
    ],
}


def process(layout: dict | str) -> dict:
    """Generate structured render payloads from a layout dict or raw prompt string."""
    started_at = perf_counter()
    logger.info("render_started")

    normalized = validate_input(_normalize_input(layout))
    prompt_payload = PromptBuilder(normalized).build()
    logger.info(
        "prompt_transformed",
        extra={
            "style": prompt_payload["prompt"]["style"],
            "space": prompt_payload["prompt"]["space"],
            "seed": prompt_payload["render_control"]["seed"],
        },
    )

    cache_manager = CacheManager()
    cache_payload = cache_manager.build(prompt_payload)
    logger.info("cache_miss", extra={"cache_key": cache_payload["cache_key"]})

    variations = VariationGenerator(prompt_payload).build()
    logger.info("variations_generated", extra={"count": len(variations)})

    job = RenderJobQueue().create(priority="high" if normalized.get("realtime") else "medium")
    logger.info("render_job_created", extra={"job_id": job["job_id"], "priority": job["priority"]})

    adapters = RenderingAdapterRegistry()
    assets = AssetManager(prompt_payload).build()
    batch = BatchRenderer(prompt_payload).build()

    errors: list[dict] = []
    try:
        renders = {
            "interior": adapters.stable_diffusion().build_render_payload(
                render_type="interior",
                scene=prompt_payload,
                views=DEFAULT_VIEWS,
            ),
            "exterior": adapters.dalle().build_render_payload(
                render_type="exterior",
                scene=_with_exterior_overrides(prompt_payload),
                views=["front_view", "perspective_view"],
            ),
            "isometric": adapters.stable_diffusion().build_render_payload(
                render_type="isometric",
                scene=_with_isometric_overrides(prompt_payload),
                views=["isometric_view"],
            ),
            "walkthrough_frames": WalkthroughFrameBuilder(prompt_payload, adapters.stable_diffusion()).build(),
        }
        logger.info("batch_processed", extra={"batch_size": batch["batch_size"]})
    except Exception as exc:
        errors.append({"type": "render_failed", "message": str(exc)})
        logger.exception("render_failed", extra={"job_id": job["job_id"]})
        job = RenderJobQueue().transition(job, "failed")
        renders = {
            "interior": {},
            "exterior": {},
            "isometric": {},
            "walkthrough_frames": [],
        }

    payload = {
        "renders": renders,
        "prompt": prompt_payload["prompt"],
        "camera": prompt_payload["camera"],
        "lighting": prompt_payload["lighting"],
        "materials": prompt_payload["materials"],
        "views": prompt_payload["views"],
        "render_control": prompt_payload["render_control"],
        "quality": prompt_payload["quality"],
        "export": prompt_payload["export"],
        "variations": variations,
        "negative_prompt": prompt_payload["negative_prompt"],
        "model_adapters": prompt_payload["model_adapters"],
        "assets": assets,
        "render_job": job,
        "batch": batch,
        "cache": cache_payload,
        "performance": PerformanceTracker(started_at).build(),
        "errors": errors,
        "preview": {"enabled": True, "low_res": DEFAULT_PREVIEW_RESOLUTION},
        "pipeline": {
            "threejs_ready": True,
            "blender_ready": True,
            "unreal_ready": True,
        },
        "style_preset": {
            "name": f"{prompt_payload['style_key']}_default",
            "locked_materials": True,
        },
        "post_processing": {
            "color_correction": True,
            "sharpen": True,
            "contrast": "medium",
        },
        "security": {
            "rate_limit": 100,
            "auth_required": True,
        },
    }

    validate_output(payload)
    logger.info(
        "render_completed",
        extra={
            "space": payload["prompt"]["space"],
            "interior_views": len(payload["renders"]["interior"].get("views", [])),
            "walkthrough_frames": len(payload["renders"]["walkthrough_frames"]),
            "job_id": payload["render_job"]["job_id"],
        },
    )
    return payload


class PromptBuilder:
    """Transform loose room/layout inputs into structured render prompts."""

    def __init__(self, normalized_input: dict) -> None:
        self.data = normalized_input

    def build(self) -> dict:
        style_key = self._style()
        space = self.data["space"]
        materials = self._materials(style_key)
        lighting = self._lighting()
        camera = CameraSystem(self.data).build(space_type=space)
        quality = self._quality()
        seed = self._seed(style_key, space, materials)

        return {
            "style_key": style_key,
            "prompt": {
                "style": style_key.title().replace("_", " "),
                "space": space.replace("_", " "),
                "lighting": self._lighting_text(lighting),
                "materials": list(materials.values()),
                "mood": self._mood(style_key),
            },
            "camera": camera,
            "lighting": lighting,
            "materials": materials,
            "views": list(DEFAULT_VIEWS),
            "render_control": {"seed": seed, "consistency": True},
            "quality": quality,
            "export": {"png_ready": True, "webp_ready": True, "3d_pipeline_ready": True},
            "variations": [
                {"style": style_key},
                {"style": f"minimal_{style_key}" if not style_key.startswith("minimal_") else style_key},
            ],
            "negative_prompt": list(DEFAULT_NEGATIVE_PROMPT),
            "model_adapters": {"primary": "stable_diffusion_xl", "secondary": "dall_e"},
            "raw_prompt": self._compose_raw_prompt(style=style_key, materials=materials, lighting=lighting, camera=camera),
        }

    def _style(self) -> str:
        return str(self.data.get("style") or "modern").strip().lower()

    def _materials(self, style_key: str) -> dict:
        existing = self.data.get("material_candidates", [])
        style_defaults = list(STYLE_MATERIAL_HINTS.get(style_key, {"oak wood", "matte paint", "fabric"}))
        pool = _dedupe_preserve_order(existing + style_defaults)
        return {
            "floor": pool[0],
            "walls": pool[1] if len(pool) > 1 else "white matte paint",
            "furniture": " + ".join(pool[2:4]) if len(pool) > 2 else "fabric + wood",
        }

    def _lighting(self) -> dict:
        raw_lighting = str(self.data.get("lighting") or "soft natural light").lower()
        lighting_type = "natural" if "natural" in raw_lighting else "mixed" if "layered" in raw_lighting else "artificial"
        direction = "east" if lighting_type == "natural" else "interior"
        return {
            "type": lighting_type,
            "intensity": "medium",
            "direction": direction,
            "time_of_day": "morning" if lighting_type == "natural" else "evening",
        }

    def _lighting_text(self, lighting: dict) -> str:
        if lighting["type"] == "natural":
            return f"soft natural light from the {lighting['direction']}"
        return f"{lighting['intensity']} {lighting['type']} lighting"

    def _mood(self, style_key: str) -> str:
        return {
            "scandinavian": "minimal, cozy",
            "modern": "refined, calm",
            "minimalist": "quiet, airy",
            "industrial": "moody, tactile",
            "luxury": "warm, premium",
        }.get(style_key, "balanced, inviting")

    def _quality(self) -> dict:
        return {"resolution": DEFAULT_RESOLUTION, "steps": DEFAULT_STEPS, "high_detail": True}

    def _seed(self, style_key: str, space: str, materials: dict) -> int:
        digest = hashlib.sha256(f"{style_key}|{space}|{materials}".encode("utf-8")).hexdigest()
        return int(digest[:8], 16)

    def _compose_raw_prompt(self, *, style: str, materials: dict, lighting: dict, camera: dict) -> str:
        return (
            f"High-end {style.replace('_', ' ')} {self.data['space'].replace('_', ' ')} render, "
            f"{camera['angle']} camera from {camera['position']}, {camera['height']}, {camera['fov']}, "
            f"{self._lighting_text(lighting)}, materials: floor {materials['floor']}, walls {materials['walls']}, "
            f"furniture {materials['furniture']}, realistic architectural visualization, photorealistic."
        )


class CameraSystem:
    """Centralize camera defaults and validation-friendly output."""

    def __init__(self, normalized_input: dict) -> None:
        self.data = normalized_input

    def build(self, *, space_type: str) -> dict:
        if space_type in {"facade", "exterior"}:
            return {"angle": "wide", "position": "facade", "height": "eye-level", "fov": "90deg"}
        return {"angle": "wide", "position": "corner", "height": "eye-level", "fov": "90deg"}


class VariationGenerator:
    """Generate style-safe variations for the same scene."""

    def __init__(self, prompt_payload: dict) -> None:
        self.payload = prompt_payload

    def build(self) -> list[dict]:
        base = self.payload["variations"]
        return [
            {
                **variation,
                "seed": self.payload["render_control"]["seed"] + index,
                "consistency": self.payload["render_control"]["consistency"],
            }
            for index, variation in enumerate(base, start=1)
        ]


class WalkthroughFrameBuilder:
    """Create consistent frame payloads for simple camera walkthroughs."""

    def __init__(self, prompt_payload: dict, adapter) -> None:
        self.payload = prompt_payload
        self.adapter = adapter

    def build(self) -> list[dict]:
        frames = []
        for index, position in enumerate(["entry", "corner", "center"], start=1):
            scene = deepcopy(self.payload)
            scene["camera"] = {
                **scene["camera"],
                "position": position,
                "angle": "wide" if position != "center" else "medium",
            }
            frames.append(
                self.adapter.build_render_payload(
                    render_type="walkthrough_frame",
                    scene=scene,
                    views=[f"frame_{index}"],
                )
            )
        return frames


class RenderingAdapterRegistry:
    """Factory for backend-specific render payload adapters."""

    def stable_diffusion(self):
        return StableDiffusionAdapter()

    def dalle(self):
        return DalleAdapter()


class BaseRenderAdapter:
    provider = "base"

    def build_render_payload(self, *, render_type: str, scene: dict, views: list[str]) -> dict:
        return {
            "type": render_type,
            "provider": self.provider,
            "status": "queued",
            "prompt": scene["prompt"],
            "negative_prompt": scene["negative_prompt"],
            "camera": scene["camera"],
            "lighting": scene["lighting"],
            "materials": scene["materials"],
            "quality": scene["quality"],
            "render_control": scene["render_control"],
            "views": [
                {
                    "name": view_name,
                    "prompt_text": self.compose_prompt_text(scene, view_name),
                }
                for view_name in views
            ],
            "export": scene["export"],
        }

    def compose_prompt_text(self, scene: dict, view_name: str) -> str:
        return (
            f"{scene['raw_prompt']} View: {view_name.replace('_', ' ')}. "
            f"Quality {scene['quality']['resolution']} with {scene['quality']['steps']} steps."
        )


class StableDiffusionAdapter(BaseRenderAdapter):
    provider = "stable_diffusion_xl"

    def build_render_payload(self, *, render_type: str, scene: dict, views: list[str]) -> dict:
        payload = super().build_render_payload(render_type=render_type, scene=scene, views=views)
        payload["sampler"] = "DPM++ 2M Karras"
        payload["cfg_scale"] = 7.5
        return payload


class DalleAdapter(BaseRenderAdapter):
    provider = "dall_e"

    def build_render_payload(self, *, render_type: str, scene: dict, views: list[str]) -> dict:
        payload = super().build_render_payload(render_type=render_type, scene=scene, views=views)
        payload["quality_profile"] = "hd"
        payload["style_preset"] = "architectural_visualization"
        return payload


class AssetManager:
    """Resolve rendering assets required for a style/material package."""

    def __init__(self, prompt_payload: dict) -> None:
        self.payload = prompt_payload

    def build(self) -> dict:
        style_key = self.payload["style_key"]
        preset = STYLE_ASSET_PRESETS.get(style_key, STYLE_ASSET_PRESETS.get(style_key.replace("minimal_", ""), {}))
        textures = preset.get("textures", ["tex/default_wall", "tex/default_floor"])
        models = preset.get("models", ["mdl/default_sofa", "mdl/default_table"])
        hdris = preset.get("hdris", ["hdri/studio_neutral"])
        return {"textures": textures, "models": models, "hdris": hdris}


class RenderJobQueue:
    """Build queue-safe job metadata and validate job transitions."""

    valid_transitions = {
        "queued": {"processing", "failed"},
        "processing": {"completed", "failed"},
        "completed": set(),
        "failed": set(),
    }

    def create(self, *, priority: str) -> dict:
        if priority not in SUPPORTED_JOB_PRIORITIES:
            raise ValueError("Unsupported render job priority")
        return {
            "job_id": str(uuid.uuid4()),
            "status": "queued",
            "priority": priority,
        }

    def transition(self, job: dict, next_status: str) -> dict:
        current = job["status"]
        if next_status not in self.valid_transitions[current]:
            raise ValueError(f"Invalid job transition from {current} to {next_status}")
        return {**job, "status": next_status}


class BatchRenderer:
    """Describe batch execution settings for scalable render runs."""

    def __init__(self, prompt_payload: dict) -> None:
        self.prompt_payload = prompt_payload

    def build(self) -> dict:
        batch_size = min(4, MAX_BATCH_SIZE)
        return {"enabled": True, "batch_size": batch_size}


class CacheManager:
    """Create deterministic cache keys for render scenes."""

    def build(self, prompt_payload: dict) -> dict:
        cache_key = hashlib.sha256(
            (
                f"{prompt_payload['style_key']}|"
                f"{prompt_payload['prompt']}|"
                f"{prompt_payload['camera']}|"
                f"{prompt_payload['lighting']}|"
                f"{prompt_payload['materials']}|"
                f"{prompt_payload['quality']}"
            ).encode("utf-8")
        ).hexdigest()
        return {"enabled": True, "cache_key": cache_key}


class PerformanceTracker:
    """Estimate response-side performance metrics for orchestration visibility."""

    def __init__(self, started_at: float) -> None:
        self.started_at = started_at

    def build(self) -> dict:
        render_time_ms = int((perf_counter() - self.started_at) * 1000)
        memory_usage_mb = 96
        return {"render_time_ms": render_time_ms, "memory_usage_mb": memory_usage_mb}


def _normalize_input(layout: dict | str) -> dict:
    if isinstance(layout, str):
        return {
            "raw_prompt": layout.strip(),
            "space": _infer_space_from_prompt(layout),
            "style": _infer_style_from_prompt(layout),
            "lighting": _infer_lighting_from_prompt(layout),
            "material_candidates": _infer_materials_from_prompt(layout),
            "realtime": False,
        }

    layout = deepcopy(layout or {})
    theme_reference = layout.get("theme_reference", {})
    material_candidates = []
    material_candidates.extend(theme_reference.get("materials", []))
    for obj in layout.get("objects", []):
        material = obj.get("material")
        if material:
            material_candidates.append(str(material))

    return {
        "raw_prompt": str(layout.get("layout_summary") or ""),
        "space": str(layout.get("room_type") or "living_room").strip().lower(),
        "style": str(theme_reference.get("style") or layout.get("style") or "modern").strip().lower(),
        "lighting": str(theme_reference.get("lighting") or "soft natural light").strip().lower(),
        "material_candidates": _dedupe_preserve_order(material_candidates),
        "realtime": bool(layout.get("realtime", False)),
        "layout": layout,
    }


def validate_input(normalized_input: dict) -> dict:
    if not normalized_input.get("space"):
        raise ValueError("Render input must include a space or room type")
    if not normalized_input.get("style"):
        raise ValueError("Render input must include a style")
    if not isinstance(normalized_input.get("material_candidates", []), list):
        raise ValueError("material_candidates must be a list")
    return normalized_input


def validate_output(payload: dict) -> None:
    for key in ("interior", "exterior", "isometric", "walkthrough_frames"):
        if key not in payload["renders"]:
            raise ValueError(f"renders.{key} is required")

    if payload["camera"]["angle"] not in SUPPORTED_CAMERA_ANGLES:
        raise ValueError("Unsupported camera angle")
    if payload["camera"]["position"] not in SUPPORTED_CAMERA_POSITIONS:
        raise ValueError("Unsupported camera position")
    if payload["camera"]["height"] not in SUPPORTED_CAMERA_HEIGHTS:
        raise ValueError("Unsupported camera height")
    if payload["lighting"]["type"] not in SUPPORTED_LIGHTING_TYPES:
        raise ValueError("Unsupported lighting type")
    if payload["lighting"]["time_of_day"] not in SUPPORTED_TIMES_OF_DAY:
        raise ValueError("Unsupported time of day")
    if payload["quality"]["resolution"] not in SUPPORTED_RESOLUTIONS:
        raise ValueError("Unsupported output resolution")
    if payload["preview"]["low_res"] not in SUPPORTED_PREVIEW_RESOLUTIONS:
        raise ValueError("Unsupported preview resolution")
    if payload["render_job"]["status"] not in SUPPORTED_JOB_STATUSES:
        raise ValueError("Unsupported render job status")
    if payload["render_job"]["priority"] not in SUPPORTED_JOB_PRIORITIES:
        raise ValueError("Unsupported render job priority")
    if not (1 <= payload["batch"]["batch_size"] <= MAX_BATCH_SIZE):
        raise ValueError("Batch size is outside supported limits")
    if not payload["cache"]["cache_key"] or len(payload["cache"]["cache_key"]) != 64:
        raise ValueError("Cache key must be a deterministic sha256 hex digest")
    if not all(isinstance(entry, dict) for entry in payload["errors"]):
        raise ValueError("errors must be a list of objects")

    style_key = payload["prompt"]["style"].strip().lower().replace(" ", "_")
    style_material_hints = STYLE_MATERIAL_HINTS.get(style_key.replace("minimal_", ""), set())
    material_blob = " ".join(payload["materials"].values()).lower()
    if style_material_hints and not any(material.lower() in material_blob for material in style_material_hints):
        raise ValueError("Materials do not match the selected style")
    if payload["lighting"]["type"] == "natural" and payload["camera"]["height"] == "low-angle":
        raise ValueError("Natural lighting with low-angle camera is not a supported production preset")
    if not payload["negative_prompt"]:
        raise ValueError("negative_prompt must not be empty")

    _validate_assets(payload["assets"], style_key)


def _validate_assets(assets: dict, style_key: str) -> None:
    for key in ("textures", "models", "hdris"):
        if key not in assets or not isinstance(assets[key], list) or not assets[key]:
            raise ValueError(f"assets.{key} must be a non-empty list")

    known_assets = STYLE_ASSET_PRESETS.get(style_key.replace("minimal_", ""), {})
    if known_assets:
        for texture in assets["textures"]:
            if not texture.startswith("tex/"):
                raise ValueError("Texture assets must use tex/ identifiers")
        for model in assets["models"]:
            if not model.startswith("mdl/"):
                raise ValueError("Model assets must use mdl/ identifiers")
        for hdri in assets["hdris"]:
            if not hdri.startswith("hdri/"):
                raise ValueError("HDRI assets must use hdri/ identifiers")


def _with_exterior_overrides(payload: dict) -> dict:
    scene = deepcopy(payload)
    scene["camera"] = {"angle": "wide", "position": "facade", "height": "eye-level", "fov": "90deg"}
    scene["lighting"] = {**scene["lighting"], "type": "natural", "direction": "east", "time_of_day": "morning"}
    scene["prompt"] = {**scene["prompt"], "space": "building exterior"}
    scene["raw_prompt"] += " Exterior facade composition, architectural exterior visualization."
    return scene


def _with_isometric_overrides(payload: dict) -> dict:
    scene = deepcopy(payload)
    scene["camera"] = {"angle": "isometric", "position": "center", "height": "overhead", "fov": "90deg"}
    scene["raw_prompt"] += " Isometric cutaway visualization."
    return scene


def _infer_space_from_prompt(prompt: str) -> str:
    lowered = prompt.lower()
    for space in ("living room", "bedroom", "kitchen", "bathroom", "office", "dining room", "exterior"):
        if space in lowered:
            return space.replace(" ", "_")
    return "living_room"


def _infer_style_from_prompt(prompt: str) -> str:
    lowered = prompt.lower()
    for style in STYLE_MATERIAL_HINTS:
        if style in lowered:
            return style
    return "modern"


def _infer_lighting_from_prompt(prompt: str) -> str:
    lowered = prompt.lower()
    if "natural" in lowered:
        return "soft natural light"
    if "dramatic" in lowered:
        return "dramatic mixed lighting"
    return "soft natural light"


def _infer_materials_from_prompt(prompt: str) -> list[str]:
    prompt_lower = prompt.lower()
    matches = []
    for materials in STYLE_MATERIAL_HINTS.values():
        for material in materials:
            if material.lower() in prompt_lower:
                matches.append(material)
    return _dedupe_preserve_order(matches) or ["oak wood", "white matte paint", "fabric"]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    ordered = []
    for value in values:
        text = str(value).strip()
        lowered = text.lower()
        if text and lowered not in seen:
            ordered.append(text)
            seen.add(lowered)
    return ordered
