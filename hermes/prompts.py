"""Prompts for the Hermes Function-Calling framework.

Hermes idiom: tools declared as JSON Schema inside <tools></tools>. Model
emits <tool_call>{"name":"...","arguments":{...}}</tool_call> XML blocks.
Tool results fed back as <tool_response>{...}</tool_response> in a follow-up
user turn. The system prompt is heavier than Pygentic's because it carries
all the tool schemas as JSON in the prefill.
"""

from __future__ import annotations

import json
from typing import Any


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_time",
        "description": "Get the current local date and time.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_file",
        "description": "Create or overwrite a text file in the sandboxed workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path inside the workspace."},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "append_file",
        "description": "Append text to a file in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file from the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": "List a directory inside the workspace.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "system_status",
        "description": "Get machine status (cpu, disk, load average).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "calculate",
        "description": "Evaluate a safe arithmetic expression (+ - * / ** % //).",
        "parameters": {
            "type": "object",
            "properties": {"expression": {"type": "string"}},
            "required": ["expression"],
        },
    },
    {
        "name": "speak",
        "description": "Speak text aloud through the speakers via Kokoro TTS.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "speak_file",
        "description": "Read a workspace file and narrate its contents aloud via Kokoro TTS.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "web_search",
        "description": "DuckDuckGo web search. Returns titles, urls, snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["query"],
        },
    },
]


def system_prompt() -> str:
    schemas_block = json.dumps(TOOL_SCHEMAS, indent=2)
    return f"""You are Lilith, a function-calling AI assistant.

You have access to the following tools. Function signatures are declared as JSON Schema inside <tools></tools> tags:

<tools>
{schemas_block}
</tools>

The only writable area is the sandboxed workspace at hermes/workspace.
All "path" arguments are relative to that workspace root. Do NOT prefix paths
with "hermes/", "workspace/", "~", or any absolute path. If the user asks to
save to their Desktop / Downloads / etc., still save to the workspace —
your follow-up message after the tool result will explain where the file went.

When a tool is needed, respond ONLY with a tool call in this exact format:
<tool_call>
{{"name": "<tool_name>", "arguments": <arguments-object>}}
</tool_call>

If no tool is needed, answer the user directly in plain text (no tags).
"""


FINAL_INSTRUCTIONS = """Now write a short natural answer for the user based ONLY on facts in the tool response above.
Never claim a file landed in a location the tool result did not return.
No markdown unless the user asked for it.
"""
