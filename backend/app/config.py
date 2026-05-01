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
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

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
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "katha-assets"
    s3_region: str = "auto"

    # ── Auth ─────────────────────────────────────────────
    jwt_secret: str = _DEFAULT_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours

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
