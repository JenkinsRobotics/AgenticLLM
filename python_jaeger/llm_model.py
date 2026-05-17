"""Custom Pydantic AI Model that wraps an in-process llama-cpp-python Llama.

Same Llama instance our other frameworks use — no HTTP layer, no separate
llama-server process. We adapt llama-cpp-python's OpenAI-style chat-completion
output to pydantic-ai's ModelMessage / ModelResponse format.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any


# Drift patterns: Gemma 4 (not OpenAI-tuned) sometimes emits tool calls in
# its own XML-ish format that llama-cpp-python's chat handler doesn't
# convert into structured tool_calls. We salvage them here so pydantic-ai
# sees a proper ToolCallPart and not a raw text blob.
_DRIFT_PATTERNS = [
    # <|tool_call>call:name{...}<tool_call|>  (Gemma's native form)
    # Tool names allow `:` and `/` so MCP qualified names like mcp:web/fetch salvage.
    re.compile(r"<\|tool_call>\s*call:\s*([a-zA-Z_][\w:/.\-]*)\s*\{(.*?)\}\s*<tool_call\|>", re.DOTALL),
    # <|tool_call|>{"name": "x", "arguments": {...}}<|/tool_call|>
    re.compile(r"<\|tool_call\|>\s*(\{.*?\})\s*<\|/tool_call\|>", re.DOTALL),
    # <tool_call>{"name": "x", "arguments": {...}}</tool_call>  (standard Hermes)
    re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL),
]


def _parse_loose_args(raw: str) -> dict[str, Any]:
    """Convert Gemma's loose `{timezone:<|"|>Asia/Shanghai<|"|>}` into a clean dict.

    Gemma drops standard JSON quoting in favor of its own special-token
    quotes (`<|"|>...<|"|>`). We strip those and try to parse what's left
    as JSON; if that fails, parse manually.
    """
    cleaned = raw.replace('<|"|>', '"').replace("<|'|>", '"')
    # Try parsing as JSON first
    try:
        result = json.loads("{" + cleaned + "}") if not cleaned.startswith("{") else json.loads(cleaned)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass
    # Manual parse: key:"value" pairs
    pairs: dict[str, Any] = {}
    for match in re.finditer(r"([a-zA-Z_][\w]*)\s*:\s*\"([^\"]*)\"", cleaned):
        pairs[match.group(1)] = match.group(2)
    if pairs:
        return pairs
    # Last resort: try to interpret as bare key:value
    for match in re.finditer(r"([a-zA-Z_][\w]*)\s*:\s*([^,}]+)", cleaned):
        pairs[match.group(1).strip()] = match.group(2).strip().strip('"').strip("'")
    return pairs


def _extract_drift_tool_calls(text: str) -> list[dict[str, Any]]:
    """Find tool calls in non-standard formats. Returns OpenAI-style tool_calls."""
    # Cheap early-exit: every drift pattern starts with `<`. If the model's
    # response has no angle brackets, we know nothing to salvage — skip the
    # three regex sweeps entirely.
    if "<" not in text:
        return []
    out: list[dict[str, Any]] = []
    for pattern in _DRIFT_PATTERNS:
        for match in pattern.finditer(text):
            groups = match.groups()
            if len(groups) == 2:
                # Gemma form: (name, args_inner)
                name = groups[0]
                args = _parse_loose_args(groups[1])
            elif len(groups) == 1:
                # JSON form: {"name": "x", "arguments": {...}}
                try:
                    payload = json.loads(groups[0])
                except json.JSONDecodeError:
                    continue
                name = payload.get("name", "")
                args = payload.get("arguments", {}) or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
            else:
                continue
            if not name:
                continue
            out.append({
                "id": "drift_" + uuid.uuid4().hex[:8],
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            })
    return out

from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage


class LlamaCppModel(Model):
    """Wrap a loaded `llama_cpp.Llama` instance as a Pydantic AI Model."""

    def __init__(self, llama: Any, model_name: str = "local-gemma-4-26b-a4b") -> None:
        self._llama = llama
        self._model_name_value = model_name
        self.last_call_times: list[float] = []
        self.last_call_ttft: list[float] = []
        # OpenAI-format tool defs are stable per agent. Cache by id() of the
        # function_tools list pydantic-ai hands us — saves rebuilding ~20
        # dicts every request.
        self._openai_tools_cache_key: int | None = None
        self._openai_tools_cache_value: list[dict[str, Any]] | None = None

    def reset_timings(self) -> None:
        self.last_call_times = []
        self.last_call_ttft = []

    # --- Model property contract ---------------------------------------------------
    @property
    def model_name(self) -> str:
        return self._model_name_value

    @property
    def system(self) -> str:
        return "local"

    # --- Main request entry point --------------------------------------------------
    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        chat_messages = self._to_chat_messages(messages)
        tools = self._to_openai_tools(model_request_parameters.function_tools)

        settings: dict[str, Any] = dict(model_settings or {})
        kwargs: dict[str, Any] = {
            "messages": chat_messages,
            "max_tokens": settings.get("max_tokens", 2048),
            "temperature": settings.get("temperature", 0.0),
            "top_p": settings.get("top_p", 0.95),
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = settings.get("tool_choice", "auto")

        loop = asyncio.get_running_loop()
        started = time.perf_counter()
        completion = await loop.run_in_executor(
            None, lambda: self._llama.create_chat_completion(**kwargs)
        )
        elapsed = time.perf_counter() - started
        self.last_call_times.append(elapsed)
        # We don't have true TTFT from non-streaming completions, so treat
        # total elapsed as a proxy. Streaming would let us record true TTFT.
        self.last_call_ttft.append(elapsed)
        return self._to_model_response(completion)

    async def request_stream(self, *args, **kwargs):  # type: ignore[override]
        # Streaming is more complex; for now, fall back to non-streaming.
        # Pydantic-AI tolerates this — `Agent.run_sync` and `agent.run` both work.
        raise NotImplementedError("Streaming not implemented for LlamaCppModel")

    # --- Conversions ---------------------------------------------------------------
    def _to_chat_messages(self, messages: list[ModelMessage]) -> list[dict[str, Any]]:
        """Convert pydantic-ai messages to llama-cpp-python chat format.

        Gemma 4's chat template doesn't understand OpenAI's `"role": "tool"`
        message type, so tool returns become user turns with a
        `<tool_response>...</tool_response>` body — the same format
        python_hermes_xml uses successfully. Similarly, assistant turns that
        contain tool calls are serialized as Gemma's native `<tool_call>`
        text rather than the structured `tool_calls` array, which prevents
        llama-cpp-python from getting confused about what the template
        should emit.
        """
        out: list[dict[str, Any]] = []
        for msg in messages:
            kind = getattr(msg, "kind", None)
            if kind == "request":
                for part in msg.parts:
                    pk = getattr(part, "part_kind", None)
                    if pk == "system-prompt":
                        out.append({"role": "system", "content": part.content})
                    elif pk == "user-prompt":
                        content = part.content if isinstance(part.content, str) else str(part.content)
                        out.append({"role": "user", "content": content})
                    elif pk == "tool-return":
                        # Wrap as user-role message with Hermes-style <tool_response>
                        tool_name = getattr(part, "tool_name", "")
                        payload = {"name": tool_name, "content": part.content}
                        body = json.dumps(payload, ensure_ascii=True, default=str)
                        out.append({
                            "role": "user",
                            "content": f"<tool_response>\n{body}\n</tool_response>",
                        })
            elif kind == "response":
                texts: list[str] = []
                tool_call_strs: list[str] = []
                for part in msg.parts:
                    pk = getattr(part, "part_kind", None)
                    if pk == "text":
                        texts.append(part.content)
                    elif pk == "tool-call":
                        args_val = part.args
                        if isinstance(args_val, str):
                            try:
                                args_dict = json.loads(args_val)
                            except json.JSONDecodeError:
                                args_dict = {}
                        else:
                            args_dict = args_val or {}
                        call_json = json.dumps(
                            {"name": part.tool_name, "arguments": args_dict},
                            ensure_ascii=True,
                        )
                        tool_call_strs.append(f"<tool_call>\n{call_json}\n</tool_call>")
                content_pieces = [t for t in texts if t]
                content_pieces.extend(tool_call_strs)
                content = "\n".join(content_pieces) if content_pieces else ""
                out.append({"role": "assistant", "content": content})
        return out

    def _to_openai_tools(self, function_tools: list[Any]) -> list[dict[str, Any]]:
        # Pydantic-AI hands us the same function_tools list every request for
        # a given agent. Cache the OpenAI conversion by `id()` so we don't
        # rebuild ~20 dicts on every turn.
        key = id(function_tools) if function_tools else 0
        if key == self._openai_tools_cache_key and self._openai_tools_cache_value is not None:
            return self._openai_tools_cache_value
        result: list[dict[str, Any]] = []
        for t in function_tools or []:
            schema = getattr(t, "parameters_json_schema", None) or {"type": "object", "properties": {}}
            result.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": schema,
                },
            })
        self._openai_tools_cache_key = key
        self._openai_tools_cache_value = result
        return result

    def _to_model_response(self, completion: dict[str, Any]) -> ModelResponse:
        choice = completion["choices"][0]
        msg = choice["message"]
        parts: list[Any] = []

        content = msg.get("content")
        raw_tool_calls = list(msg.get("tool_calls") or [])

        # If llama-cpp-python didn't parse tool calls but the content looks
        # like a drift-format tool invocation, salvage it. Also strip the
        # tool-call XML out of any remaining text so we don't double-emit.
        if content:
            drifted = _extract_drift_tool_calls(content)
            if drifted:
                raw_tool_calls.extend(drifted)
                # Remove all drift-pattern matches from content so the visible
                # text is just the model's prose (if any).
                cleaned = content
                for pattern in _DRIFT_PATTERNS:
                    cleaned = pattern.sub("", cleaned)
                cleaned = cleaned.strip()
                content = cleaned if cleaned else None

        if content:
            parts.append(TextPart(content=content))

        for tc in raw_tool_calls:
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                args = {}
            parts.append(ToolCallPart(
                tool_name=fn.get("name", ""),
                args=args,
                tool_call_id=tc.get("id") or str(uuid.uuid4()),
            ))

        usage_data = completion.get("usage") or {}
        usage = RequestUsage(
            input_tokens=int(usage_data.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage_data.get("completion_tokens", 0) or 0),
        )

        return ModelResponse(
            parts=parts,
            usage=usage,
            model_name=self._model_name_value,
            timestamp=datetime.now(timezone.utc),
        )
