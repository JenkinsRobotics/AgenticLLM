"""Pygentic tool parsing and routing.

Pygentic style: the model emits minimal JSON. A GBNF grammar restricts the
output to either a tool call or a {"final": "..."} answer. No prose, no XML.

MCP extension: when an MCP registry is initialized, tools named "mcp:<server>/<tool>"
are routed through it. The grammar is rebuilt to include those names so the
model can emit them and stay format-safe.
"""

from __future__ import annotations

import json
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

# Per-tool default response mode in --mode auto. Tools whose raw output already
# answers the user ("fast") skip the finalize LLM call entirely.
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

# MCP tools default to "natural" — their output is structured content that
# benefits from a short rewrite for the user.
_MCP_DEFAULT_MODE = "natural"


def _gbnf_escape_tool_name(name: str) -> str:
    """Escape a tool name for inclusion as a GBNF string literal alternative.

    GBNF string literals are delimited by " and use \\ for escapes. We allow
    colons and slashes in MCP names; the only character that needs escaping
    inside a quoted alternative is the double-quote itself, which never
    appears in our tool names.
    """
    if '"' in name or "\\" in name:
        raise ValueError(f"unsupported tool name: {name!r}")
    return f'"\\"{name}\\""'


def build_decision_grammar(tool_names: list[str]) -> str:
    alternatives = " | ".join(_gbnf_escape_tool_name(n) for n in tool_names)
    return rf'''
root        ::= tool-call | final-answer
tool-call   ::= "{{\"tool\":" tool-name ",\"args\":" args "}}"
final-answer ::= "{{\"final\":" string "}}"
tool-name   ::= {alternatives}
args        ::= "{{" (kv ("," kv)*)? "}}"
kv          ::= string ":" string
string      ::= "\"" char* "\""
char        ::= [^"\\] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])
'''


DECISION_GRAMMAR = build_decision_grammar(list(SAFE_TOOLS.keys()))


@dataclass
class ToolDecision:
    tool: str | None
    args: dict[str, Any]
    mode: str
    final: str | None = None


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"model did not return JSON: {text!r}")
    return json.loads(cleaned[start:end + 1])


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
    payload = extract_json(text)
    if "final" in payload:
        return ToolDecision(tool=None, args={}, mode="final", final=str(payload["final"]))

    tool = payload.get("tool")
    if tool not in SAFE_TOOLS and not _is_mcp_tool(tool or ""):
        raise ValueError(f"unknown or unsafe tool: {tool}")

    args = payload.get("args", {})
    if not isinstance(args, dict):
        raise ValueError("tool args must be an object")

    mode = payload.get("mode")
    if mode not in {"fast", "natural"}:
        if tool in TOOL_DEFAULT_MODE:
            mode = TOOL_DEFAULT_MODE[tool]
        elif tool and tool.startswith("mcp:"):
            mode = _MCP_DEFAULT_MODE
        else:
            mode = "natural"

    return ToolDecision(tool=tool, args=args, mode=mode)


def run_tool(decision: ToolDecision) -> dict[str, Any]:
    if decision.tool is None:
        raise ValueError("no tool to run")
    if decision.tool.startswith("mcp:"):
        import mcp_bridge

        return mcp_bridge.call_mcp_tool(decision.tool, decision.args)
    return SAFE_TOOLS[decision.tool](**decision.args)
