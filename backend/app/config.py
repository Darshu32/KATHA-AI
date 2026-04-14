"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────
    app_name: str = "KATHA AI"
    debug: bool = False
    api_version: str = "v1"
    cors_origins: list[str] = ["http://localhost:3000"]

    # ── Database ─────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://katha:katha@localhost:5432/katha"
    database_echo: bool = False

    # ── Redis / Celery ───────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── OpenAI / LLM Provider ───────────────────────────
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-small"

    # ── Google Gemini (Nano Banana image generation) ────
    gemini_api_key: str = ""

    # ── YouTube Data API v3 ─────────────────────────────
    youtube_api_key: str = ""

    # ── Feature Flags ───────────────────────────────────
    sora_enabled: bool = False

    # ── Storage (Cloudflare R2 / S3-compat) ──────────────
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = "katha-assets"
    s3_region: str = "auto"

    # ── Auth ─────────────────────────────────────────────
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24  # 24 hours

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    return Settings()
