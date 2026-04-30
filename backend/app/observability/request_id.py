"""Request ID propagation.

Every inbound HTTP request gets a request ID — either taken from the
``X-Request-ID`` header (so callers can correlate across services) or
generated fresh. The ID is:

- Stored in a ``ContextVar`` so any code path can grab it
- Echoed back in the response headers
- Attached to every log line
- Recorded on every ``AuditEvent`` written during the request

This is the spine of "what happened during request X?" debugging — solo
dev needs this once production starts seeing real traffic.
"""

from __future__ import annotations

from contextvars import ContextVar
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Header name follows the de-facto standard.
HEADER_NAME = "X-Request-ID"

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the current request ID, or None outside a request context."""
    return _request_id_ctx.get()


def set_request_id(value: str | None) -> None:
    """Set the request ID for the current context. Useful in tests + workers."""
    _request_id_ctx.set(value)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assign or propagate a request ID for each HTTP request."""

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        incoming = request.headers.get(HEADER_NAME)
        request_id = incoming or uuid4().hex
        token = _request_id_ctx.set(request_id)
        try:
            response: Response = await call_next(request)
        finally:
            _request_id_ctx.reset(token)
        response.headers[HEADER_NAME] = request_id
        return response
