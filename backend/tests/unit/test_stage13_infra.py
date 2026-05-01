"""Stage 13 unit tests — pre-UI handover infrastructure.

Covers four pieces of plumbing:

- Error code enum + ``http_status_for`` map: every code maps to a
  status; the envelope builder produces the canonical shape;
  ``AppError`` carries code + message + details into the handler.
- Rate-limit classifier + tier defaults: path hints + method
  fallback land on the right tier; ``RateLimitConfig.defaults()``
  gives the ranges promised by the spec (60 / 100 / 600 / 60s).
- OTEL skip path: with no ``OTEL_EXPORTER_OTLP_ENDPOINT`` env var,
  ``install()`` returns ``False`` cleanly. With deps missing it
  warns and returns ``False``. No exceptions on the boot path.
- S3-sync soft-fail: when settings are missing, returns 0 without
  raising, so backup.sh continues writing local artefacts.

No DB, no Redis, no real network — all in-process.
"""

from __future__ import annotations

import os
from typing import Any
from unittest.mock import patch

import pytest

from app.observability.error_codes import ErrorCode, http_status_for
from app.observability.error_envelope import (
    AppError,
    build_envelope,
)


# ─────────────────────────────────────────────────────────────────────
# Error taxonomy
# ─────────────────────────────────────────────────────────────────────


def test_every_error_code_maps_to_a_status():
    for code in ErrorCode:
        assert isinstance(http_status_for(code), int)


def test_validation_failed_is_422():
    assert http_status_for(ErrorCode.VALIDATION_FAILED) == 422


def test_rate_limited_is_429():
    assert http_status_for(ErrorCode.RATE_LIMITED) == 429


def test_envelope_shape_has_required_keys():
    env = build_envelope(
        code=ErrorCode.NOT_FOUND,
        message="missing",
        details=[{"field": "id", "message": "missing"}],
        request_id="req-abc",
    )
    assert env["error"] == "not_found"
    assert env["message"] == "missing"
    assert env["request_id"] == "req-abc"
    assert env["details"][0]["field"] == "id"


def test_envelope_accepts_string_code_for_third_party_paths():
    """Validation handlers don't import the enum — they pass raw
    strings. Lock that path."""
    env = build_envelope(code="custom_code", message="x")
    assert env["error"] == "custom_code"


def test_app_error_default_status_from_code():
    err = AppError(ErrorCode.PROJECT_NOT_FOUND, "no such project")
    assert err.status_code == 404
    assert err.code == ErrorCode.PROJECT_NOT_FOUND
    assert err.message == "no such project"


def test_app_error_explicit_status_overrides():
    err = AppError(ErrorCode.UNKNOWN, "x", status_code=418)
    assert err.status_code == 418


# ─────────────────────────────────────────────────────────────────────
# Rate-limit classifier
# ─────────────────────────────────────────────────────────────────────


def _make_request(*, path: str, method: str = "GET",
                  state: dict[str, Any] | None = None,
                  user: Any = None) -> Any:
    """Build a minimal Request stand-in for classify_request().

    classify_request only touches ``request.url.path``, ``method``,
    and ``request.state.rate_limit_tier`` — so we can fake it with a
    SimpleNamespace.
    """
    from types import SimpleNamespace

    state_ns = SimpleNamespace(**(state or {}))
    if user is not None:
        state_ns.user = user
    return SimpleNamespace(
        url=SimpleNamespace(path=path),
        method=method,
        state=state_ns,
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
    )


def test_classify_llm_paths():
    from app.middleware.rate_limit import RateLimitTier, classify_request

    for path in (
        "/api/v1/agent/chat",
        "/api/v1/generation/start",
        "/api/v1/specs/material",
        "/api/v1/drawings/plan",
        "/api/v1/diagrams/concept",
        "/api/v1/working_drawings/section",
        "/api/v1/parametric/apply",
        "/api/v1/brief/architect",
    ):
        tier = classify_request(_make_request(path=path, method="POST"))
        assert tier == RateLimitTier.LLM, path


def test_classify_uploads_as_write():
    from app.middleware.rate_limit import RateLimitTier, classify_request

    tier = classify_request(_make_request(
        path="/api/v1/uploads/sketch", method="POST",
    ))
    assert tier == RateLimitTier.WRITE


def test_classify_get_default_to_read():
    from app.middleware.rate_limit import RateLimitTier, classify_request

    tier = classify_request(_make_request(
        path="/api/v1/projects", method="GET",
    ))
    assert tier == RateLimitTier.READ


def test_classify_post_default_to_write():
    from app.middleware.rate_limit import RateLimitTier, classify_request

    tier = classify_request(_make_request(
        path="/api/v1/projects", method="POST",
    ))
    assert tier == RateLimitTier.WRITE


def test_classify_explicit_override_wins():
    from app.middleware.rate_limit import RateLimitTier, classify_request

    tier = classify_request(_make_request(
        path="/api/v1/agent/chat",  # would be LLM
        method="POST",
        state={"rate_limit_tier": RateLimitTier.READ},
    ))
    assert tier == RateLimitTier.READ


def test_rate_limit_config_defaults_match_spec():
    """Stage 13 spec: 60 LLM / 100 write / 600 read per 60s."""
    from app.middleware.rate_limit import RateLimitConfig, RateLimitTier

    cfg = RateLimitConfig.defaults()
    assert cfg.window_seconds == 60
    assert cfg.limit_for(RateLimitTier.LLM) == 60
    assert cfg.limit_for(RateLimitTier.WRITE) == 100
    assert cfg.limit_for(RateLimitTier.READ) == 600


# ─────────────────────────────────────────────────────────────────────
# OTEL skip semantics
# ─────────────────────────────────────────────────────────────────────


def test_otel_install_returns_false_when_endpoint_unset():
    from fastapi import FastAPI

    from app.observability import otel

    # Reset module-level state (other tests may have installed).
    otel._INSTALLED = False  # type: ignore[attr-defined]

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
        installed = otel.install(FastAPI())
        assert installed is False
        assert otel.is_installed() is False


def test_otel_parse_headers_handles_blank_and_comma():
    from app.observability.otel import _parse_headers

    assert _parse_headers(None) == {}
    assert _parse_headers("") == {}
    assert _parse_headers("a=1, b=2") == {"a": "1", "b": "2"}
    # Malformed entries skipped, valid ones kept.
    assert _parse_headers("a=1,trash,b=2") == {"a": "1", "b": "2"}


# ─────────────────────────────────────────────────────────────────────
# S3 sync soft-fail
# ─────────────────────────────────────────────────────────────────────


def test_s3_sync_returns_zero_when_settings_missing(tmp_path):
    """Backups must keep working when remote storage is unconfigured.

    The bash script ignores a 0-result; this test locks the
    behaviour."""
    from app.services.backup import s3_sync as mod

    # Settings come from env / .env. We expect the default test env
    # to have empty S3 creds — which means upload_files should
    # short-circuit before any boto3 call.
    f = tmp_path / "fake.dump.gz"
    f.write_text("dummy")

    # Re-import settings so any cached object reflects the test env.
    from app.config import get_settings

    settings = get_settings()
    if any([settings.s3_access_key, settings.s3_secret_key,
            settings.s3_endpoint, settings.s3_bucket]):
        pytest.skip("test env has S3 creds; this test only runs unconfigured")

    n = mod.upload_files([str(f)])
    assert n == 0


def test_s3_sync_extract_timestamp():
    from app.services.backup.s3_sync import _extract_timestamp

    ts = _extract_timestamp("db_20260501T103045Z.dump.gz")
    assert ts == "20260501T103045Z"
    ts = _extract_timestamp("uploads_20260501T103045Z.tar.gz")
    assert ts == "20260501T103045Z"
    ts = _extract_timestamp("manifest_20260501T103045Z.json")
    assert ts == "20260501T103045Z"
    # Unknown shape → "unknown" sentinel, not exception.
    assert _extract_timestamp("random.txt") == "unknown"
