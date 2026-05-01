"""Stage 13 — OpenTelemetry instrumentation (vendor-agnostic).

Wires distributed tracing into the FastAPI app **without** binding
to any specific telemetry backend. The exporter is OTLP/HTTP, which
every modern backend (Honeycomb, Grafana Cloud, Datadog,
SigNoz, Jaeger, ...) accepts natively.

Configuration (env vars, all optional):

- ``OTEL_EXPORTER_OTLP_ENDPOINT`` — e.g.
  ``https://api.honeycomb.io/v1/traces`` or
  ``https://otlp-gateway-prod-us-east-0.grafana.net/otlp/v1/traces``.
  When unset, instrumentation is **disabled** — :func:`install`
  becomes a no-op. Don't ship telemetry to the void.
- ``OTEL_EXPORTER_OTLP_HEADERS`` — e.g.
  ``x-honeycomb-team=YOUR_API_KEY``. Header keys/values are
  comma-separated.
- ``OTEL_SERVICE_NAME`` — default ``katha-api``.
- ``OTEL_RESOURCE_ATTRIBUTES`` — extra resource attributes
  (deployment.environment, service.version, ...). Standard OTel
  format ``key1=val1,key2=val2``.

Soft dependencies
-----------------
If ``opentelemetry-sdk`` / ``opentelemetry-instrumentation-fastapi``
aren't installed, :func:`install` logs a one-line warning and
continues. The app boots regardless.

Why no ``configure_logging`` integration?
-----------------------------------------
Stage 0 logging is JSON with ``request_id``. OTel adds trace_id
once instrumentation lands — a separate Stage 13B can wire the
log → trace correlation field when there's actually a backend
receiving the spans.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import FastAPI


logger = logging.getLogger(__name__)


_INSTALLED = False


def is_installed() -> bool:
    """``True`` once :func:`install` has wired tracing into FastAPI."""
    return _INSTALLED


def _parse_headers(raw: Optional[str]) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip()
        value = value.strip()
        if key:
            out[key] = value
    return out


def _parse_resource_attrs(raw: Optional[str]) -> dict[str, Any]:
    return _parse_headers(raw)  # same syntax


def install(app: FastAPI) -> bool:
    """Install OTel tracing on the given FastAPI app.

    Returns ``True`` if instrumentation was wired, ``False`` if it
    was skipped (no endpoint configured, missing dependencies, or
    setup failure). All paths log clearly so an operator can see
    what happened in startup logs.
    """
    global _INSTALLED
    if _INSTALLED:
        return True

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        logger.info(
            "otel.skipped reason=no_endpoint "
            "set OTEL_EXPORTER_OTLP_ENDPOINT to enable tracing",
        )
        return False

    try:
        # All imports lazy — keeps the app bootable when the OTel
        # libs aren't installed (dev / minimal envs).
        from opentelemetry import trace  # type: ignore[import-not-found]
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # type: ignore[import-not-found]
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import (  # type: ignore[import-not-found]
            FastAPIInstrumentor,
        )
        from opentelemetry.sdk.resources import Resource  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore[import-not-found]
        from opentelemetry.sdk.trace.export import (  # type: ignore[import-not-found]
            BatchSpanProcessor,
        )
    except ImportError as exc:
        logger.warning(
            "otel.skipped reason=missing_deps detail=%s "
            "install opentelemetry-sdk + "
            "opentelemetry-instrumentation-fastapi + "
            "opentelemetry-exporter-otlp-proto-http to enable",
            exc,
        )
        return False

    service_name = os.environ.get("OTEL_SERVICE_NAME", "katha-api").strip() or "katha-api"
    headers = _parse_headers(os.environ.get("OTEL_EXPORTER_OTLP_HEADERS"))
    resource_attrs = _parse_resource_attrs(
        os.environ.get("OTEL_RESOURCE_ATTRIBUTES")
    )
    resource_attrs.setdefault("service.name", service_name)

    try:
        resource = Resource.create(resource_attrs)
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=endpoint,
            headers=headers or None,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # FastAPI instrumentation creates a span per request, with
        # http.method / route / status_code attributes.
        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:  # noqa: BLE001
        logger.warning("otel.install_failed: %s", exc)
        return False

    _INSTALLED = True
    logger.info(
        "otel.installed endpoint=%s service=%s",
        endpoint, service_name,
    )
    return True


__all__ = [
    "install",
    "is_installed",
]
