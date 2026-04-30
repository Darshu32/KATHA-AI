"""Observability primitives — logging, request IDs, future tracing hooks.

Stage 0 ships:
- ``configure_logging``      : single entry point for log setup (JSON in prod, pretty in dev)
- ``RequestIdMiddleware``    : assigns / propagates request IDs
- ``get_request_id``         : access the current request ID from anywhere
- ``get_logger``             : structured logger with request_id auto-attached

Later stages add OpenTelemetry tracing on top of this same scaffold.
"""

from app.observability.logging import configure_logging, get_logger
from app.observability.request_id import (
    RequestIdMiddleware,
    get_request_id,
    set_request_id,
)

__all__ = [
    "RequestIdMiddleware",
    "configure_logging",
    "get_logger",
    "get_request_id",
    "set_request_id",
]
