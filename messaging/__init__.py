"""Inbound-message gateways for the agent (Discord, Telegram, iMessage, …).

Each adapter is a long-lived class that:
  - Watches its channel for new user messages
  - Forwards each message through the shared agent (run_for_voice)
  - Replies on the same channel

The gateway daemon (`messaging.gateway`) loads the agent ONCE and starts
every adapter that has credentials configured, so all channels share the
same memory, the same skills, and the same in-process Gemma. Run via:

    .venv/bin/python -m messaging.gateway

Adapters that successfully start also register themselves in the
`_BRIDGES` registry below, so the agent's `send_message(channel, …)` tool
can push proactive messages from cron jobs or mid-conversation.
"""

from __future__ import annotations

import threading
from typing import Any


# {channel_name → bridge_instance}. Populated by each bridge as it starts;
# read by python_pydantic_ai.tools.send_message. A lock guards the dict so
# the gateway can register/deregister without races against tool calls.
_BRIDGES: dict[str, Any] = {}
_BRIDGES_LOCK = threading.Lock()


def register_bridge(name: str, bridge: Any) -> None:
    """Bridges call this from their `start()` once they're connected."""
    with _BRIDGES_LOCK:
        _BRIDGES[name] = bridge


def deregister_bridge(name: str) -> None:
    with _BRIDGES_LOCK:
        _BRIDGES.pop(name, None)


def get_bridge(name: str) -> Any:
    with _BRIDGES_LOCK:
        return _BRIDGES.get(name)


def list_bridges() -> list[str]:
    with _BRIDGES_LOCK:
        return sorted(_BRIDGES.keys())
