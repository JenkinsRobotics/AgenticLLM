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
    "remember": tools.remember,
    "recall": tools.recall,
    "forget": tools.forget,
    "list_facts": tools.list_facts,
    "get_weather": tools.get_weather,
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
    "remember": "fast",
    "recall": "fast",
    "forget": "fast",
    "list_facts": "fast",
    "get_weather": "fast",
}

_MCP_DEFAULT_MODE = "natural"

# Primary, strict pattern — the format Hermes is documented to use.
_TOOL_CALL_STRICT = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

# Drift-tolerant patterns. Gemma (not a Hermes-tuned model) occasionally
# emits these variants. We accept them because the intent is unambiguous.
_TOOL_CALL_DRIFT = [
    # <|tool_call|>{...}<|/tool_call|>  (chatml-style special tokens)
    re.compile(r"<\|tool_call\|>\s*(\{.*?\})\s*<\|/tool_call\|>", re.DOTALL),
    # <|tool_call|>{...}</tool_call>   (mixed)
    re.compile(r"<\|tool_call\|>\s*(\{.*?\})\s*</tool_call>", re.DOTALL),
    # <|tool_call>...<tool_call|>      (variant the user actually hit)
    re.compile(r"<\|tool_call>\s*(.*?)\s*<tool_call\|>", re.DOTALL),
    # ```tool_call\n{...}\n```          (markdown-fenced)
    re.compile(r"```(?:tool_call|json)?\s*(\{.*?\})\s*```", re.DOTALL),
]

# Final fallback: "call:tool_name{...}" or "call:tool_name(...)" inside
# whatever delimiters the model invented. Extracts (name, args_str).
_CALL_FORM = re.compile(r"call:\s*([a-zA-Z_][\w:/-]*)\s*[\{(]\s*(.*?)\s*[\})]", re.DOTALL)


@dataclass
class ToolDecision:
    tool: str | None
    args: dict[str, Any]
    mode: str
    final: str | None = None
    parse_fallback: str | None = None  # populated when we recovered from drift


def _is_mcp_tool(name: str) -> bool:
    if not name.startswith("mcp:"):
        return False
    try:
        import mcp_bridge
    except ImportError:
        return False
    reg = mcp_bridge.get_registry()
    return reg is not None and reg.has_tool(name)


def _extract_call_payload(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Try strict, then drift-tolerant patterns. Returns (parsed_payload, fallback_label)."""
    m = _TOOL_CALL_STRICT.search(text)
    if m:
        try:
            return json.loads(m.group(1)), None
        except json.JSONDecodeError:
            pass

    for idx, pattern in enumerate(_TOOL_CALL_DRIFT):
        m = pattern.search(text)
        if not m:
            continue
        inner = m.group(1).strip()
        # If the inner part is already valid JSON, accept it.
        if inner.startswith("{"):
            try:
                return json.loads(inner), f"drift_pattern_{idx}"
            except json.JSONDecodeError:
                pass
        # Otherwise try the "call:name{args}" pattern inside.
        call_match = _CALL_FORM.search(inner)
        if call_match:
            name = call_match.group(1)
            args_str = call_match.group(2).strip()
            try:
                args = json.loads("{" + args_str + "}") if args_str and not args_str.startswith("{") else (
                    json.loads(args_str) if args_str else {}
                )
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            return {"name": name, "arguments": args}, f"drift_call_form_{idx}"

    # Last resort: try the call-form anywhere in the text
    call_match = _CALL_FORM.search(text)
    if call_match:
        name = call_match.group(1)
        args_str = call_match.group(2).strip()
        try:
            args = json.loads(args_str) if args_str.startswith("{") else (json.loads("{" + args_str + "}") if args_str else {})
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        return {"name": name, "arguments": args}, "drift_bare_call"

    return None, None


def parse_decision(text: str) -> ToolDecision:
    payload, fallback_label = _extract_call_payload(text)

    if payload is None:
        stripped = text.strip()
        if not stripped:
            raise ValueError("model returned empty response")
        # No call-shape found anywhere — treat as final answer.
        return ToolDecision(tool=None, args={}, mode="final", final=stripped)

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

    return ToolDecision(tool=name, args=args, mode=mode, parse_fallback=fallback_label)


def run_tool(decision: ToolDecision) -> dict[str, Any]:
    if decision.tool is None:
        raise ValueError("no tool to run")
    if decision.tool.startswith("mcp:"):
        import mcp_bridge

        return mcp_bridge.call_mcp_tool(decision.tool, decision.args)
    return SAFE_TOOLS[decision.tool](**decision.args)
