"""Structured logging configured once at app startup.

Two modes
---------
- **dev** (``debug=True``): pretty, colorless, human-readable.
- **prod** (``debug=False``): single-line JSON, ready for log aggregators.

Every log line gets the current ``request_id`` (if inside a request) and
the logger name. Use ``get_logger(__name__)`` instead of ``logging.getLogger``
to ensure consistent formatting.

Why solo-dev cares
------------------
You can't grep prod logs by request without a request ID. You can't ship
to a log aggregator without JSON. This file makes both true on day 1.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.observability.request_id import get_request_id


# ─────────────────────────────────────────────────────────────────────────
# Formatters
# ─────────────────────────────────────────────────────────────────────────


class _JSONFormatter(logging.Formatter):
    """Single-line JSON suitable for shipping to a log aggregator."""

    # Reserved LogRecord keys we don't want to duplicate as "extras".
    _RESERVED = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = get_request_id()
        if rid:
            payload["request_id"] = rid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Surface any user-provided extras.
        for key, value in record.__dict__.items():
            if key in self._RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except TypeError:
                value = repr(value)
            payload[key] = value
        return json.dumps(payload, default=str, ensure_ascii=False)


class _PrettyFormatter(logging.Formatter):
    """Human-friendly format for local development."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime("%H:%M:%S")
        rid = get_request_id()
        rid_part = f" [{rid[:8]}]" if rid else ""
        msg = record.getMessage()
        line = f"{ts} {record.levelname:<5} {record.name}{rid_part}: {msg}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────


def configure_logging(*, debug: bool = False) -> None:
    """Configure the root logger. Call exactly once at app startup."""
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(_PrettyFormatter() if debug else _JSONFormatter())

    root = logging.getLogger()
    # Replace any existing handlers (uvicorn, basicConfig leftovers).
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if debug else logging.INFO)

    # Tame noisy third-party loggers.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper. Use this instead of ``logging.getLogger``."""
    return logging.getLogger(name)
