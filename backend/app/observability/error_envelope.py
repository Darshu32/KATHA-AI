"""Stage 13 — uniform error envelope helpers.

The platform's API contract: **every** error response is shaped
identically across every route, so a frontend or integration can
catch errors with one parser:

.. code-block:: json

   {
     "error": "validation_failed",          // ErrorCode enum value
     "message": "human-readable summary",
     "request_id": "req-abc123",            // Stage 0 join key
     "details": [                            // optional, per-field
       {"field": "project_type", "message": "missing"}
     ]
   }

The Stage 0 ``ErrorResponse`` schema already standardised the JSON
shape; this module adds:

- :class:`AppError` — typed exception carrying a code, message, and
  optional details. Routes raise these instead of bare
  ``HTTPException``.
- :func:`build_envelope` — turn an :class:`AppError` (or a stray
  ``Exception``) into the JSON dict the response handler returns.
- :func:`install_error_handlers` — wires the FastAPI exception
  handlers so all errors land in the envelope, regardless of how
  they were raised.

Routes are encouraged to migrate to ``AppError`` over time. The
fallback handler keeps existing ``HTTPException``-based code
working unchanged.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.models.schemas import ErrorDetail, ErrorResponse
from app.observability.error_codes import ErrorCode, http_status_for
from app.observability.request_id import get_request_id


# ─────────────────────────────────────────────────────────────────────
# AppError — the typed exception routes should raise
# ─────────────────────────────────────────────────────────────────────


class AppError(Exception):
    """Typed exception carrying a stable error code + envelope fields.

    Raise this from routes / services instead of bare ``HTTPException``
    when the failure has a known code. The exception handler maps it
    to the canonical HTTP status from :data:`_HTTP_STATUS_BY_CODE`.
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str = "",
        *,
        details: Optional[list[ErrorDetail]] = None,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message or code.value)
        self.code = code
        self.message = message or code.value
        self.details = list(details or [])
        self.status_code = status_code or http_status_for(code)


# ─────────────────────────────────────────────────────────────────────
# Envelope builders
# ─────────────────────────────────────────────────────────────────────


def build_envelope(
    *,
    code: ErrorCode | str,
    message: str,
    details: Optional[list[dict[str, Any]] | list[ErrorDetail]] = None,
    request_id: Optional[str] = None,
) -> dict[str, Any]:
    """Produce the canonical JSON envelope dict.

    Accepts either ``ErrorCode`` enum or its raw string value so
    third-party error handlers (e.g. validation errors) don't need
    to import the enum.
    """
    code_str = code.value if isinstance(code, ErrorCode) else str(code)
    detail_dicts: list[dict[str, Any]] = []
    if details:
        for d in details:
            if isinstance(d, ErrorDetail):
                detail_dicts.append(d.model_dump())
            elif isinstance(d, dict):
                detail_dicts.append(dict(d))
    envelope = ErrorResponse(
        error=code_str,
        message=message,
        details=[ErrorDetail(**d) for d in detail_dicts],
    ).model_dump()
    rid = request_id or get_request_id()
    if rid:
        envelope["request_id"] = rid
    return envelope


# ─────────────────────────────────────────────────────────────────────
# Exception handlers
# ─────────────────────────────────────────────────────────────────────


async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=build_envelope(
            code=exc.code,
            message=exc.message,
            details=exc.details,
        ),
    )


async def _handle_validation_error(
    _: Request, exc: RequestValidationError,
) -> JSONResponse:
    details = [
        ErrorDetail(
            field=".".join(
                str(part) for part in error["loc"] if part != "body"
            ),
            message=error["msg"],
        ).model_dump()
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=build_envelope(
            code=ErrorCode.VALIDATION_FAILED,
            message="Request validation failed",
            details=details,
        ),
    )


async def _handle_http_exception(
    _: Request, exc: HTTPException,
) -> JSONResponse:
    """FastAPI's default — kept for routes still raising HTTPException.

    Detail can be (a) an already-shaped envelope dict, (b) a string,
    or (c) anything else. We wrap any non-envelope detail into a
    fresh envelope keyed by HTTP status.
    """
    if isinstance(exc.detail, dict) and {"error", "message"}.issubset(
        exc.detail.keys()
    ):
        content = exc.detail
        # Inject request_id if the raiser didn't.
        rid = get_request_id()
        if rid and "request_id" not in content:
            content = dict(content)
            content["request_id"] = rid
    else:
        # Map common HTTP statuses to canonical codes.
        code = {
            400: ErrorCode.INVALID_INPUT,
            401: ErrorCode.AUTH_REQUIRED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            409: ErrorCode.CONFLICT,
            410: ErrorCode.GONE,
            422: ErrorCode.VALIDATION_FAILED,
            429: ErrorCode.RATE_LIMITED,
            500: ErrorCode.INTERNAL_ERROR,
            502: ErrorCode.UPSTREAM_ERROR,
            503: ErrorCode.UPSTREAM_UNAVAILABLE,
            504: ErrorCode.TOOL_TIMEOUT,
        }.get(exc.status_code, ErrorCode.UNKNOWN)
        content = build_envelope(code=code, message=str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content=content)


def install_error_handlers(app: FastAPI) -> None:
    """Register the canonical exception handlers on a FastAPI app.

    Idempotent — calling twice replaces the handlers in place.
    """
    app.add_exception_handler(AppError, _handle_app_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _handle_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(HTTPException, _handle_http_exception)  # type: ignore[arg-type]


__all__ = [
    "AppError",
    "build_envelope",
    "install_error_handlers",
]
