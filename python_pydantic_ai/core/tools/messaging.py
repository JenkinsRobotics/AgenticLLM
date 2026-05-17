"""Messaging skill (sender-side).

  • send_message(channel, recipient, text) — push a message into any
    registered bridge (discord / telegram / imessage).

This skill is the AGENT-FACING side of messaging. The actual bridge code
(receive-side daemons) lives in `plugins/messaging/` and gets started by
the gateway. The skill talks to those bridges through the shared
register/get_bridge registry.
"""

from __future__ import annotations

from typing import Any


def send_message(channel: str, recipient: str, text: str) -> dict[str, Any]:
    """Send a proactive message to a user on a registered channel.

    `channel` is one of the bridges started by `plugins/messaging/gateway.py`:
    "discord", "telegram", "imessage".
    `recipient` is the channel-specific ID:
      - discord:  numeric user ID or channel ID (as a string)
      - telegram: numeric chat ID (as a string)
      - imessage: phone number ("+15551234567") or Apple ID email
    `text` is the message body.

    Use this for cron jobs ("every morning send weather to Discord") or
    mid-conversation routing ("text the user the result on iMessage").
    Returns {sent, ...} on success or {sent: False, error: "..."}.
    """
    channel = (channel or "").strip().lower()
    recipient = (recipient or "").strip()
    text = (text or "").strip()
    if not channel or not recipient or not text:
        return {"sent": False, "error": "channel, recipient, and text are all required"}

    try:
        from ...plugins.messaging import get_bridge, list_bridges
    except Exception as exc:
        return {"sent": False, "error": f"messaging plugin not importable: {exc}"}

    bridge = get_bridge(channel)
    if bridge is None:
        return {
            "sent": False,
            "error": f"no bridge registered for {channel!r}; live bridges: {list_bridges()}",
        }
    try:
        return bridge.send(recipient, text)
    except Exception as exc:
        return {"sent": False, "error": f"bridge.send failed: {type(exc).__name__}: {exc}"}
