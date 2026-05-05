"""Slack webhook for anomaly notifications.

Best-effort by design (Stage 13 soft-fail pattern): a misconfigured
or down Slack webhook MUST NOT crash the Celery worker mid-refresh.
The alert row is the source of truth; Slack is the courtesy ping.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _format_message(
    *,
    feed_source: str,
    commodity_key: str,
    previous_mid: float,
    new_mid: float,
    pct_change: float,
    threshold_pct: float,
    direction: str,
    material_slug: Optional[str] = None,
) -> dict[str, Any]:
    """Render the Slack ``blocks`` payload.

    Slack's Block Kit is more verbose than ``text`` alone but the UI
    grouping makes ops triage faster. We always send a fallback
    ``text`` field too so notifications survive Slack rendering changes.
    """
    arrow = "📈" if direction == "up" else "📉"
    sign = "+" if pct_change >= 0 else ""
    sku_line = f" (material: `{material_slug}`)" if material_slug else ""
    headline = (
        f"{arrow} *Price anomaly* — `{feed_source}/{commodity_key}`{sku_line}"
    )
    body = (
        f"*Move:* {sign}{pct_change:.2f}% (threshold {threshold_pct:.1f}%)\n"
        f"*Previous mid:* {previous_mid:,.2f}\n"
        f"*New mid:* {new_mid:,.2f}"
    )
    return {
        "text": (
            f"Price anomaly: {feed_source}/{commodity_key} "
            f"{sign}{pct_change:.2f}% ({direction})"
        ),
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": headline},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body},
            },
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": (
                            "Triggered by KATHA-AI feed anomaly detector. "
                            "Acknowledge from `/admin/feeds/alerts`."
                        ),
                    }
                ],
            },
        ],
    }


async def send_anomaly_alert(
    *,
    feed_source: str,
    commodity_key: str,
    previous_mid: float,
    new_mid: float,
    pct_change: float,
    threshold_pct: float,
    direction: str,
    material_slug: Optional[str] = None,
    timeout_seconds: float = 5.0,
) -> tuple[str, Optional[str]]:
    """POST a formatted message to the Slack webhook.

    Returns ``(channel, error)``. ``channel`` is one of:
      - ``"slack"`` — webhook returned 2xx
      - ``"log"``   — no webhook configured; written to logger instead
      - ``"none"``  — POST attempted but failed (error populated)

    Never raises; errors are caught and surfaced via the return tuple.
    """
    settings = get_settings()
    payload = _format_message(
        feed_source=feed_source,
        commodity_key=commodity_key,
        previous_mid=previous_mid,
        new_mid=new_mid,
        pct_change=pct_change,
        threshold_pct=threshold_pct,
        direction=direction,
        material_slug=material_slug,
    )

    if not settings.feed_slack_webhook_url:
        logger.warning(
            "feed_anomaly fallback=log feed=%s commodity=%s pct=%.2f%%",
            feed_source,
            commodity_key,
            pct_change,
        )
        return "log", None

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(
                settings.feed_slack_webhook_url, json=payload
            )
        if 200 <= resp.status_code < 300:
            return "slack", None
        return "none", f"slack webhook HTTP {resp.status_code}"
    except httpx.HTTPError as exc:
        logger.warning(
            "feed_slack_webhook failed: %s (feed=%s commodity=%s)",
            exc,
            feed_source,
            commodity_key,
        )
        return "none", f"slack webhook error: {exc}"
    except Exception as exc:  # noqa: BLE001 — soft-fail boundary
        logger.exception(
            "feed_slack_webhook unexpected exception (feed=%s)", feed_source
        )
        return "none", f"unexpected: {exc}"
