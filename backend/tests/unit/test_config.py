"""Smoke tests for the Settings hardening done in Stage 0."""

from __future__ import annotations

import pytest

from app.config import Settings


def test_dev_environment_allows_default_secret() -> None:
    s = Settings(environment="dev", jwt_secret="change-me-in-production")
    s.assert_production_safe()  # must not raise


def test_prod_environment_rejects_default_jwt() -> None:
    s = Settings(
        environment="prod",
        jwt_secret="change-me-in-production",
        database_url="postgresql+asyncpg://user:pw@db.prod/x",
        anthropic_api_key="sk-ant-foo",
    )
    with pytest.raises(RuntimeError, match="jwt_secret"):
        s.assert_production_safe()


def test_prod_environment_requires_an_llm_key() -> None:
    s = Settings(
        environment="prod",
        jwt_secret="x" * 48,
        database_url="postgresql+asyncpg://user:pw@db.prod/x",
    )
    with pytest.raises(RuntimeError, match="LLM provider"):
        s.assert_production_safe()


def test_prod_passes_with_strong_secret_and_anthropic_key() -> None:
    s = Settings(
        environment="prod",
        jwt_secret="x" * 48,
        database_url="postgresql+asyncpg://user:pw@db.prod/x",
        anthropic_api_key="sk-ant-foo",
    )
    s.assert_production_safe()


def test_redacted_dict_masks_secrets() -> None:
    s = Settings(
        anthropic_api_key="sk-ant-secret",
        openai_api_key="sk-openai-secret",
        jwt_secret="z" * 48,
    )
    out = s.redacted_dict()
    assert out["anthropic_api_key"] == "***"
    assert out["openai_api_key"] == "***"
    assert out["jwt_secret"] == "***"
    # Non-secret fields remain visible.
    assert out["app_name"] == "KATHA AI"


def test_has_key_helpers() -> None:
    s = Settings(anthropic_api_key="  sk-ant  ")
    assert s.has_anthropic_key
    assert not s.has_openai_key
    assert not s.has_gemini_key
