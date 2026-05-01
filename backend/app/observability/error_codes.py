"""Stage 13 — canonical error code enum.

Every API error envelope carries a stable ``code`` field so clients
can branch on machine-readable categories instead of parsing
human-readable ``message`` strings.

Codes are stable. Renaming or repurposing a code is a **breaking
change** and requires the API-versioning policy
(see ``docs/api-versioning.md``):

- Add new codes freely.
- Deprecate by leaving the code in place and updating the docs.
- Never repurpose a code.

The HTTP status that ships with a given code is fixed at the
:func:`error_response` helper — so any handler raising
``code=AUTH_INVALID`` always lands on 401 regardless of which route
emitted it.
"""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """Canonical error categories surfaced in every API error envelope."""

    # 4xx — client problems.
    VALIDATION_FAILED = "validation_failed"          # 422
    INVALID_INPUT = "invalid_input"                  # 400
    MISSING_REQUIRED_FIELD = "missing_required_field"  # 400
    PROJECT_SCOPE_REQUIRED = "project_scope_required"  # 400

    AUTH_REQUIRED = "auth_required"                  # 401
    AUTH_INVALID = "auth_invalid"                    # 401
    AUTH_EXPIRED = "auth_expired"                    # 401
    FORBIDDEN = "forbidden"                          # 403

    NOT_FOUND = "not_found"                          # 404
    CONFLICT = "conflict"                            # 409
    GONE = "gone"                                    # 410

    RATE_LIMITED = "rate_limited"                    # 429
    QUOTA_EXCEEDED = "quota_exceeded"                # 429

    # 5xx — server problems.
    INTERNAL_ERROR = "internal_error"                # 500
    UPSTREAM_ERROR = "upstream_error"                # 502
    TOOL_TIMEOUT = "tool_timeout"                    # 504
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"    # 503

    # Domain-specific.
    TOOL_NOT_FOUND = "tool_not_found"                # 404
    TOOL_VALIDATION_ERROR = "tool_validation_error"  # 422
    DECISION_NOT_FOUND = "decision_not_found"        # 404
    DECISION_LOCKED = "decision_locked"              # 409
    PROJECT_NOT_FOUND = "project_not_found"          # 404
    LEARNING_DISABLED = "learning_disabled"          # 403

    # Catch-all.
    UNKNOWN = "unknown"                              # 500


# Map each code → canonical HTTP status. The error envelope helper
# uses this so handlers don't have to remember which code returns
# which status.
_HTTP_STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_FAILED: 422,
    ErrorCode.INVALID_INPUT: 400,
    ErrorCode.MISSING_REQUIRED_FIELD: 400,
    ErrorCode.PROJECT_SCOPE_REQUIRED: 400,

    ErrorCode.AUTH_REQUIRED: 401,
    ErrorCode.AUTH_INVALID: 401,
    ErrorCode.AUTH_EXPIRED: 401,
    ErrorCode.FORBIDDEN: 403,

    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.GONE: 410,

    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.QUOTA_EXCEEDED: 429,

    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.UPSTREAM_ERROR: 502,
    ErrorCode.UPSTREAM_UNAVAILABLE: 503,
    ErrorCode.TOOL_TIMEOUT: 504,

    ErrorCode.TOOL_NOT_FOUND: 404,
    ErrorCode.TOOL_VALIDATION_ERROR: 422,
    ErrorCode.DECISION_NOT_FOUND: 404,
    ErrorCode.DECISION_LOCKED: 409,
    ErrorCode.PROJECT_NOT_FOUND: 404,
    ErrorCode.LEARNING_DISABLED: 403,

    ErrorCode.UNKNOWN: 500,
}


def http_status_for(code: ErrorCode) -> int:
    """Canonical HTTP status for a given error code.

    Routes that raise ``HTTPException`` should generally pass the
    status from this helper rather than hand-coding numbers — keeps
    the contract single-source-of-truth.
    """
    return _HTTP_STATUS_BY_CODE.get(code, 500)


__all__ = [
    "ErrorCode",
    "http_status_for",
]
