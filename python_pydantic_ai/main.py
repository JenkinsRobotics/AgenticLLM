#!/usr/bin/env python3
"""CLI loop for the Pydantic AI framework wrapper.

Reuses the same in-process llama-cpp-python `Llama` instance our other
frameworks load. The agent loop, tool calling, message conversion, retry
logic — all of that is handled by pydantic-ai itself. We provide:
  - LlamaCppModel: in-process adapter for the local Gemma model
  - The 19 in-process tools + optional MCP fetch tool
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
import json
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from . import prompts, tools
from .llm_model import LlamaCppModel


LOG_DIR = Path(__file__).resolve().parent / "logs"
DEFAULT_MODEL_PATH = Path(
    "/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/"
    "gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf"
)


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
}

# Conversation history maintained across run_command calls (only populated
# when --with-memory is on). Each element is a pydantic-ai ModelMessage.
_session_history: list[Any] = []
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
        from memory.memory_module import append_episodic

        append_episodic({
            "timestamp": entry.get("timestamp"),
            "framework": "python_pydantic_ai",
            "user": user,
            "decision_raw": json.dumps(entry.get("decision"), ensure_ascii=True, default=str)
                if entry.get("decision") is not None
                else None,
            "answer": entry.get("answer"),
            "run_id": entry.get("run_id"),
        })
    except Exception as exc:
        print(f"[python_pydantic_ai] episodic append failed: {exc}", file=sys.stderr, flush=True)


# ============================================================================
# Agent construction
# ============================================================================
def build_agent(
    client: Any,
    system_prompt: str,
    mcp_specs: list[Any] | None = None,
) -> Agent[None, str]:
    """Build a Pydantic AI Agent backed by our in-process llama-cpp-python model.

    Registers the 19 base tools. If mcp_specs is provided, also registers an
    MCP fetch tool wrapper (currently only mcp:web/fetch is supported — the
    schema is hardcoded since pydantic-ai needs typed signatures).
    """
    model = LlamaCppModel(client.llm)
    agent: Agent[None, str] = Agent(
        model=model,
        system_prompt=system_prompt,
        tool_retries=2,
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
    def delete_file(path: str) -> dict:
        """Delete a file from the workspace."""
        return tools.delete_file(path=path)

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
    def calculate(expression: str) -> dict:
        """Evaluate a safe arithmetic expression (+ - * / ** % //)."""
        return tools.calculate(expression=expression)

    @agent.tool_plain
    def speak(text: str) -> dict:
        """Speak text aloud through the speakers via Kokoro TTS. Supports SSML pauses."""
        return tools.speak(text=text)

    @agent.tool_plain
    def speak_file(path: str) -> dict:
        """Read a workspace file and narrate its contents aloud."""
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
        """Store a fact in unified memory shared across all agent processes."""
        return tools.remember(key=key, value=value)

    @agent.tool_plain
    def recall(key: str) -> dict:
        """Fetch a previously saved fact by key (or by partial / word-overlap match)."""
        return tools.recall(key=key)

    @agent.tool_plain
    def forget(key: str) -> dict:
        """Remove a stored fact by key."""
        return tools.forget(key=key)

    @agent.tool_plain
    def list_facts() -> dict:
        """List every fact currently in unified memory."""
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

    # MCP tools — currently only mcp:web/fetch is wired (its schema is the
    # only one we hardcode for type-safe pydantic-ai integration).
    if mcp_specs and any(s.qualified_name == "mcp:web/fetch" for s in mcp_specs):
        @agent.tool_plain
        def fetch_url(url: str, max_length: int = 5000) -> dict:
            """Fetch a URL through the MCP web/fetch server. Returns markdown content."""
            import mcp_bridge

            return mcp_bridge.call_mcp_tool("mcp:web/fetch", {"url": url, "max_length": max_length})

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


# ============================================================================
# run_command — main agent invocation, with latency split + history mgmt
# ============================================================================
def run_command(client: Any, user_text: str, default_mode: str) -> None:
    """Compatible with bench.py's expected (client, user_text, mode) signature.

    `default_mode` is accepted for API parity but ignored — pydantic-ai
    decides the loop dynamics on its own.
    """
    agent = _get_agent(client)
    model: LlamaCppModel = agent.model  # type: ignore[assignment]
    model.reset_timings()

    lock = _pipeline["llm_lock"]
    started = time.perf_counter()
    try:
        if lock is not None:
            with lock:
                result = agent.run_sync(user_text, message_history=_session_history or None)
        else:
            result = agent.run_sync(user_text, message_history=_session_history or None)
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
            "error": str(exc),
            "latency": asdict(report),
        })
        return

    elapsed = time.perf_counter() - started
    answer = result.output if hasattr(result, "output") else str(result)
    tool_activity = _summarize_tool_activity(result)
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

    for line in tool_activity:
        print(line)
    if answer:
        print(answer)
    print_latency(report)
    if tool_calls > 1:
        print(f"  (chained {tool_calls} tool calls)")

    write_log({
        "user": user_text,
        "answer": answer,
        "tool_calls": tool_calls,
        "tool_activity": tool_activity,
        "decision": _extract_first_decision(result),
        "latency": asdict(report),
    })

    # Memory: append new messages to session history + queue background thinking
    if _pipeline["with_memory"]:
        _extend_session_history_from_result(result)
    runner = _pipeline["thinking_runner"]
    if runner is not None:
        runner.queue(user_text, run_id=os.environ.get("BENCH_RUN_ID"))


def _extend_session_history_from_result(result: Any) -> None:
    """After agent.run_sync, append new messages to _session_history so the
    next call carries the conversation forward. Capped at _MAX_HISTORY_MESSAGES."""
    global _session_history
    try:
        new_msgs = result.new_messages()
    except Exception:
        try:
            new_msgs = result.all_messages()
        except Exception:
            return
    _session_history.extend(new_msgs)
    overflow = len(_session_history) - _MAX_HISTORY_MESSAGES
    if overflow > 0:
        del _session_history[:overflow]


# ============================================================================
# Tool-activity surfacing for chat display
# ============================================================================
def _summarize_tool_activity(result: Any) -> list[str]:
    """Walk the agent's message history and produce one human-readable line
    per tool call. Specially handles speak / speak_file so the spoken text
    is echoed to chat (otherwise the user can't see what was said)."""
    out: list[str] = []
    pending_calls: dict[str, dict[str, Any]] = {}
    try:
        msgs = list(result.new_messages()) if hasattr(result, "new_messages") else list(result.all_messages())
    except Exception:
        msgs = []
    for msg in msgs:
        kind = getattr(msg, "kind", None)
        if kind == "response":
            for part in msg.parts:
                if getattr(part, "part_kind", None) == "tool-call":
                    pending_calls[part.tool_call_id] = {
                        "name": part.tool_name,
                        "args": part.args,
                    }
        elif kind == "request":
            for part in msg.parts:
                if getattr(part, "part_kind", None) != "tool-return":
                    continue
                tc_id = getattr(part, "tool_call_id", None)
                call = pending_calls.pop(tc_id, None)
                name = (call or {}).get("name") or part.tool_name
                args = (call or {}).get("args") or {}
                out.append(_format_call_line(name, args, part.content))
    return out


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


def _extract_first_decision(result: Any) -> dict[str, Any] | None:
    """First tool call from the CURRENT turn only. We must not walk
    `all_messages()` here — that includes prior-turn history loaded via
    memory, which would mis-attribute every turn's decision to turn 1."""
    try:
        msgs = result.new_messages() if hasattr(result, "new_messages") else result.all_messages()
        for msg in msgs:
            if getattr(msg, "kind", None) != "response":
                continue
            for part in msg.parts:
                if getattr(part, "part_kind", None) == "tool-call":
                    return {"tool": part.tool_name, "args": part.args, "mode": "natural"}
    except Exception:
        pass
    return None


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

    # --- Memory: identity injection + episodic history ---------------------------
    if with_memory:
        try:
            from memory.memory_module import load_identity, load_recent_turns

            identity = load_identity()
            if identity:
                _pipeline["system_prompt"] = f"{identity}\n\n{prompts.SYSTEM_PROMPT}"
            recent_dicts = load_recent_turns(n=5)
            if recent_dicts:
                _session_history.extend(_episodic_to_messages(recent_dicts))
                print(
                    f"[python_pydantic_ai] memory on — identity injected, loaded {len(recent_dicts)//2} recent turn(s).",
                    flush=True,
                )
            else:
                print("[python_pydantic_ai] memory on — identity injected; no prior episodic turns.", flush=True)
        except Exception as exc:
            print(f"[python_pydantic_ai] --with-memory partial: {exc}", file=sys.stderr, flush=True)

    # --- MCP: load bridge + record specs (agent will be rebuilt by _get_agent) ---
    if with_mcp:
        try:
            import mcp_bridge

            registry = mcp_bridge.init_from_config()
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
            import thinking_runner

            lock = threading.Lock()
            _pipeline["llm_lock"] = lock
            _pipeline["thinking_runner"] = thinking_runner.ThinkingRunner(
                client, "python_pydantic_ai", lock, _pipeline["system_prompt"]
            )
            print("[python_pydantic_ai] background thinking enabled — see thinking.jsonl.", flush=True)
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
def cli_loop(client, mode: str) -> int:
    ensure_workspace()
    print(f"[python_pydantic_ai] Workspace: {tools.WORKSPACE}")
    print("Type 'exit' or 'quit' to stop.")
    while True:
        try:
            user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not user_text:
            continue
        if user_text.lower() in {"exit", "quit"}:
            return 0
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()

    is_interactive = not " ".join(args.prompt).strip()
    if is_interactive and not args.with_memory:
        args.with_memory = True
        print("[python_pydantic_ai] interactive chat — memory auto-enabled (identity + session history).", flush=True)

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
