"""MCP (Model Context Protocol) plugin.

Bridges the agent to external MCP server processes. Each registered MCP
server's advertised tool schema becomes a pydantic-ai Tool dynamically.
"""

from __future__ import annotations

from . import client

__all__ = ["client"]
