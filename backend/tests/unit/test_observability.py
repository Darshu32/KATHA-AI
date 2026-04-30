"""Smoke tests for request-id propagation and structured logging."""

from __future__ import annotations

import json
import logging

from app.observability.logging import _JSONFormatter, configure_logging
from app.observability.request_id import get_request_id, set_request_id


def test_set_and_get_request_id() -> None:
    set_request_id("abc-123")
    assert get_request_id() == "abc-123"
    set_request_id(None)
    assert get_request_id() is None


def test_json_formatter_includes_request_id() -> None:
    set_request_id("trace-xyz")
    try:
        formatter = _JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        out = json.loads(formatter.format(record))
        assert out["msg"] == "hello"
        assert out["request_id"] == "trace-xyz"
        assert out["level"] == "INFO"
    finally:
        set_request_id(None)


def test_configure_logging_replaces_handlers() -> None:
    configure_logging(debug=False)
    root = logging.getLogger()
    assert len(root.handlers) == 1
    # Re-configuring is idempotent (no handler accumulation).
    configure_logging(debug=True)
    assert len(root.handlers) == 1
