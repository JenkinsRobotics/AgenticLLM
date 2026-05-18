#!/usr/bin/env python3
"""CLI loop for the Pydantic AI framework wrapper.

Reuses the same in-process llama-cpp-python `Llama` instance our other
frameworks load. The agent loop, tool calling, message conversion, retry
logic — all of that is handled by pydantic-ai itself. We provide:
  - LlamaCppModel: in-process adapter for the local Gemma model
  - The 19 in-process tools + every tool exposed by configured MCP servers
  - Memory extension (identity injection + episodic continuity)
  - Thinking extension (background planning calls)
  - A run_command shim with the same signature bench.py expects from the
    other frameworks, so the comparison harness works uniformly.

CLI flags:
  --with-memory   Inject identity.md, load recent episodic turns, append
                  every new turn to memory/episodic.jsonl.
  --with-mcp      Register the MCP fetch tool from mcp_config.json.
  --think         Run a background thinking call after each turn.
  --no-warm-tts   Skip Kokoro warmup at startup.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, CallToolsNode, ModelRequestNode, Tool
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import RequestUsage

from .core import prompts
from .core import tools  # built-in tool implementations live in core/tools/
from .core.llm_model import LlamaCppModel


# Tools whose dict result already *is* the user-facing answer. When the agent
# picks one of these and there are no other tool calls in the same response,
# we skip pydantic-ai's "final-answer" LLM round-trip (~285ms saved per turn).
# The formatter below renders each result dict into a one-line plain string
# that matches what the LLM would have generated.
SKIP_FINAL_TOOLS = frozenset({
    "get_time",
    "calculate",
    "system_status",
    "list_facts",
    "recall",
    "remember",
    "forget",
    "delete_file",
    "create_file",
    "append_file",
    "open_file",
    "open_app",
    "launch_url",
    # The speak/speak_file tools already vocalize the answer; the user has
    # heard it. Asking the LLM to add "OK." costs ~280ms for no benefit.
    "speak",
    "speak_file",
    # ask_user IS the final turn — the question is the answer, the next
    # phrase from the user is the next turn's input.
    "ask_user",
    # Scheduling tools have natural one-line confirmations — no need for
    # a final LLM rewrite. Faster and avoids the post-long-output
    # "agent responds with empty text" edge case the validation found.
    "schedule_prompt",
    "cancel_schedule",
    # delegate's `answer` field IS the user-facing response from the subagent.
    "delegate",
    # send_message returns a tight {sent: bool, ...} that has a natural
    # one-line confirmation; no LLM summarization needed.
    "send_message",
    # help_me returns a curated capability list; the LLM doesn't need to
    # re-summarize it — the summary IS the answer.
    "help_me",
})


def _format_tool_result_as_answer(name: str, result: Any) -> str:
    """Render a tool result dict into the short final answer the LLM would
    have generated, so we can skip the final-LLM round-trip."""
    if not isinstance(result, dict):
        return str(result)

    if name == "get_time":
        return result.get("datetime") or "Time unavailable."
    if name == "calculate":
        val = result.get("result")
        return str(val) if val is not None else "Calculation failed."
    if name == "system_status":
        load = result.get("load_average")
        disk = result.get("disk") or {}
        parts = []
        if load:
            parts.append(f"load {load[0]:.2f}/{load[1]:.2f}/{load[2]:.2f}")
        if disk:
            parts.append(
                f"disk {disk.get('used_gb', 0):.1f}/{disk.get('total_gb', 0):.1f} GB "
                f"({disk.get('free_gb', 0):.1f} GB free)"
            )
        return ", ".join(parts) or "System status unavailable."
    if name == "list_facts":
        facts = result.get("facts") or {}
        if not facts:
            return "I don't have any facts saved about you yet."
        return "; ".join(f"{k}: {v}" for k, v in facts.items())
    if name == "recall":
        if result.get("found"):
            return str(result.get("value", ""))
        return f"I don't have a value for {result.get('key')!r}."
    if name == "remember":
        return f"Got it — remembered {result.get('key')!r}." if result.get("remembered") else "Couldn't save that."
    if name == "forget":
        if result.get("forgotten"):
            return f"Forgot {result.get('key')!r}."
        return f"No saved value under {result.get('key')!r}."
    if name == "delete_file":
        return f"Deleted {result.get('path', '')}." if result.get("deleted") else "Couldn't delete that file."
    if name in ("create_file", "append_file"):
        if result.get("created") or result.get("appended"):
            return f"Saved to {result.get('path', '')}."
        return "Couldn't save that file."
    if name == "open_file":
        return f"Opened {result.get('path', '')}." if result.get("opened") else "Couldn't open that file."
    if name == "open_app":
        return f"Launched {result.get('app', '')}." if result.get("opened") else "Couldn't launch that app."
    if name == "launch_url":
        return f"Opened {result.get('url', '')}." if result.get("opened") else "Couldn't open that URL."
    if name in ("speak", "speak_file"):
        # The audio has played. No extra text needed for the user.
        if result.get("spoken") is True:
            return ""
        return f"Couldn't speak: {result.get('reason', 'unknown')}"
    if name == "ask_user":
        # The question IS the final answer this turn — the voice loop will
        # speak it and the user's next phrase becomes the answer next turn.
        if result.get("asked") is True:
            return str(result.get("question") or "")
        return "(no question to ask)"
    if name == "schedule_prompt":
        if result.get("scheduled"):
            sname = result.get("name", "?")
            nxt = result.get("next_run_at", "?")
            return f"Scheduled {sname!r} — next run at {nxt}."
        return f"Couldn't schedule: {result.get('error', 'unknown')}"
    if name == "cancel_schedule":
        if result.get("cancelled"):
            return f"Cancelled schedule {result.get('name')!r}."
        return f"No schedule named {result.get('name')!r} to cancel."
    if name == "delegate":
        if result.get("delegated"):
            return str(result.get("answer") or "")
        return f"Delegation failed: {result.get('error', 'unknown')}"
    if name == "send_message":
        if result.get("sent"):
            return f"Sent."
        return f"Couldn't send: {result.get('error', 'unknown')}"
    if name == "help_me":
        summary = (result.get("summary") or "").strip()
        cli = "\n".join(f"  {line}" for line in result.get("cli_commands") or [])
        tip = (result.get("tip") or "").strip()
        chunks = [summary]
        if cli:
            chunks.append(f"CLI commands:\n{cli}")
        if tip:
            chunks.append(tip)
        return "\n\n".join(c for c in chunks if c)
    return str(result)


LOG_DIR = Path(__file__).resolve().parent / "logs"


def _resolve_model_path() -> Path:
    """GGUF resolution chain. Mirrors model_resolver.py at repo root —
    framework isolation rules forbid us from importing that module, so
    the logic is duplicated here. Update both when the chain changes.

    Order: AGENTICLLM_MODEL_PATH env var > HERMES_LLM_MODEL env var
    (legacy) > <repo>/models/gemma-4-26B-A4B-it-Q4_K_M.gguf > LM Studio default.
    """
    for env_var in ("AGENTICLLM_MODEL_PATH", "HERMES_LLM_MODEL"):
        v = os.environ.get(env_var)
        if v:
            return Path(v).expanduser()
    # one level up from this framework dir, then into models/
    local = Path(__file__).resolve().parent.parent / "models" / "gemma-4-26B-A4B-it-Q4_K_M.gguf"
    if local.exists():
        return local
    return Path(
        "/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/"
        "gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf"
    )


DEFAULT_MODEL_PATH = _resolve_model_path()


# ============================================================================
# Pipeline state — populated by init_extensions; read by run_command + agent
# ============================================================================
_pipeline: dict[str, Any] = {
    "system_prompt": prompts.SYSTEM_PROMPT,
    "llm_lock": None,            # threading.Lock() when --think is on
    "thinking_runner": None,     # ThinkingRunner when --think is on
    "with_memory": False,
    "with_mcp": False,
    "with_thinking": False,
    # Client reference used by the `delegate` tool to recursively invoke
    # the same agent. Set in init_extensions.
    "client": None,
    # Whether the KV cache has already been primed with system prompt +
    # tool schema (set by `prewarm`). Once True, the first user-facing
    # turn skips its cold-cache prefill penalty.
    "prewarmed": False,
    # User-facing display preferences (filled in from memory/config.json at
    # startup; toggled live via /latency, /tools, etc. slash commands).
    "show_latency": False,
    "show_tool_activity": True,
}

# Conversation history maintained across run_command calls (only populated
# when --with-memory is on). Each element is a pydantic-ai ModelMessage.
#
# Per-session: keyed by an opaque session_key (e.g. "cli", "voice",
# "telegram:12345", "discord:67890"). Each chat keeps its own ~20-message
# rolling window so the Telegram bot's context never leaks into the CLI
# loop (and vice versa) when both run in the same gateway process. On
# first access, recent turns are lazy-loaded from episodic.jsonl filtered
# to that session_key — so a process restart still feels like a continuous
# chat to each individual user.
_DEFAULT_SESSION_KEY = "cli"
_session_histories: dict[str, list[Any]] = {}
_session_loaded: set[str] = set()
_MAX_HISTORY_MESSAGES = 20  # ~10 user+assistant pairs


@dataclass
class LatencyReport:
    total: float
    tool_calls: int
    decision: float       # cumulative time inside LlamaCppModel.request()
    decision_ttft: float  # time of the FIRST LLM call
    tool: float           # elapsed - decision (Python tool exec + Pydantic overhead)
    final: float          # time of the LAST LLM call (the summary)
    final_ttft: float     # same as `final` since we don't stream


def print_latency(report: LatencyReport) -> None:
    print("Latency:")
    print(f"- decision: {report.decision:.3f}s  (ttft {report.decision_ttft:.3f}s)")
    print(f"- tool: {report.tool:.3f}s")
    print(f"- final: {report.final:.3f}s  (ttft {report.final_ttft:.3f}s)")
    print(f"- total: {report.total:.3f}s  (tool_calls: {report.tool_calls})")


def write_log(entry: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "latency.jsonl"
    entry = {
        "framework": "python_pydantic_ai",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": os.environ.get("BENCH_RUN_ID"),
        **entry,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True, default=str) + "\n")

    if _pipeline["with_memory"]:
        _record_turn(entry)


def _record_turn(entry: dict[str, Any]) -> None:
    """Append this turn to the cross-session episodic log (when memory on)."""
    user = entry.get("user")
    if not user:
        return
    try:
        from .memory.memory_module import append_episodic

        append_episodic({
            "timestamp": entry.get("timestamp"),
            "framework": "python_pydantic_ai",
            "session_key": entry.get("session_key"),
            "user": user,
            "decision_raw": json.dumps(entry.get("decision"), ensure_ascii=True, default=str)
                if entry.get("decision") is not None
                else None,
            "answer": entry.get("answer"),
            "run_id": entry.get("run_id"),
        })
    except Exception as exc:
        print(f"[python_pydantic_ai] episodic append failed: {exc}", file=sys.stderr, flush=True)


def _get_session_history(session_key: str) -> list[Any]:
    """Return the in-memory history list for `session_key`, lazy-loading
    that session's prior turns from episodic.jsonl on first access.

    Only called when --with-memory is on (otherwise we always pass None to
    the agent, no history mixing possible).
    """
    history = _session_histories.get(session_key)
    if history is None:
        history = []
        _session_histories[session_key] = history

    if session_key not in _session_loaded:
        _session_loaded.add(session_key)
        try:
            from .memory.memory_module import load_recent_turns

            recent_dicts = load_recent_turns(n=5, session_key=session_key)
            if recent_dicts:
                history.extend(_episodic_to_messages(recent_dicts))
                print(
                    f"[python_pydantic_ai] resumed {session_key!r}: {len(recent_dicts)//2} prior turn(s) loaded.",
                    flush=True,
                )
        except Exception as exc:
            print(
                f"[python_pydantic_ai] resume for {session_key!r} skipped: {exc}",
                file=sys.stderr, flush=True,
            )
    return history


# ============================================================================
# Agent construction
# ============================================================================
def _build_mcp_tools(specs: list[Any]) -> list[Tool]:
    """Build Pydantic AI Tool objects for every MCP tool the bridge exposes.

    Each MCP tool's advertised JSON Schema becomes the pydantic-ai tool
    schema directly via Tool.from_schema, so adding a new MCP server in
    mcp_config.json automatically surfaces its tools — no code change.
    """
    if not specs:
        return []

    tools_list: list[Tool] = []
    for spec in specs:
        schema = spec.input_schema if isinstance(spec.input_schema, dict) else {}
        if not schema or "type" not in schema:
            schema = {"type": "object", "properties": {}, **schema}

        def _make_caller(qualified_name: str):
            def _call(**kwargs: Any) -> dict[str, Any]:
                from .plugins.mcp import client as mcp_client

                return mcp_client.call_mcp_tool(qualified_name, kwargs)

            _call.__name__ = qualified_name.replace(":", "_").replace("/", "_")
            return _call

        tools_list.append(
            Tool.from_schema(
                function=_make_caller(spec.qualified_name),
                name=spec.qualified_name,
                description=spec.description or f"MCP tool {spec.qualified_name}",
                json_schema=schema,
            )
        )
    return tools_list


def build_agent(
    client: Any,
    system_prompt: str,
    mcp_specs: list[Any] | None = None,
) -> Agent[None, str]:
    """Build a Pydantic AI Agent backed by our in-process llama-cpp-python model.

    Registers the 19 in-process tools. Any tools advertised by an MCP server
    via mcp_bridge are registered dynamically from their JSON Schema, so
    adding a new MCP server requires no code change here.
    """
    model = LlamaCppModel(client.llm)
    agent: Agent[None, str] = Agent(
        model=model,
        system_prompt=system_prompt,
        tool_retries=2,
        tools=_build_mcp_tools(mcp_specs or []),
    )

    @agent.tool_plain
    def get_time(timezone: str | None = None) -> dict:
        """Get the current date/time, optionally in a specific IANA timezone (e.g. 'Asia/Shanghai')."""
        return tools.get_time(timezone=timezone)

    @agent.tool_plain
    def create_file(path: str, content: str) -> dict:
        """Write a text file in the sandboxed workspace. Overwrites if it already exists."""
        return tools.create_file(path=path, content=content)

    @agent.tool_plain
    def append_file(path: str, content: str) -> dict:
        """Append text to an existing workspace file."""
        return tools.append_file(path=path, content=content)

    @agent.tool_plain
    def delete_file(path: str, confirm: bool = False) -> dict:
        """Delete a file from the workspace.

        In voice / production mode (env DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1)
        you must first call this without `confirm` to get a preview, ask
        the user via `ask_user`, then call again with `confirm=True`.
        In default / bench mode `confirm` is ignored and deletion is
        immediate.
        """
        return tools.delete_file(path=path, confirm=confirm)

    @agent.tool_plain
    def read_file(path: str) -> dict:
        """Read a workspace text file."""
        return tools.read_file(path=path)

    @agent.tool_plain
    def list_directory(path: str = ".") -> dict:
        """List entries in a workspace directory."""
        return tools.list_directory(path=path)

    @agent.tool_plain
    def system_status() -> dict:
        """Get current machine status (cpu, disk, load average)."""
        return tools.system_status()

    @agent.tool_plain
    def help_me() -> dict:
        """Show what the agent can do — call when the user asks for help,
        a capability overview, or "what can you do?" / "what tools do you have?"."""
        return tools.help_me()

    @agent.tool_plain
    def delegate(subtask: str) -> dict:
        """Hand off a focused subtask to a fresh subagent.

        Use this to split a complex request into independent pieces — e.g.
        "search the web for X, then save the top result to a file" is one
        delegate call for the web search and one for the save. The subagent
        runs in its own context (no parent history) but shares memory and
        the same toolset. Depth-limited to prevent runaway recursion.
        """
        client_ref = _pipeline.get("client")
        if client_ref is None:
            return {"delegated": False, "error": "no client wired — call init_extensions first"}
        clean = (subtask or "").strip()
        if not clean:
            return {"delegated": False, "error": "empty subtask"}
        return _delegate_internal(client_ref, clean)

    @agent.tool_plain
    def send_message(channel: str, recipient: str, text: str) -> dict:
        """Send a proactive message to a user on a messaging channel.

        Available `channel` values depend on which bridges are live in
        this process — typically "discord", "telegram", "imessage".
        `recipient` is the channel-specific ID (numeric Discord user ID,
        Telegram chat ID, or iMessage phone/Apple-ID handle).

        Use this together with `schedule_prompt` to send unattended
        notifications: schedule a prompt that says "send the weather to
        Discord user 12345" and the cron runner will fire it on time.
        """
        return tools.send_message(channel=channel, recipient=recipient, text=text)

    @agent.tool_plain
    def schedule_prompt(cron_expr: str, prompt: str, name: str | None = None) -> dict:
        """Schedule a prompt for unattended execution on a cron expression.

        Examples:
          "0 7 * * *"         — every day at 7 AM
          "*/10 * * * *"      — every 10 minutes
          "0 9 * * MON-FRI"   — 9 AM on weekdays
        The schedule fires in the same agent loop a fresh user turn would.
        """
        return tools.schedule_prompt(cron_expr=cron_expr, prompt=prompt, name=name)

    @agent.tool_plain
    def list_schedules() -> dict:
        """List every active scheduled prompt with its next-run timestamp."""
        return tools.list_schedules()

    @agent.tool_plain
    def cancel_schedule(name: str) -> dict:
        """Cancel a previously-scheduled prompt by name."""
        return tools.cancel_schedule(name=name)

    @agent.tool_plain
    def search_memory(query: str, k: int = 5) -> dict:
        """Semantic search over the cross-session episodic log.

        Returns the past user/assistant turns most relevant to `query`.
        Use this when `recall` (exact-key) is too narrow — natural
        questions like "what did we talk about yesterday?" or "what's my
        dog's name?" go through this tool.
        """
        return tools.search_memory(query=query, k=k)

    @agent.tool_plain
    def ask_user(question: str) -> dict:
        """Ask the user a clarifying question instead of guessing.

        Use this whenever the request is ambiguous — missing names, unclear
        pronouns ("open it" / "delete that"), missing destinations, two
        plausible interpretations. The voice loop speaks the question and
        waits for the user's next phrase as the answer.
        """
        return tools.ask_user(question=question)

    @agent.tool_plain
    def generate_image(
        prompt: str,
        out_path: str = "generated.png",
        num_inference_steps: int = 1,
        guidance_scale: float = 0.0,
        seed: int | None = None,
    ) -> dict:
        """Generate an image from a text prompt and save it in the workspace.

        Uses a local SDXL-Turbo pipeline (no internet at inference time).
        First call lazy-downloads ~6 GB of weights; subsequent calls are
        ~1–3 s per image on Apple Silicon. `out_path` is workspace-relative.
        """
        return tools.generate_image(
            prompt=prompt,
            out_path=out_path,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            seed=seed,
        )

    @agent.tool_plain
    def look_at(image_path: str, question: str = "Describe this image in one short sentence.") -> dict:
        """Look at a workspace image file and answer a question about it.

        Use this when the user references a photo, screenshot, or anything
        they want you to *see*. `image_path` is workspace-relative. The
        first call lazy-loads a small local vision model (~1.9 B params);
        subsequent calls are fast.
        """
        return tools.look_at(image_path=image_path, question=question)

    @agent.tool_plain
    def run_python(code: str, timeout_s: float = 10.0) -> dict:
        """Execute a snippet of Python in a sandboxed subprocess.

        Use this for novel problems that don't have a dedicated tool:
        non-trivial math, data wrangling, regex on a string, parsing a
        chunk of JSON the user pasted, etc. The snippet runs in a fresh
        interpreter with a 10-second timeout and an isolated temp dir.
        Print the answer to stdout — the tool result captures stdout.
        """
        return tools.run_python(code=code, timeout_s=timeout_s)

    @agent.tool_plain
    def calculate(expression: str) -> dict:
        """Evaluate a safe arithmetic expression (+ - * / ** % //)."""
        return tools.calculate(expression=expression)

    @agent.tool_plain
    def speak(text: str) -> dict:
        """Speak text aloud through the speakers via Kokoro TTS. Supports SSML pauses."""
        return tools.speak(text=text)

    @agent.tool_plain
    def speak_file(path: str) -> dict:
        """MANDATORY when the user asks to "read", "narrate", or "speak"
        a named workspace FILE aloud ("read bench.txt out loud", "narrate
        youtube_intro.txt", "speak the script as if for a video"). Reads
        the file's contents and pipes them to Kokoro TTS. Use this — not
        `speak` — whenever a file path is involved."""
        return tools.speak_file(path=path)

    @agent.tool_plain
    def web_search(query: str, max_results: int = 5) -> dict:
        """DuckDuckGo web search. Returns titles, URLs, and snippets."""
        return tools.web_search(query=query, max_results=max_results)

    @agent.tool_plain
    def get_weather(location: str) -> dict:
        """Look up current weather at a named location via wttr.in."""
        return tools.get_weather(location=location)

    @agent.tool_plain
    def remember(key: str, value: str) -> dict:
        """MANDATORY when the user states a preference, identity fact,
        plan, or anything they might recall later ("remember that…",
        "my favorite X is…", "I'll be in town on…"). Call this
        proactively — do NOT just acknowledge in text. Pick a
        descriptive snake_case key."""
        return tools.remember(key=key, value=value)

    @agent.tool_plain
    def recall(key: str) -> dict:
        """MANDATORY when the user asks about something they told you
        earlier ("what did I say my…", "do you remember…", "what's my
        favorite X", "what video length do I prefer?"). Call BEFORE
        answering — the persisted store is the source of truth.
        Fuzzy/word-overlap matching is supported, so close-but-not-exact
        keys still hit. Try `recall` first; only fall back to
        `search_memory` if both `recall` and `list_facts` miss."""
        return tools.recall(key=key)

    @agent.tool_plain
    def forget(key: str, confirm: bool = False) -> dict:
        """MANDATORY when the user asks to remove a stored fact
        ("forget my X", "remove my X preference", "I changed my mind
        about X"). Call this — don't just acknowledge in text.

        Same approval semantics as delete_file when
        DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1."""
        return tools.forget(key=key, confirm=confirm)

    @agent.tool_plain
    def list_facts() -> dict:
        """MANDATORY for open-ended "what do you know about me?" or
        "what have I told you?" questions. Returns the full k/v store.
        Use this before falling back to free-text 'I don't know'."""
        return tools.list_facts()

    @agent.tool_plain
    def launch_url(url: str) -> dict:
        """Open a URL in the user's default web browser (macOS only)."""
        return tools.launch_url(url=url)

    @agent.tool_plain
    def open_file(path: str) -> dict:
        """Open a workspace file in its default macOS app."""
        return tools.open_file(path=path)

    @agent.tool_plain
    def open_app(app_name: str) -> dict:
        """Launch a macOS application by name."""
        return tools.open_app(app_name=app_name)

    return agent


# Agent cache. Keyed by a tuple that captures everything that would force a
# rebuild: client id, system prompt content, MCP tool list.
_agent_cache: dict[tuple, Agent[None, str]] = {}


def _agent_cache_key(client: Any) -> tuple:
    mcp_names = tuple(sorted(s.qualified_name for s in _pipeline.get("mcp_specs") or []))
    return (id(client), hash(_pipeline["system_prompt"]), mcp_names)


def _get_agent(client: Any) -> Agent[None, str]:
    key = _agent_cache_key(client)
    if key not in _agent_cache:
        # Keep cache small — only the latest config
        _agent_cache.clear()
        _agent_cache[key] = build_agent(
            client,
            system_prompt=_pipeline["system_prompt"],
            mcp_specs=_pipeline.get("mcp_specs"),
        )
    return _agent_cache[key]


# ============================================================================
# Memory: convert episodic.jsonl entries to pydantic-ai ModelMessages
# ============================================================================
def _episodic_to_messages(turns: list[dict[str, str]]) -> list[Any]:
    """Convert (user, assistant) message dicts into pydantic-ai ModelMessages.

    Each pair becomes:
      ModelRequest(parts=[UserPromptPart(content=user)])
      ModelResponse(parts=[TextPart(content=answer)])
    """
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )
    from pydantic_ai.usage import RequestUsage

    out: list[Any] = []
    pending_user: str | None = None
    for entry in turns:
        role = entry.get("role")
        content = entry.get("content")
        if not isinstance(content, str):
            continue
        if role == "user":
            pending_user = content
        elif role == "assistant" and pending_user is not None:
            out.append(ModelRequest(parts=[UserPromptPart(content=pending_user)]))
            out.append(ModelResponse(
                parts=[TextPart(content=content)],
                usage=RequestUsage(input_tokens=0, output_tokens=0),
                model_name="local-gemma-4-26b-a4b",
                timestamp=datetime.now(timezone.utc),
            ))
            pending_user = None
    return out


# Maximum nesting depth for delegate() — guards against infinite recursion
# if the subagent decides to delegate again. Configurable via env so a robot
# can lower it for tighter resource bounds.
_DELEGATE_MAX_DEPTH = int(os.environ.get("DELEGATE_MAX_DEPTH", "2"))
_delegate_depth = threading.local()


async def _run_via_iter(
    agent: Agent,
    user_text: str,
    message_history: list[Any] | None,
) -> dict[str, Any]:
    """Drive the agent step-by-step via agent.iter() so we can intercept
    before the final-answer LLM call fires.

    Returns a dict with:
      - result: the AgentRun's result (None if we skipped)
      - skipped: True when we short-circuited the final LLM call
      - skipped_text: the synthesized final answer (when skipped)
      - skipped_msgs: the messages to extend session history with (when skipped)
      - first_decision: the first tool the agent picked
    """
    first_decision: dict[str, Any] | None = None
    skip_final = False
    skip_tool_name: str | None = None
    skip_result: Any = None

    async with agent.iter(user_text, message_history=message_history or None) as run:
        async for node in run:
            if isinstance(node, CallToolsNode):
                tool_parts = [
                    p for p in node.model_response.parts
                    if hasattr(p, "tool_call_id")
                ]
                if first_decision is None and tool_parts:
                    tc = tool_parts[0]
                    first_decision = {"tool": tc.tool_name, "args": tc.args, "mode": "natural"}
                    if len(tool_parts) == 1 and tc.tool_name in SKIP_FINAL_TOOLS:
                        skip_final = True
                        skip_tool_name = tc.tool_name

            # When the next ModelRequestNode appears AFTER our skip-tool's
            # CallToolsNode, that's the would-be final LLM call. The tool
            # return is in node.request.parts — read it and bail out so
            # pydantic-ai never fires the LLM.
            if skip_final and isinstance(node, ModelRequestNode):
                for p in node.request.parts:
                    if isinstance(p, ToolReturnPart):
                        skip_result = p.content
                        break
                if skip_result is not None:
                    break
        else:
            # Loop exhausted normally — End was reached, final LLM ran.
            return {
                "result": run.result,
                "skipped": False,
                "first_decision": first_decision,
            }

    # Skip path. Synthesize the final answer and build the minimal pair of
    # messages to extend session history with (we keep the conversation in
    # canonical user → assistant form rather than leaking the tool internals).
    text = _format_tool_result_as_answer(skip_tool_name or "", skip_result)
    skipped_msgs = [
        ModelRequest(parts=[UserPromptPart(content=user_text)]),
        ModelResponse(
            parts=[TextPart(content=text)],
            usage=RequestUsage(input_tokens=0, output_tokens=0),
            model_name="local-gemma-4-26b-a4b",
            timestamp=datetime.now(timezone.utc),
        ),
    ]
    return {
        "result": None,
        "skipped": True,
        "skipped_text": text,
        "skipped_msgs": skipped_msgs,
        "first_decision": first_decision,
    }


# ============================================================================
# run_command — main agent invocation, with latency split + history mgmt
# ============================================================================
def prewarm(client: Any) -> None:
    """Prime the KV cache so the first user-facing turn isn't cold.

    The first agent call against a freshly-loaded model pays a ~1 s
    prefill cost to tokenize the system prompt + the 28-tool schema. By
    running a single trivial turn at startup (output discarded), we shift
    that cost from "what time is it" to the load phase — where the user
    already accepts a wait. Idempotent.
    """
    if _pipeline.get("prewarmed"):
        return
    started = time.perf_counter()
    try:
        agent = _get_agent(client)
        # A turn that's almost certain to produce a short free-text reply
        # (no tool call), so we pay decode for ~1 prefill + a handful of
        # tokens of generation. We don't keep history or log this turn.
        agent.run_sync("Respond with just the word ready.")
    except Exception as exc:
        print(f"[python_pydantic_ai] prewarm skipped: {exc}", flush=True)
        return
    _pipeline["prewarmed"] = True
    print(f"[python_pydantic_ai] agent prewarmed in {time.perf_counter() - started:.1f}s", flush=True)


def _delegate_internal(client: Any, subtask: str) -> dict[str, Any]:
    """Run a subtask through the same agent with a depth guard.

    No message_history is passed — the subagent gets a fresh context so it
    can focus on the subtask without dragging in the parent's conversation.
    Memory tools still hit the shared `memory/` store, so facts persist.
    """
    depth = getattr(_delegate_depth, "value", 0)
    if depth >= _DELEGATE_MAX_DEPTH:
        return {
            "delegated": False,
            "error": f"delegate recursion limit hit ({_DELEGATE_MAX_DEPTH}); "
                     "the subagent tried to delegate again — refusing.",
        }

    _delegate_depth.value = depth + 1
    started = time.perf_counter()
    try:
        agent = _get_agent(client)
        iter_out = asyncio.run(_run_via_iter(agent, subtask, None))
    finally:
        _delegate_depth.value = depth

    elapsed = time.perf_counter() - started
    if iter_out["skipped"]:
        text = iter_out["skipped_text"]
    else:
        result = iter_out.get("result")
        text = (getattr(result, "output", None) if result else "") or ""
    return {
        "delegated": True,
        "subtask": subtask,
        "answer": text.strip(),
        "depth": depth + 1,
        "elapsed_s": round(elapsed, 3),
    }


def run_command(client: Any, user_text: str, default_mode: str, session_key: str | None = None) -> None:
    """Compatible with bench.py's expected (client, user_text, mode) signature.

    `default_mode` is accepted for API parity but ignored — pydantic-ai
    decides the loop dynamics on its own. `session_key` selects which
    per-channel rolling history this turn uses; defaults to "cli".
    """
    key = session_key or _DEFAULT_SESSION_KEY
    history = _get_session_history(key) if _pipeline["with_memory"] else None
    agent = _get_agent(client)
    model: LlamaCppModel = agent.model  # type: ignore[assignment]
    model.reset_timings()

    lock = _pipeline["llm_lock"]
    started = time.perf_counter()
    try:
        if lock is not None:
            with lock:
                iter_out = asyncio.run(_run_via_iter(agent, user_text, history))
        else:
            iter_out = asyncio.run(_run_via_iter(agent, user_text, history))
    except Exception as exc:
        elapsed = time.perf_counter() - started
        print(f"Pydantic AI agent failed: {exc}")
        report = LatencyReport(
            total=elapsed,
            tool_calls=0,
            decision=0.0,
            decision_ttft=0.0,
            tool=0.0,
            final=0.0,
            final_ttft=0.0,
        )
        print_latency(report)
        write_log({
            "user": user_text,
            "session_key": key,
            "error": str(exc),
            "latency": asdict(report),
        })
        return

    elapsed = time.perf_counter() - started
    skipped = iter_out["skipped"]
    first_decision = iter_out["first_decision"]
    result = iter_out.get("result")

    if skipped:
        answer = iter_out["skipped_text"]
        # Synthesize the tool_activity line so the caller still sees what happened.
        if first_decision is not None:
            tool_activity = [
                _format_call_line(first_decision["tool"], first_decision.get("args") or {}, None)
            ]
        else:
            tool_activity = []
    else:
        answer = result.output if hasattr(result, "output") else str(result)
        tool_activity, walked_decision = _walk_new_messages(result)
        first_decision = first_decision or walked_decision
    tool_calls = len(tool_activity)

    llm_times = list(model.last_call_times)
    decision_total = sum(llm_times)
    decision_first = llm_times[0] if llm_times else 0.0
    final_last = llm_times[-1] if len(llm_times) >= 1 else 0.0
    tool_total = max(0.0, elapsed - decision_total)

    report = LatencyReport(
        total=elapsed,
        tool_calls=tool_calls,
        decision=decision_total,
        decision_ttft=decision_first,
        tool=tool_total,
        final=final_last if len(llm_times) > 1 else 0.0,
        final_ttft=final_last if len(llm_times) > 1 else 0.0,
    )

    if _pipeline.get("show_tool_activity", True):
        for line in tool_activity:
            print(line)
    if answer:
        print(answer)
    if _pipeline.get("show_latency", False):
        print_latency(report)
        if skipped:
            print("  (final-LLM skipped — tool result returned directly)")
        if tool_calls > 1:
            print(f"  (chained {tool_calls} tool calls)")

    write_log({
        "user": user_text,
        "session_key": key,
        "answer": answer,
        "tool_calls": tool_calls,
        "tool_activity": tool_activity,
        "decision": first_decision,
        "skipped_final": skipped,
        "latency": asdict(report),
    })

    # Memory: append new messages to this session's history + queue background thinking
    if _pipeline["with_memory"] and history is not None:
        if skipped:
            history.extend(iter_out["skipped_msgs"])
            overflow = len(history) - _MAX_HISTORY_MESSAGES
            if overflow > 0:
                del history[:overflow]
        else:
            _extend_history_from_result(history, result)
    runner = _pipeline["thinking_runner"]
    if runner is not None:
        runner.queue(user_text, run_id=os.environ.get("BENCH_RUN_ID"))


def run_for_voice(client: Any, user_text: str, session_key: str | None = None) -> dict[str, Any]:
    """Voice-loop entry point.

    Same agent and session history as run_command, but returns a structured
    result instead of printing. The caller (plugins/voice_loop.py or
    plugins/messaging_gateway.py) speaks the text through its own TTS
    pipeline — unless the agent already vocalized via a speak/speak_file
    tool call, in which case spoke_via_tool=True and the caller should
    skip its own TTS to avoid double-speaking.

    `session_key` selects the per-channel rolling history. The voice loop
    leaves it None → "voice"; messaging bridges pass channel-specific keys
    like "telegram:12345" so each chat keeps its own context.
    """
    key = session_key or "voice"
    history = _get_session_history(key) if _pipeline["with_memory"] else None
    agent = _get_agent(client)
    model: LlamaCppModel = agent.model  # type: ignore[assignment]
    model.reset_timings()

    lock = _pipeline["llm_lock"]
    started = time.perf_counter()
    try:
        if lock is not None:
            with lock:
                iter_out = asyncio.run(_run_via_iter(agent, user_text, history))
        else:
            iter_out = asyncio.run(_run_via_iter(agent, user_text, history))
    except Exception as exc:
        return {
            "text": "",
            "error": str(exc),
            "tool_activity": [],
            "spoke_via_tool": False,
            "elapsed_s": time.perf_counter() - started,
        }

    elapsed = time.perf_counter() - started
    skipped = iter_out["skipped"]
    first_decision = iter_out["first_decision"]
    result = iter_out.get("result")

    if skipped:
        text = iter_out["skipped_text"]
        tool_activity = (
            [_format_call_line(first_decision["tool"], first_decision.get("args") or {}, None)]
            if first_decision is not None else []
        )
    else:
        text = (result.output if hasattr(result, "output") else str(result)) or ""
        text = text.strip()
        tool_activity, walked = _walk_new_messages(result)
        first_decision = first_decision or walked
    spoke_via_tool = any("🔊" in line for line in tool_activity)

    write_log({
        "user": user_text,
        "session_key": key,
        "answer": text,
        "tool_calls": len(tool_activity),
        "tool_activity": tool_activity,
        "decision": first_decision,
        "skipped_final": skipped,
        "latency": {"total": elapsed, "voice": True},
    })

    if _pipeline["with_memory"] and history is not None:
        if skipped:
            history.extend(iter_out["skipped_msgs"])
            overflow = len(history) - _MAX_HISTORY_MESSAGES
            if overflow > 0:
                del history[:overflow]
        else:
            _extend_history_from_result(history, result)
    runner = _pipeline["thinking_runner"]
    if runner is not None:
        runner.queue(user_text, run_id=os.environ.get("BENCH_RUN_ID"))

    return {
        "text": text,
        "tool_activity": tool_activity,
        "spoke_via_tool": spoke_via_tool,
        "elapsed_s": elapsed,
        "skipped_final": skipped,
    }


def _extend_history_from_result(history: list[Any], result: Any) -> None:
    """After agent.run_sync, append new messages onto `history` so the next
    call (with the same session_key) carries the conversation forward.
    Capped at _MAX_HISTORY_MESSAGES."""
    try:
        new_msgs = result.new_messages()
    except Exception:
        try:
            new_msgs = result.all_messages()
        except Exception:
            return
    history.extend(new_msgs)
    overflow = len(history) - _MAX_HISTORY_MESSAGES
    if overflow > 0:
        del history[:overflow]


# ============================================================================
# Tool-activity surfacing for chat display + decision extraction
# ============================================================================
def _walk_new_messages(result: Any) -> tuple[list[str], dict[str, Any] | None]:
    """Single pass over `result.new_messages()` that produces both:
      - tool_activity: human-readable lines per tool call (for chat display)
      - first_decision: the first tool call this turn (for the decision log)

    Combines what used to be two separate iterations into one — small win,
    but both consumers run unconditionally on every turn so it's free.
    """
    out: list[str] = []
    first_decision: dict[str, Any] | None = None
    pending_calls: dict[str, dict[str, Any]] = {}
    try:
        msgs = list(result.new_messages()) if hasattr(result, "new_messages") else list(result.all_messages())
    except Exception:
        return out, None
    for msg in msgs:
        kind = getattr(msg, "kind", None)
        if kind == "response":
            for part in msg.parts:
                if getattr(part, "part_kind", None) == "tool-call":
                    pending_calls[part.tool_call_id] = {
                        "name": part.tool_name,
                        "args": part.args,
                    }
                    if first_decision is None:
                        first_decision = {"tool": part.tool_name, "args": part.args, "mode": "natural"}
        elif kind == "request":
            for part in msg.parts:
                if getattr(part, "part_kind", None) != "tool-return":
                    continue
                tc_id = getattr(part, "tool_call_id", None)
                call = pending_calls.pop(tc_id, None)
                name = (call or {}).get("name") or part.tool_name
                args = (call or {}).get("args") or {}
                out.append(_format_call_line(name, args, part.content))
    return out, first_decision


def _format_call_line(name: str, args: Any, tool_result: Any) -> str:
    result = tool_result if isinstance(tool_result, dict) else {}

    if name in ("speak", "speak_file") and result.get("spoken") is True:
        text = result.get("text") or ""
        secs = result.get("seconds", 0)
        chars = result.get("chars", 0)
        if text:
            return f"  🔊 {text}\n  (spoke {chars} chars in {secs}s)"
        return f"  🔊 (spoke {chars} chars in {secs}s)"

    if result.get("spoken") is False:
        return f"  🔊 (speak skipped: {result.get('reason', '?')})"

    if name == "remember" and result.get("remembered"):
        return f"  💾 remembered {result.get('key')!r} = {str(result.get('value', ''))[:60]!r}"

    if name == "forget":
        if result.get("forgotten"):
            return f"  🗑  forgot {result.get('key')!r}"
        return f"  ⚠  forget skipped: no key {result.get('key')!r}"

    if name == "recall":
        if result.get("found"):
            return f"  🔍 recall {result.get('key')!r} → {str(result.get('value', ''))[:80]!r}"
        return f"  🔍 recall {result.get('key')!r} → (not found)"

    if result.get("opened") is True:
        if result.get("url"):
            return f"  🌐 opened {result['url']}"
        if result.get("app"):
            return f"  📱 launched app: {result['app']}"
        if result.get("path"):
            return f"  📂 opened file: {result['path']}"

    args_repr = ""
    if isinstance(args, dict) and args:
        args_repr = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2])
        if len(args_repr) > 60:
            args_repr = args_repr[:57] + "..."
    return f"  ▸ {name}({args_repr})"


# ============================================================================
# Client shim — bench.py expects llm_client.LlamaCppPythonClient(...) with
# both .llm (for our Model) and .chat() (for ThinkingRunner compatibility).
# ============================================================================
@dataclass
class _ChatResult:
    """Mimics the LLMResult shape used by python_custom_json / python_hermes_xml."""
    text: str
    latency_s: float
    ttft_s: float = 0.0


class _LlamaClientShim:
    """Loads a Llama instance once and exposes:
      - `.llm` for LlamaCppModel
      - `.chat(messages, ...)` for ThinkingRunner (matches LlamaCppPythonClient API)
    """

    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL_PATH,
        ctx: int = 8192,
        gpu_layers: int = -1,
        batch: int = 512,
        ubatch: int = 512,
        flash_attn: bool = True,
        swa_full: bool = False,
        threads: int | None = None,
        warmup: bool = True,
    ) -> None:
        from llama_cpp import Llama

        path = model_path.expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        kwargs: dict[str, Any] = {
            "model_path": str(path),
            "n_ctx": ctx,
            "n_gpu_layers": gpu_layers,
            "n_batch": batch,
            "n_ubatch": ubatch,
            "flash_attn": flash_attn,
            "swa_full": swa_full,
            "verbose": False,
        }
        if threads is not None:
            kwargs["n_threads"] = threads

        print(f"[python_pydantic_ai] loading {path.name}...", flush=True)
        started = time.perf_counter()
        self.llm = Llama(**kwargs)
        print(f"[python_pydantic_ai] loaded in {time.perf_counter() - started:.1f}s.", flush=True)
        if warmup:
            self.llm.create_chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
                temperature=0.0,
            )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        top_p: float = 0.95,
        stream: bool = False,
        grammar: str | None = None,
    ) -> _ChatResult:
        """Minimal chat completion wrapper for ThinkingRunner.

        Ignores `stream` and `grammar`. Returns text + wall-clock latency.
        """
        started = time.perf_counter()
        completion = self.llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=False,
        )
        elapsed = time.perf_counter() - started
        text = completion["choices"][0]["message"].get("content") or ""
        return _ChatResult(text=text.strip(), latency_s=elapsed)

    def health_check(self) -> bool:
        return True


LlamaCppPythonClient = _LlamaClientShim


# ============================================================================
# Extension initialization
# ============================================================================
def init_extensions(args, client) -> None:
    """Wire up memory / MCP / thinking based on flags + env vars."""
    with_memory = getattr(args, "with_memory", False) or os.environ.get("BENCH_WITH_MEMORY") == "1"
    with_mcp = getattr(args, "with_mcp", False) or os.environ.get("BENCH_WITH_MCP") == "1"
    with_thinking = getattr(args, "think", False) or os.environ.get("BENCH_WITH_THINKING") == "1"

    _pipeline["with_memory"] = with_memory
    _pipeline["with_mcp"] = with_mcp
    _pipeline["with_thinking"] = with_thinking
    _pipeline["client"] = client

    # --- User-facing display config (memory/config.json) -----------------------
    try:
        from .memory import config as user_config

        cfg = user_config.load()
        display = cfg.get("display") or {}
        _pipeline["show_latency"] = bool(display.get("show_latency", False))
        _pipeline["show_tool_activity"] = bool(display.get("show_tool_activity", True))
        _pipeline["show_help_on_start"] = bool(display.get("show_help_on_start", True))
    except Exception as exc:
        print(f"[python_pydantic_ai] config load skipped: {exc}", file=sys.stderr, flush=True)

    # --- Memory: identity injection (per-session history is lazy-loaded) -----
    if with_memory:
        try:
            from .memory.memory_module import load_identity

            identity = load_identity()
            if identity:
                _pipeline["system_prompt"] = f"{identity}\n\n{prompts.SYSTEM_PROMPT}"
            print(
                "[python_pydantic_ai] memory on — identity injected; per-channel "
                "history loads lazily on first turn.",
                flush=True,
            )
        except Exception as exc:
            print(f"[python_pydantic_ai] --with-memory partial: {exc}", file=sys.stderr, flush=True)

    # --- MCP: load bridge + record specs (agent will be rebuilt by _get_agent) ---
    if with_mcp:
        try:
            from .plugins.mcp import client as mcp_client

            registry = mcp_client.init_from_config()
            specs = registry.list_tools()
            _pipeline["mcp_specs"] = specs
            if specs:
                print(
                    f"[python_pydantic_ai] MCP enabled with {len(specs)} extended tool(s).",
                    flush=True,
                )
        except Exception as exc:
            print(f"[python_pydantic_ai] --with-mcp failed: {exc}", file=sys.stderr, flush=True)

    # --- Thinking: background runner with shared LLM lock -----------------------
    if with_thinking:
        try:
            from .core.runners import thinking_runner

            lock = threading.Lock()
            _pipeline["llm_lock"] = lock
            # Per-framework log path: <framework>/logs/thinking.jsonl. Matches the
            # vocabulary contract (runners write into framework logs, not into
            # the plugins/ source tree).
            log_path = LOG_DIR / "thinking.jsonl"
            _pipeline["thinking_runner"] = thinking_runner.ThinkingRunner(
                client, "python_pydantic_ai", lock, _pipeline["system_prompt"],
                log_path=log_path,
            )
            print(f"[python_pydantic_ai] background thinking enabled — see {log_path}", flush=True)
        except Exception as exc:
            print(f"[python_pydantic_ai] --think failed: {exc}", file=sys.stderr, flush=True)


def init_from_env(client) -> None:
    """Called by bench.py to wire up extensions from env vars."""
    class _A:
        with_memory = False
        with_mcp = False
        think = False

    init_extensions(_A(), client)
    if os.environ.get("BENCH_NO_WARM_TTS") != "1":
        result = tools.warm_kokoro()
        if result.get("warmed"):
            print(f"[python_pydantic_ai] Kokoro warmed in {result.get('seconds')}s.", flush=True)
    _get_agent(client)


def shutdown_extensions(wait: bool = True) -> None:
    """Bench teardown — drain any background thinking jobs."""
    runner = _pipeline["thinking_runner"]
    if runner is not None:
        if runner.pending() > 0:
            print("[python_pydantic_ai] waiting for background thinking jobs...", flush=True)
        runner.shutdown(wait=wait)


def ensure_workspace() -> None:
    tools.ensure_workspace()


# ============================================================================
# CLI loops
# ============================================================================
HELP_BANNER = """\
Commands (type at the You: prompt):
  /help              show this help
  /latency [on|off]  toggle the per-turn latency breakdown
  /tools [on|off]    toggle the tool-activity lines under each reply
  /setup             re-run the first-time setup wizard
  /multi             enter multi-line mode (finish with a blank line)
  /quit              exit (also: exit, quit, Ctrl-D)

Tips:
  • Pasting multiple lines is auto-detected — paste freely, the whole
    block is sent as one turn.
  • The agent can call 28 tools (files, web, weather, memory, time, math,
    speak, image gen, vision, run_python, schedule, delegate, send_message
    on a messaging bridge). Just ask in plain English.
"""


def _print_help_banner() -> None:
    print(HELP_BANNER, end="", flush=True)


def _read_user_input(prompt_text: str = "You: ") -> str | None:
    """Read one user turn.

    Pasting multi-line text into a terminal that runs plain `input()` delivers
    one line per Enter, which breaks the prompt. We detect a paste by checking
    whether stdin has more data ready immediately after the first line — if so,
    we keep draining until stdin is quiet (~30 ms idle) and return the joined
    block as a single turn. A blank `/multi` mode is also offered for typed
    multi-line input where there's no actual paste burst to detect.
    """
    try:
        first = input(prompt_text)
    except (EOFError, KeyboardInterrupt):
        return None

    if first.strip() == "/multi":
        print("(multi-line mode — finish with a blank line)")
        lines: list[str] = []
        while True:
            try:
                line = input("... ")
            except (EOFError, KeyboardInterrupt):
                break
            if line == "":
                break
            lines.append(line)
        return "\n".join(lines).strip()

    # Paste-burst detection. Works only on Unix-y TTYs; on platforms where
    # select on stdin doesn't behave, we just return the first line.
    try:
        import select
        extra: list[str] = []
        while sys.stdin in select.select([sys.stdin], [], [], 0.03)[0]:
            line = sys.stdin.readline()
            if line == "":  # EOF
                break
            extra.append(line.rstrip("\n"))
        if extra:
            return "\n".join([first, *extra]).strip()
    except Exception:
        pass
    return first.strip()


def _handle_slash_command(cmd: str) -> bool:
    """Returns True if the loop should continue; False to exit."""
    parts = cmd.split()
    head = parts[0].lower()
    arg = parts[1].lower() if len(parts) > 1 else ""

    if head in {"/quit", "/exit"}:
        return False
    if head == "/help":
        _print_help_banner()
        return True
    if head == "/latency":
        if arg in {"on", "off"}:
            _pipeline["show_latency"] = (arg == "on")
        else:
            _pipeline["show_latency"] = not _pipeline.get("show_latency", False)
        print(f"  latency report → {'on' if _pipeline['show_latency'] else 'off'}")
        return True
    if head == "/tools":
        if arg in {"on", "off"}:
            _pipeline["show_tool_activity"] = (arg == "on")
        else:
            _pipeline["show_tool_activity"] = not _pipeline.get("show_tool_activity", True)
        print(f"  tool activity → {'on' if _pipeline['show_tool_activity'] else 'off'}")
        return True
    if head == "/setup":
        try:
            from .memory import config as user_config

            user_config.run_wizard(force=True)
            cfg = user_config.load()
            display = cfg.get("display") or {}
            _pipeline["show_latency"] = bool(display.get("show_latency", False))
            _pipeline["show_tool_activity"] = bool(display.get("show_tool_activity", True))
            print("  setup complete — restart the chat for identity changes to take effect.")
        except Exception as exc:
            print(f"  /setup failed: {exc}")
        return True
    print(f"  unknown command: {head} (try /help)")
    return True


def cli_loop(client, mode: str) -> int:
    ensure_workspace()
    print(f"[python_pydantic_ai] Workspace: {tools.WORKSPACE}")
    if _pipeline.get("show_help_on_start", True):
        _print_help_banner()
    else:
        print("Type /help for commands. /quit to stop.")
    while True:
        user_text = _read_user_input("You: ")
        if user_text is None:
            print()
            return 0
        if not user_text:
            continue
        if user_text.lower() in {"exit", "quit"}:
            return 0
        if user_text.startswith("/"):
            if not _handle_slash_command(user_text):
                return 0
            continue
        run_command(client, user_text, mode)


def self_test() -> int:
    """Run every safe tool against a canned input without loading the LLM."""
    ensure_workspace()

    checks = [
        ("get_time", lambda: tools.get_time()),
        ("get_time(timezone=Asia/Shanghai)", lambda: tools.get_time(timezone="Asia/Shanghai")),
        ("calculate", lambda: tools.calculate("(2 + 3) * 4")),
        ("create_file", lambda: tools.create_file("self_test/hello.txt", "hello")),
        ("append_file", lambda: tools.append_file("self_test/hello.txt", " world")),
        ("read_file", lambda: tools.read_file("self_test/hello.txt")),
        ("list_directory", lambda: tools.list_directory("self_test")),
        ("delete_file", lambda: tools.delete_file("self_test/hello.txt")),
        ("system_status", lambda: tools.system_status()),
        ("remember", lambda: tools.remember("self_test_key", "self_test_value")),
        ("recall (exact)", lambda: tools.recall("self_test_key")),
        ("recall (fuzzy)", lambda: tools.recall("self test")),
        ("list_facts", lambda: tools.list_facts()),
        ("forget", lambda: tools.forget("self_test_key")),
    ]
    for label, fn in checks:
        try:
            result = fn()
        except Exception as exc:
            print(f"== {label} == FAILED: {exc}")
            continue
        # Compact result preview
        as_str = json.dumps(result, ensure_ascii=True, default=str)
        if len(as_str) > 120:
            as_str = as_str[:117] + "..."
        print(f"== {label} == {as_str}")
    print("(speak/speak_file/web_search/get_weather/launch_url/open_file/open_app skipped — side-effects)")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pydantic AI agent against local llama-cpp-python.")
    parser.add_argument("prompt", nargs="*", help="Optional one-shot command.")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--ctx", type=int, default=8192)
    parser.add_argument("--gpu-layers", type=int, default=-1)
    parser.add_argument("--batch", type=int, default=512)
    parser.add_argument("--ubatch", type=int, default=512)
    parser.add_argument("--no-flash-attn", action="store_true")
    parser.add_argument("--swa-full", action="store_true")
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--no-warm-tts", action="store_true")
    parser.add_argument("--mode", choices=["auto", "fast", "natural"], default="auto")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--with-memory",
        action="store_true",
        help="Inject identity.md, maintain session history, append every turn to memory/episodic.jsonl.",
    )
    parser.add_argument(
        "--with-mcp",
        action="store_true",
        help="Connect to MCP servers from mcp_config.json and expose their tools.",
    )
    parser.add_argument(
        "--think",
        action="store_true",
        help="Run a background thinking call after each turn; logs to thinking.jsonl.",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help=("Launch the voice loop daemon instead of CLI chat. Flags after "
              "--voice are forwarded to voice_loop (--stt-mode, --barge-in, "
              "--no-aec, --require-wake-word, --no-chimes, --fast-model, "
              "--accurate-model). See `python -m python_pydantic_ai --voice --help`."),
    )
    return parser.parse_args()


def main() -> int:
    # If --voice is present, peel it off and delegate to the voice_loop
    # daemon. Voice_loop has its own argparse for STT mode, barge-in, AEC,
    # wake-word, chimes, model names — every flag the user types after
    # --voice flows through unchanged.
    if "--voice" in sys.argv[1:]:
        sys.argv.remove("--voice")
        from .plugins.voice_loop import main as voice_main
        return voice_main()
    args = parse_args()
    if args.self_test:
        return self_test()

    is_interactive = not " ".join(args.prompt).strip()
    if is_interactive and not args.with_memory:
        args.with_memory = True
        print("[python_pydantic_ai] interactive chat — memory auto-enabled (identity + session history).", flush=True)

    # First-time setup: if memory/config.json doesn't exist yet, run the
    # wizard for interactive sessions, fall back to defaults otherwise.
    try:
        from .memory import config as user_config

        user_config.ensure_configured(prompt_if_missing=is_interactive)
    except Exception as exc:
        print(f"[python_pydantic_ai] setup check skipped: {exc}", flush=True)

    client = _LlamaClientShim(
        model_path=args.model_path,
        ctx=args.ctx,
        gpu_layers=args.gpu_layers,
        batch=args.batch,
        ubatch=args.ubatch,
        flash_attn=not args.no_flash_attn,
        swa_full=args.swa_full,
        threads=args.threads,
        warmup=not args.no_warmup,
    )

    init_extensions(args, client)

    if not args.no_warm_tts:
        result = tools.warm_kokoro()
        if result.get("warmed"):
            print(f"[python_pydantic_ai] Kokoro warmed in {result.get('seconds')}s.", flush=True)

    _get_agent(client)

    prompt = " ".join(args.prompt).strip()
    try:
        if prompt:
            ensure_workspace()
            run_command(client, prompt, args.mode)
            return 0
        return cli_loop(client, args.mode)
    finally:
        runner = _pipeline["thinking_runner"]
        if runner is not None:
            if runner.pending() > 0:
                print("[python_pydantic_ai] waiting for background thinking jobs...", flush=True)
            runner.shutdown(wait=True)


if __name__ == "__main__":
    raise SystemExit(main())
