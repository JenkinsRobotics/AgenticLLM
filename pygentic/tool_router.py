"""Pygentic tool parsing and routing.

Pygentic style: the model emits minimal JSON. A GBNF grammar restricts the
output to either a tool call or a {"final": "..."} answer. No prose, no XML.
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
}

# GBNF grammar that constrains the decision step to either a tool call or a
# direct {"final": "..."} answer. Restricting tool names at the grammar level
# means the model literally cannot emit an unsafe or misspelled tool.
DECISION_GRAMMAR = r'''
root        ::= tool-call | final-answer
tool-call   ::= "{\"tool\":" tool-name ",\"args\":" args "}"
final-answer ::= "{\"final\":" string "}"
tool-name   ::= "\"get_time\"" | "\"create_file\"" | "\"append_file\"" | "\"delete_file\"" | "\"read_file\"" | "\"list_directory\"" | "\"system_status\"" | "\"calculate\"" | "\"speak\"" | "\"speak_file\"" | "\"web_search\""
args        ::= "{" (kv ("," kv)*)? "}"
kv          ::= string ":" string
string      ::= "\"" char* "\""
char        ::= [^"\\] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F])
'''


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


def parse_decision(text: str) -> ToolDecision:
    payload = extract_json(text)
    if "final" in payload:
        return ToolDecision(tool=None, args={}, mode="final", final=str(payload["final"]))

    tool = payload.get("tool")
    if tool not in SAFE_TOOLS:
        raise ValueError(f"unknown or unsafe tool: {tool}")

    args = payload.get("args", {})
    if not isinstance(args, dict):
        raise ValueError("tool args must be an object")

    mode = payload.get("mode")
    if mode not in {"fast", "natural"}:
        mode = TOOL_DEFAULT_MODE.get(tool, "natural")

    return ToolDecision(tool=tool, args=args, mode=mode)


def run_tool(decision: ToolDecision) -> dict[str, Any]:
    if decision.tool is None:
        raise ValueError("no tool to run")
    return SAFE_TOOLS[decision.tool](**decision.args)
