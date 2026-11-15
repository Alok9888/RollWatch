from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("rollwatch.alerts")


async def send_alert_webhook(
    webhook_url: str | None,
    *,
    title: str,
    target_name: str,
    trigger_reason: str,
    details: dict[str, Any],
    severity: str = "critical",
) -> bool:
    """Dispatch a Slack/Discord-compatible JSON webhook notification."""
    if not webhook_url:
        return False

    summary_lines = [f"**{title}** (`{target_name}`)", f"Reason: `{trigger_reason}`"]
    for key, val in details.items():
        if val is not None:
            summary_lines.append(f"- {key}: `{val}`")
    message = "\n".join(summary_lines)

    color = 0xEF4444 if severity == "critical" else 0xF59E0B
    payload = {
        # Discord fields
        "content": message,
        "embeds": [
            {
                "title": f"[RollWatch] {title}",
                "description": f"Target **{target_name}** triggered `{trigger_reason}`",
                "color": color,
                "fields": [
                    {"name": str(k), "value": str(v), "inline": True}
                    for k, v in details.items()
                    if v is not None
                ][:10],
            }
        ],
        # Slack compatible fields
        "text": message,
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(webhook_url, json=payload)
            if response.status_code >= 400:
                logger.warning("Alert webhook returned HTTP %s: %s", response.status_code, response.text[:200])
                return False
            return True
    except Exception as exc:
        logger.warning("Failed to dispatch alert webhook to %s: %s", webhook_url, exc)
        return False
