"""Opt-in extensions for Jaeger.

Empty in M1–M3 — Jaeger doesn't ship MCP or messaging bridges yet. The
directory exists so the structure mirrors python_pydantic_ai/plugins/
(visual parity) and so future plugins have an obvious home.

Future candidates that would land here:
  • mcp_bridge.py / mcp_config.json — MCP server adapter (deferred from M2)
  • messaging/ — Discord / Telegram / iMessage bridges
  • voice/ — STT + TTS wiring for a voice loop

A plugin is opt-in: the agent core has no hard dependency on any plugin,
and default agent paths pay zero cost when a plugin isn't loaded.
"""
