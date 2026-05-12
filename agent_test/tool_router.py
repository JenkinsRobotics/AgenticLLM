"""Tool parsing and routing for the headless agent test."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from . import tools


ToolFunc = Callable[..., dict[str, Any]]

SAFE_TOOLS: dict[str, ToolFunc] = {
    "get_time": tools.get_time,
    "create_file": tools.create_file,
    "read_file": tools.read_file,
    "list_directory": tools.list_directory,
    "system_status": tools.system_status,
}


@dataclass
class ToolDecision:
    tool: str | None
    args: dict[str, Any]
    mode: str
    final: str | None = None


def extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()

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

    mode = payload.get("mode", "natural")
    if mode not in {"fast", "natural"}:
        mode = "natural"

    return ToolDecision(tool=tool, args=args, mode=mode)


def run_tool(decision: ToolDecision) -> dict[str, Any]:
    if decision.tool is None:
        raise ValueError("no tool to run")
    return SAFE_TOOLS[decision.tool](**decision.args)
