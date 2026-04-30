"""Tests for the schema-conventions mixins (no DB needed)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.conventions import EffectiveDatesMixin


class _Row(EffectiveDatesMixin):
    """Bare instance to test the ``is_active_at`` predicate."""

    def __init__(
        self,
        effective_from: datetime,
        effective_to: datetime | None,
    ) -> None:
        self.effective_from = effective_from
        self.effective_to = effective_to


def test_active_within_window() -> None:
    now = datetime.now(timezone.utc)
    row = _Row(
        effective_from=now - timedelta(days=1),
        effective_to=now + timedelta(days=1),
    )
    assert row.is_active_at(now)


def test_inactive_before_window() -> None:
    now = datetime.now(timezone.utc)
    row = _Row(
        effective_from=now + timedelta(hours=1),
        effective_to=None,
    )
    assert not row.is_active_at(now)


def test_inactive_after_window() -> None:
    now = datetime.now(timezone.utc)
    row = _Row(
        effective_from=now - timedelta(days=2),
        effective_to=now - timedelta(days=1),
    )
    assert not row.is_active_at(now)


def test_open_ended_window() -> None:
    now = datetime.now(timezone.utc)
    row = _Row(
        effective_from=now - timedelta(days=30),
        effective_to=None,
    )
    assert row.is_active_at(now)
