"""Decision-challenge repository (Stage 11).

The challenge ledger is append-only by convention — once a
challenge is resolved (rejected_challenge / decision_revised /
accepted_override), the row stays put. A re-challenge creates a
new row; we never mutate history.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import DecisionChallenge


_RESOLUTIONS = {
    "pending",
    "rejected_challenge",
    "decision_revised",
    "accepted_override",
}


class DecisionChallengeRepository:
    """Async repo for :class:`DecisionChallenge`."""

    @staticmethod
    async def file_challenge(
        session: AsyncSession,
        *,
        project_id: str,
        decision_id: str,
        challenger_id: Optional[str],
        challenge_text: str,
        extra: Optional[dict[str, Any]] = None,
    ) -> DecisionChallenge:
        """File a fresh challenge in ``pending`` state."""
        row = DecisionChallenge(
            project_id=project_id,
            decision_id=decision_id,
            challenger_id=challenger_id,
            challenge_text=challenge_text or "",
            resolution="pending",
            response_reasoning="",
            new_decision_id=None,
            extra=dict(extra or {}),
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def resolve(
        session: AsyncSession,
        *,
        challenge_id: str,
        resolution: str,
        response_reasoning: str,
        new_decision_id: Optional[str] = None,
    ) -> DecisionChallenge:
        """Update an existing challenge with the agent's resolution.

        Append-only-ish — we update the resolution fields on the
        same row. The row's identity persists for the audit trail;
        a re-challenge files a fresh row.
        """
        if resolution not in _RESOLUTIONS:
            raise ValueError(
                f"Unknown resolution {resolution!r}; "
                f"allowed: {sorted(_RESOLUTIONS)}"
            )
        result = await session.execute(
            select(DecisionChallenge).where(DecisionChallenge.id == challenge_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise LookupError(f"DecisionChallenge {challenge_id!r} not found")
        row.resolution = resolution
        row.response_reasoning = response_reasoning or ""
        row.new_decision_id = new_decision_id
        await session.flush()
        return row

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        *,
        challenge_id: str,
    ) -> Optional[DecisionChallenge]:
        result = await session.execute(
            select(DecisionChallenge).where(DecisionChallenge.id == challenge_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_for_decision(
        session: AsyncSession,
        *,
        decision_id: str,
        limit: int = 50,
    ) -> list[DecisionChallenge]:
        stmt = (
            select(DecisionChallenge)
            .where(DecisionChallenge.decision_id == decision_id)
            .order_by(DecisionChallenge.created_at.desc())
            .limit(max(1, min(int(limit), 200)))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def list_for_project(
        session: AsyncSession,
        *,
        project_id: str,
        resolution: Optional[str] = None,
        limit: int = 50,
    ) -> list[DecisionChallenge]:
        stmt = select(DecisionChallenge).where(
            DecisionChallenge.project_id == project_id,
        )
        if resolution is not None:
            if resolution not in _RESOLUTIONS:
                raise ValueError(
                    f"Unknown resolution {resolution!r}; "
                    f"allowed: {sorted(_RESOLUTIONS)}"
                )
            stmt = stmt.where(DecisionChallenge.resolution == resolution)
        stmt = stmt.order_by(DecisionChallenge.created_at.desc()).limit(
            max(1, min(int(limit), 500))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
