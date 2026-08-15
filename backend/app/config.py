"""Application settings — single source of truth for env-driven config.

Hardened in Stage 0:
- ``environment`` flag distinguishes dev / staging / prod
- ``Settings.assert_production_safe()`` refuses to boot with default
  secrets in non-dev environments
- ``has_*_key`` helpers report which integrations are wired without
  ever exposing the raw secret value
- Anthropic Claude key added (per agent stack lock-in for Stage 2+)

Never log a Settings instance directly — use ``redacted_dict()``.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings

# Sentinel values that indicate "the user has not yet configured this".
_DEFAULT_JWT_SECRET = "change-me-in-production"  # noqa: S105 — sentinel, not a credential


Environment = Literal["dev", "staging", "prod"]


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────
    app_name: str = "KATHA AI"
    environment: Environment = "dev"
    debug: bool = False
    api_version: str = "v1"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:3001",
        ]
    )

    # ── Database ─────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://katha:katha@localhost:5432/katha"
    database_echo: bool = False

    # ── Redis / Celery ───────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── LLM providers ────────────────────────────────────
    # Stage 2+: Anthropic Claude is the primary agent runtime.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"

    # OpenAI used as fallback + for embeddings.
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"

    # Google Gemini for image generation.
    gemini_api_key: str = ""
    # Nano Banana (Gemini) image model — used for chat media and, when selected,
    # the design finish pass. Bump to the Pro / "nano-banana-2" id when adopted.
    gemini_image_model: str = "gemini-2.5-flash-image"
    # Which provider finishes the geometry render into a photoreal image:
    #   "gemini" — Nano Banana img2img (default; tightest geometry+camera lock,
    #              cheaper/faster, EU-pinnable via Vertex — KATHA's target stack)
    #   "openai" — gpt-image-1 image-edit (re-frames slightly; automatic fallback)
    # ControlNet-depth still wins when a token is set; the other provider is the
    # automatic fallback. Serves both prompt-mode and (later) upload-enhance.
    spatial_finish_provider: str = "gemini"
    # Optional PROD finish lock — ControlNet-depth via Replicate. When BOTH the
    # token and the model are set, the finish pass conditions on the kernel DEPTH
    # MAP (Flux/SDXL depth-ControlNet) for the tightest possible geometry lock,
    # ahead of the img2img providers above. Dormant (falls back) when either is
    # blank — so it's a config switch, not a code change.
    replicate_api_token: str = ""
    # Official Flux depth model — great for architecture (preserves geometry,
    # restyles materials). Extracts depth from the clay render internally. Ready
    # to use the moment replicate_api_token is set; blank token = dormant.
    controlnet_depth_model: str = "black-forest-labs/flux-depth-dev"
    # Finish tuning. Higher guidance = stronger prompt/material adherence; the
    # depth control keeps geometry locked regardless. Steps trade quality vs cost.
    controlnet_guidance: float = 12.0
    controlnet_steps: int = 28
    # Send the kernel's exact DEPTH MAP as the control instead of the clay render.
    # Leave False for flux-depth-dev (it extracts depth from the clay image); set
    # True only if you point controlnet_depth_model at a depth-NATIVE ControlNet.
    controlnet_send_depth: bool = False
    # Faithful-render policy. When True (default), the display render is ALWAYS
    # geometry-true: the exact kernel clay render, or — when a Replicate token is
    # set — the depth-locked ControlNet finish. The img2img "beautify" providers
    # (Gemini / gpt-image-1) are NEVER used for the shown render because they
    # re-imagine the scene (move & invent furniture), so it stops matching the
    # plan / 3D / drawings. Set False only to allow that legacy img2img beautify.
    spatial_render_faithful_only: bool = True
    # Anti-aliasing: render this many times oversampled, then box-downsample. 2 is
    # a big quality win for little cost; 1 disables it (fastest); 3+ is sharper but
    # scales compute ~quadratically. Presentation-quality knob for the clay render.
    spatial_render_supersample: int = 2

    # ── Interop / export ─────────────────────────────────
    # Speckle push (Revit/Rhino/Grasshopper/ArchiCAD distribution wedge).
    # All three blank = offline mode: the export still serializes a valid
    # Speckle object tree, only the live server push is skipped.
    speckle_server_url: str = ""
    speckle_token: str = ""
    speckle_project_id: str = ""

    # ── External APIs ────────────────────────────────────
    youtube_api_key: str = ""

    # ── Feature Flags ───────────────────────────────────
    sora_enabled: bool = False

    # Stage 5D — when True, auto-indexing of design versions runs as
    # a Celery task instead of inline. Default False so installations
    # without a healthy worker still get inline indexing. Production
    # turns this on once Celery has been monitored to keep up with
    # generation traffic.
    async_indexing_enabled: bool = False

    # ── Storage (Cloudflare R2 / S3-compat) ──────────────
    # Stage 7 — backend selector. ``local`` writes to a directory on
    # disk (defaults to ``./uploads``); ``s3`` uses the S3-compatible
    # bucket below. Tests use ``local`` with a temp dir.
    storage_backend: str = "local"
    storage_local_root: str = "uploads"
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "katha-assets"
    s3_region: str = "auto"

    # Stage 7 — multi-modal (vision).
    # Image-asset upload limits enforced at the route layer.
    upload_max_bytes: int = 25 * 1024 * 1024  # 25 MB
    # Allowed MIME types for the upload endpoint. The vision tools
    # additionally check the image is one of these before sending to
    # the model — no user-supplied URI bypasses this.
    upload_allowed_mime: tuple[str, ...] = (
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/heic",
        "image/heif",
    )
    # Vision runs on OpenAI (same OPENAI_API_KEY as the agent runtime).
    # We expose the model slug separately so future stages can pin a
    # different vision-tuned variant without moving the chat model.
    vision_model: str = "gpt-4o"

    # ── Stage 12 — Live data feeds ───────────────────────
    # Master switch. When False every adapter resolves to its stub
    # implementation regardless of the per-feed flags below — used by
    # the test suite and offline dev. Production sets True and gates
    # individual feeds via the per-feed envs.
    live_feeds_enabled: bool = False

    # Per-feed switches. False keeps the adapter registered but the
    # Celery beat task short-circuits to a no-op (with a structured log
    # event for ops dashboards).
    feed_mcx_enabled: bool = True
    feed_fx_enabled: bool = True
    feed_gst_enabled: bool = True
    feed_vendor_jaquar_enabled: bool = True
    feed_vendor_kohler_enabled: bool = True
    feed_vendor_asian_paints_enabled: bool = True

    # HTTP transport — single timeout/retry policy for every adapter
    # so ops can dial blast radius without per-adapter tuning.
    feed_http_timeout_seconds: float = 20.0
    feed_http_max_retries: int = 2

    # Anomaly threshold. Midpoint move >= this percentage between the
    # previous current quote and the incoming one fires an alert.
    feed_anomaly_pct_threshold: float = 10.0

    # Slack webhook for anomaly alerts. Empty string = log-only fallback
    # (the alert row is still persisted; only the Slack POST is skipped).
    feed_slack_webhook_url: str = ""
    feed_slack_channel: str = "#price-alerts"

    # Freshness ladder (seconds). The bands mirror what UI shows in
    # the estimate envelope: live < 6h, recent < 24h, stale < 14d,
    # otherwise expired. We keep them config-tunable so a long-weekend
    # outage doesn't accidentally show every estimate as "expired".
    feed_freshness_live_seconds: int = 6 * 3600
    feed_freshness_recent_seconds: int = 24 * 3600
    feed_freshness_stale_seconds: int = 14 * 86400

    # Per-adapter base URLs (overridable so staging hits a recording
    # proxy without code changes). Empty defaults are intentional —
    # each adapter knows its own canonical URL when this is blank.
    feed_mcx_base_url: str = ""
    feed_fx_base_url: str = ""
    feed_gst_base_url: str = ""

    # ── Auth ─────────────────────────────────────────────
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours

    # ── Opening geometry (windows / doors) ───────────────
    # The one place opening dimensions live. Values are code-sourced — NBC/IBC
    # clear doorway width 900 mm, standard 2.1 m leaf, common residential window
    # proportions — and env-overridable so a jurisdiction or client standard can
    # retune them without touching geometry code. Read by the wall model, so the
    # generation opening-pass, every 2D/3D renderer and the IFC export all size
    # openings from this single source instead of hardcoded literals.
    opening_door_width_m: float = 0.9       # NBC/IBC clear doorway width
    opening_door_height_m: float = 2.1      # standard door leaf height
    opening_window_width_m: float = 1.2     # standard residential window width
    opening_window_sill_m: float = 0.9      # sill height above finished floor
    opening_window_head_m: float = 2.1      # head height above finished floor
    opening_min_door_wall_m: float = 0.9    # shortest partition that can hold a door
    opening_min_window_wall_m: float = 1.6  # shortest exterior wall that gets a window

    # ── Mesh import (upload → geometry) ──────────────────
    # Uploaded models arrive in arbitrary units (mm / cm / m / inches). Geometry
    # alone can't reveal the true size, so if the model's largest dimension falls
    # outside this plausible object-scale band we snap it by whole powers of 10
    # (a unit guess) so an editable part reads as "0.85 m", not "85 m". Models
    # already in-band are trusted as-is. Env-overridable for building-scale work.
    import_scale_min_m: float = 0.08
    import_scale_max_m: float = 4.0
    # A dense CAD mesh can shatter into dozens of connected components. Keep the
    # largest as individual editable parts (up to the cap, and only those at least
    # this fraction of the biggest); everything smaller merges into ONE "remainder"
    # part so nothing is dropped from the render but the part list stays legible.
    import_max_parts: int = 24
    import_min_part_frac: float = 0.04

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # ── Validators ───────────────────────────────────────

    @field_validator("environment", mode="before")
    @classmethod
    def _normalize_environment(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip().lower()
        return v

    # ── Helpers ──────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @property
    def has_anthropic_key(self) -> bool:
        return bool(self.anthropic_api_key.strip())

    @property
    def has_openai_key(self) -> bool:
        return bool(self.openai_api_key.strip())

    @property
    def has_gemini_key(self) -> bool:
        return bool(self.gemini_api_key.strip())

    def assert_production_safe(self) -> None:
        """Refuse to boot in staging/prod with insecure defaults.

        Called from app startup (Stage 0+). Catches the most common
        deploy-time foot-gun: shipping with the dev JWT secret.
        """
        if self.environment == "dev":
            return

        problems: list[str] = []
        if self.jwt_secret == _DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32:
            problems.append("jwt_secret must be set to a strong random value")
        if not self.database_url or "localhost" in self.database_url:
            problems.append("database_url is pointing at localhost")
        if not self.has_anthropic_key and not self.has_openai_key:
            problems.append("at least one LLM provider key must be configured")

        if problems:
            joined = "; ".join(problems)
            raise RuntimeError(
                f"Refusing to start in environment={self.environment!r}: {joined}"
            )

    def redacted_dict(self) -> dict[str, object]:
        """Settings as a dict, with secret-like values masked.

        Use this for /health debug output or startup banners — never log
        the raw Settings instance.
        """
        secret_keys = {
            "anthropic_api_key",
            "openai_api_key",
            "gemini_api_key",
            "youtube_api_key",
            "s3_secret_key",
            "s3_access_key",
            "jwt_secret",
        }
        out: dict[str, object] = {}
        for name, value in self.model_dump().items():
            if name in secret_keys:
                out[name] = "***" if value else ""
            else:
                out[name] = value
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
