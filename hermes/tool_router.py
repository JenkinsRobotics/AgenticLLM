"""Hermes tool parsing and routing.

Hermes style: the model's response may contain free text plus an optional
<tool_call>{...}</tool_call> XML block. The parser extracts the JSON inside.
No grammar constraint — Hermes is designed for unconstrained decoding.

MCP extension: when an MCP registry is initialized, tools named "mcp:<server>/<tool>"
are routed through it. No prompt/grammar change is needed in the router
itself; hermes/prompts.py picks up the extra schemas dynamically.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from . import tools


ToolFunc = Callable[..., dict[str, Any]]

SAFE_TOOLS: dict[str, ToolFunc] = {
    "get_time": tools.get_time,
    "create_file": tools.create_file,
    "append_file": tools.append_file,
    "delete_file": tools.delete_file,
    "read_file": tools.read_file,
    "list_directory": tools.list_directory,
    "system_status": tools.system_status,
    "calculate": tools.calculate,
    "speak": tools.speak,
    "speak_file": tools.speak_file,
    "web_search": tools.web_search,
}

TOOL_DEFAULT_MODE: dict[str, str] = {
    "get_time": "fast",
    "create_file": "natural",
    "append_file": "natural",
    "delete_file": "natural",
    "read_file": "fast",
    "list_directory": "fast",
    "system_status": "fast",
    "calculate": "fast",
    "speak": "fast",
    "speak_file": "fast",
    "web_search": "natural",
}

_MCP_DEFAULT_MODE = "natural"

TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)


@dataclass
class ToolDecision:
    tool: str | None
    args: dict[str, Any]
    mode: str
    final: str | None = None


def _is_mcp_tool(name: str) -> bool:
    if not name.startswith("mcp:"):
        return False
    try:
        import mcp_bridge
    except ImportError:
        return False
    reg = mcp_bridge.get_registry()
    return reg is not None and reg.has_tool(name)


def parse_decision(text: str) -> ToolDecision:
    match = TOOL_CALL_RE.search(text)
    if not match:
        stripped = text.strip()
        if not stripped:
            raise ValueError("model returned empty response")
        return ToolDecision(tool=None, args={}, mode="final", final=stripped)

    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"tool_call JSON invalid: {exc}") from exc

    name = payload.get("name")
    if name not in SAFE_TOOLS and not _is_mcp_tool(name or ""):
        raise ValueError(f"unknown or unsafe tool: {name}")

    args = payload.get("arguments", {})
    if not isinstance(args, dict):
        raise ValueError("tool arguments must be an object")

    if name in TOOL_DEFAULT_MODE:
        mode = TOOL_DEFAULT_MODE[name]
    elif name and name.startswith("mcp:"):
        mode = _MCP_DEFAULT_MODE
    else:
        mode = "natural"

    return ToolDecision(tool=name, args=args, mode=mode)


def run_tool(decision: ToolDecision) -> dict[str, Any]:
    if decision.tool is None:
        raise ValueError("no tool to run")
    if decision.tool.startswith("mcp:"):
        import mcp_bridge

        return mcp_bridge.call_mcp_tool(decision.tool, decision.args)
    return SAFE_TOOLS[decision.tool](**decision.args)
