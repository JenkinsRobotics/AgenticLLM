#!/usr/bin/env python3
"""Jaeger CLI — self-improving local agent.

Lifecycle, in order:

  1. Resolve the instance dir (JAEGER_INSTANCE_DIR / ~/.jaeger/<name>/).
  2. Run the setup wizard if no valid instance is on disk.
  3. Take the exclusive lockfile (refuses to start if another copy holds it).
  4. Verify manifest.json's core_version matches; refuse-to-start if not.
  5. Bind tools + memory to the instance layout.
  6. Load the in-process Gemma model.
  7. Build the PydanticAI agent with the v2 system prompt + identity.
  8. Register built-in tools, then run the skill loader (base + instance
     skills, with smoke-test gating + instance-wins-over-core resolution).
  9. Enter the chat loop (slash commands + multiline paste detection).

This file is intentionally self-contained — no imports from `memory/`,
`messaging/`, or any other framework dir. Only third-party libraries and
sibling modules under `python_jaeger/`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import select
import sys
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, CallToolsNode, ModelRequestNode
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import RequestUsage

from . import credentials as creds
from . import log_rotation
from . import memory as mem
from . import prompts as prompt_module
from . import tools as jaeger_tools
from .cron_runner import CronRunner
from .instance import (
    CoreVersionMismatch,
    InstanceLayout,
    InstanceLock,
    check_manifest,
    default_instance_name,
    resolve_instance_dir,
    touch_manifest_started,
)
from .llm_model import LlamaCppModel
from .schemas import CORE_VERSION, Config
from .schemas import load_yaml
from .skill_loader import load_and_register
from .setup_wizard import run_wizard


# ---------------------------------------------------------------------------
# Tools whose dict result IS the answer (skip the final-LLM round-trip).
# ---------------------------------------------------------------------------
SKIP_FINAL_TOOLS = frozenset({
    "get_time", "calculate", "system_status",
    "list_facts", "recall", "remember", "forget",
    "file_write", "file_read", "list_skill_dir",
    "ask_user",
    "schedule_prompt", "cancel_schedule",
    "help_me",
    "list_credentials",
    "reload_skills",
})


def _format_tool_result_as_answer(name: str, result: Any) -> str:
    """Render a tool result dict into a one-line plain string."""
    if not isinstance(result, dict):
        return str(result)
    if name == "get_time":
        return result.get("datetime") or "Time unavailable."
    if name == "calculate":
        v = result.get("result")
        return str(v) if v is not None else "Calculation failed."
    if name == "system_status":
        disk = result.get("disk") or {}
        if disk:
            return (f"disk {disk.get('used_gb', 0):.1f}/{disk.get('total_gb', 0):.1f} GB "
                    f"({disk.get('free_gb', 0):.1f} GB free)")
        return "System status unavailable."
    if name == "list_facts":
        facts = result.get("facts") or {}
        if not facts:
            return "No facts saved yet."
        return "; ".join(f"{k}: {v}" for k, v in facts.items())
    if name == "recall":
        return str(result.get("value", "")) if result.get("found") else f"No value for {result.get('key')!r}."
    if name == "remember":
        return (f"Got it — remembered {result.get('key')!r}." if result.get("remembered")
                else "Couldn't save that.")
    if name == "forget":
        return (f"Forgot {result.get('key')!r}." if result.get("forgotten")
                else f"No saved value under {result.get('key')!r}.")
    if name == "file_write":
        if not result.get("written"):
            return f"Couldn't write: {result.get('error')}"
        commit = result.get("commit")
        suffix = f" [git {commit}]" if commit else ""
        return f"Wrote {result.get('path')} ({result.get('bytes')} bytes).{suffix}"
    if name == "file_read":
        return (result.get("content") or "")[:8000] if result.get("read") else f"Couldn't read: {result.get('error')}"
    if name == "list_skill_dir":
        if not result.get("listed"):
            return f"Couldn't list: {result.get('error')}"
        entries = result.get("entries") or []
        if not entries:
            return f"{result.get('path')}/ is empty."
        return "\n".join(f"  {e['type'][0]} {e['name']}" for e in entries)
    if name == "ask_user":
        return str(result.get("question") or "")
    if name == "schedule_prompt":
        return (f"Scheduled {result.get('name')!r} — next run at {result.get('next_run_at')!r}."
                if result.get("scheduled") else f"Couldn't schedule: {result.get('error')}")
    if name == "cancel_schedule":
        return (f"Cancelled {result.get('name')!r}." if result.get("cancelled")
                else f"No schedule {result.get('name')!r}.")
    if name == "help_me":
        return result.get("summary") or ""
    if name == "list_credentials":
        names = result.get("credentials") or []
        return ("Credentials: " + ", ".join(names)) if names else "No credentials stored yet."
    if name == "reload_skills":
        newly = result.get("newly_registered") or []
        skipped = result.get("skipped") or []
        bits = []
        if newly:
            bits.append("Registered: " + ", ".join(f"{s['name']}_v{s['version']}" for s in newly))
        else:
            bits.append("No new skills to register.")
        if skipped:
            bits.append("Skipped: " + ", ".join(
                f"{s['name']}_v{s['version']} ({s['reason'][:60]})" for s in skipped
            ))
        return " ".join(bits)
    return str(result)


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------
_DEFAULT_SESSION_KEY = "cli"
_MAX_HISTORY_MESSAGES = 20

_pipeline: dict[str, Any] = {
    "layout": None,
    "config": None,
    "system_prompt": "",
    "llm_lock": None,
    "show_latency": False,
    "show_tool_activity": True,
    "show_help_on_start": True,
}

_session_histories: dict[str, list[Any]] = {}
_session_loaded: set[str] = set()


@dataclass
class LatencyReport:
    total: float
    tool_calls: int
    decision: float
    decision_ttft: float
    tool: float
    final: float
    final_ttft: float


def print_latency(report: LatencyReport) -> None:
    print("Latency:")
    print(f"- decision: {report.decision:.3f}s  (ttft {report.decision_ttft:.3f}s)")
    print(f"- tool: {report.tool:.3f}s")
    print(f"- final: {report.final:.3f}s  (ttft {report.final_ttft:.3f}s)")
    print(f"- total: {report.total:.3f}s  (tool_calls: {report.tool_calls})")


def write_log(entry: dict[str, Any]) -> None:
    layout: InstanceLayout = _pipeline["layout"]
    layout.logs_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "framework": "python_jaeger",
        "core_version": CORE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **entry,
    }
    with layout.latency_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True, default=str) + "\n")
    _record_episodic(entry)


def _record_episodic(entry: dict[str, Any]) -> None:
    user = entry.get("user")
    if not user:
        return
    try:
        mem.append_episodic({
            "timestamp": entry.get("timestamp"),
            "framework": "python_jaeger",
            "session_key": entry.get("session_key"),
            "user": user,
            "decision_raw": json.dumps(entry.get("decision"), ensure_ascii=True, default=str)
                if entry.get("decision") is not None else None,
            "answer": entry.get("answer"),
        })
    except Exception as exc:
        print(f"[jaeger] episodic append failed: {exc}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Per-session conversation history
# ---------------------------------------------------------------------------
def _episodic_to_messages(turns: list[dict[str, str]]) -> list[Any]:
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


def _get_session_history(session_key: str) -> list[Any]:
    history = _session_histories.get(session_key)
    if history is None:
        history = []
        _session_histories[session_key] = history
    if session_key not in _session_loaded:
        _session_loaded.add(session_key)
        try:
            recent = mem.load_recent_turns(n=5, session_key=session_key)
            if recent:
                history.extend(_episodic_to_messages(recent))
                print(f"[jaeger] resumed {session_key!r}: {len(recent)//2} prior turn(s).", flush=True)
        except Exception as exc:
            print(f"[jaeger] resume for {session_key!r} skipped: {exc}", file=sys.stderr, flush=True)
    return history


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------
def _register_builtins(agent: Agent[None, str]) -> None:
    """Wire all the built-in Jaeger tools onto the agent.

    Skill-loader-managed skills come AFTER this — instance skills can
    override built-ins by registering a higher version of the same name.
    """
    t = jaeger_tools

    @agent.tool_plain
    def get_time(timezone: str | None = None) -> dict:
        """Current date/time (optional IANA timezone)."""
        return t.get_time(timezone=timezone)

    @agent.tool_plain
    def calculate(expression: str) -> dict:
        """Evaluate a safe arithmetic expression."""
        return t.calculate(expression=expression)

    @agent.tool_plain
    def system_status() -> dict:
        """Machine + instance dir status."""
        return t.system_status()

    @agent.tool_plain
    def file_write(path: str, content: str) -> dict:
        """Write a text file inside the instance's skills/ sandbox.
        Refuses absolute paths, .. escapes, and writes outside skills/."""
        return t.file_write(path=path, content=content)

    @agent.tool_plain
    def file_read(path: str) -> dict:
        """Read a text file from anywhere inside the instance dir except credentials/."""
        return t.file_read(path=path)

    @agent.tool_plain
    def list_skill_dir(path: str = ".") -> dict:
        """List the contents of skills/ (or a subdirectory under it)."""
        return t.list_skill_dir(path=path)

    @agent.tool_plain
    def remember(key: str, value: str) -> dict:
        """MANDATORY when the user states a preference, identity fact,
        plan, or anything they might recall later. Call this proactively
        — do not just acknowledge "OK, I'll remember" in text. Pick a
        descriptive snake_case key. Examples of inputs that require this
        tool: "remember that my favorite color is teal", "I drive a
        Mazda", "my name is Sam", "I'll be in Tokyo next week"."""
        return t.remember(key=key, value=value)

    @agent.tool_plain
    def recall(key: str) -> dict:
        """MANDATORY when the user asks about something they told you
        earlier ("what did I say my…", "do you remember…", "what's my
        favorite X"). Call BEFORE answering — the persisted store is the
        source of truth, short-term conversation context is not.
        Fuzzy match is supported, so close-but-not-exact keys still hit."""
        return t.recall(key=key)

    @agent.tool_plain
    def forget(key: str) -> dict:
        """Remove a stored fact. Call when the user says "forget that…"
        or asks to remove a stored preference."""
        return t.forget(key=key)

    @agent.tool_plain
    def list_facts() -> dict:
        """List every fact currently in memory. Call when the user asks
        an open-ended "what do you know about me?" or wants an audit of
        what's been remembered."""
        return t.list_facts()

    @agent.tool_plain
    def schedule_prompt(cron_expr: str, prompt: str, name: str | None = None) -> dict:
        """Schedule a prompt for unattended execution on a cron expression."""
        return t.schedule_prompt(cron_expr=cron_expr, prompt=prompt, name=name)

    @agent.tool_plain
    def list_schedules() -> dict:
        """List every active scheduled prompt."""
        return t.list_schedules()

    @agent.tool_plain
    def cancel_schedule(name: str) -> dict:
        """Cancel a previously-scheduled prompt by name."""
        return t.cancel_schedule(name=name)

    @agent.tool_plain
    def web_search(query: str, max_results: int = 5) -> dict:
        """DuckDuckGo web search (no API key)."""
        return t.web_search(query=query, max_results=max_results)

    @agent.tool_plain
    def get_weather(location: str) -> dict:
        """Look up current weather via wttr.in (no API key)."""
        return t.get_weather(location=location)

    @agent.tool_plain
    def run_python(code: str, timeout_s: float = 10.0) -> dict:
        """Execute Python in a sandboxed subprocess (10s default timeout)."""
        return t.run_python(code=code, timeout_s=timeout_s)

    @agent.tool_plain
    def ask_user(question: str) -> dict:
        """Ask the user a clarifying question instead of guessing."""
        return t.ask_user(question=question)

    @agent.tool_plain
    def help_me() -> dict:
        """Capability overview — call when asked 'what can you do?'."""
        return t.help_me()

    @agent.tool_plain
    def get_credential(name: str) -> dict:
        """Look up a secret (API key, token) by name from the instance's
        credentials/ store. NEVER read credential files directly — this is
        the only sanctioned access path. The returned value is for tool
        use only; do NOT echo it back to the user in your reply.
        """
        return creds.get_credential_tool_result(_pipeline["layout"], name=name)

    @agent.tool_plain
    def list_credentials() -> dict:
        """List the names of every credential currently stored. Values
        are never returned by this tool — use get_credential(name) for
        the actual value, and never echo the value in your reply."""
        return {"credentials": creds.list_credentials(_pipeline["layout"])}

    @agent.tool_plain
    def reload_skills() -> dict:
        """Re-scan core base_skills/ + instance skills/ and register any
        newly-authored or newly-versioned skills onto this agent.

        Call this after you've finished writing all the files for a new
        skill (SKILL.md + module + tests/smoke_test.py). The loader runs
        each skill's smoke test before activation; a failing test means
        the skill is NOT registered and you must fix the skill (not the
        test) before retrying. Returns the names of skills newly
        registered this call."""
        from .skill_loader import load_and_register, _REGISTERED_KEYS
        cfg = _pipeline["config"]
        before = {(n, v, z) for (n, v, z) in _REGISTERED_KEYS}
        report = load_and_register(
            agent,
            _pipeline["layout"],
            run_smoke_tests=cfg.skills.run_smoke_tests,
            enabled_allowlist=list(cfg.skills.enabled_base_skills) or None,
            audit=lambda ev, payload: jaeger_tools._audit(ev, payload),
        )
        after = set(_REGISTERED_KEYS)
        newly = sorted(after - before)
        return {
            "newly_registered": [
                {"name": n, "version": v, "zone": z} for (n, v, z) in newly
            ],
            "skipped": [
                {"name": s.name, "version": s.version, "zone": s.zone, "reason": reason[:200]}
                for (s, reason) in report.skipped
            ],
            "total_registered": len(after),
        }


def build_agent(client: Any, system_prompt: str) -> Agent[None, str]:
    model = LlamaCppModel(client.llm)
    agent: Agent[None, str] = Agent(model=model, system_prompt=system_prompt, tool_retries=2)
    _register_builtins(agent)
    return agent


# ---------------------------------------------------------------------------
# agent.iter() drive loop with skip-final intercept
# ---------------------------------------------------------------------------
async def _run_via_iter(agent: Agent, user_text: str, message_history: list[Any] | None) -> dict[str, Any]:
    first_decision: dict[str, Any] | None = None
    skip_final = False
    skip_tool_name: str | None = None
    skip_result: Any = None

    async with agent.iter(user_text, message_history=message_history or None) as run:
        async for node in run:
            if isinstance(node, CallToolsNode):
                tool_parts = [p for p in node.model_response.parts if hasattr(p, "tool_call_id")]
                if first_decision is None and tool_parts:
                    tc = tool_parts[0]
                    first_decision = {"tool": tc.tool_name, "args": tc.args}
                    if len(tool_parts) == 1 and tc.tool_name in SKIP_FINAL_TOOLS:
                        skip_final = True
                        skip_tool_name = tc.tool_name
            if skip_final and isinstance(node, ModelRequestNode):
                for p in node.request.parts:
                    if isinstance(p, ToolReturnPart):
                        skip_result = p.content
                        break
                if skip_result is not None:
                    break
        else:
            return {"result": run.result, "skipped": False, "first_decision": first_decision}

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
        "result": None, "skipped": True, "skipped_text": text,
        "skipped_msgs": skipped_msgs, "first_decision": first_decision,
    }


def _walk_new_messages(result: Any) -> tuple[list[str], dict[str, Any] | None]:
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
                    pending_calls[part.tool_call_id] = {"name": part.tool_name, "args": part.args}
                    if first_decision is None:
                        first_decision = {"tool": part.tool_name, "args": part.args}
        elif kind == "request":
            for part in msg.parts:
                if getattr(part, "part_kind", None) != "tool-return":
                    continue
                call = pending_calls.pop(getattr(part, "tool_call_id", None), None)
                name = (call or {}).get("name") or part.tool_name
                args = (call or {}).get("args") or {}
                args_repr = ""
                if isinstance(args, dict) and args:
                    args_repr = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2])
                    if len(args_repr) > 60:
                        args_repr = args_repr[:57] + "..."
                out.append(f"  ▸ {name}({args_repr})")
    return out, first_decision


# ---------------------------------------------------------------------------
# run_command — the chat-loop entry point
# ---------------------------------------------------------------------------
_agent_cache: dict[tuple, Agent[None, str]] = {}


def _agent_key(client: Any) -> tuple:
    return (id(client), hash(_pipeline["system_prompt"]))


def _get_agent(client: Any) -> Agent[None, str]:
    key = _agent_key(client)
    if key not in _agent_cache:
        _agent_cache.clear()
        agent = build_agent(client, _pipeline["system_prompt"])
        # Skill loader registers base + instance skills AFTER built-ins,
        # so an instance skill named `get_time_v2` would override the
        # built-in (intentional; honors the v2 override-via-versioning rule).
        load_and_register(
            agent,
            _pipeline["layout"],
            run_smoke_tests=_pipeline["config"].skills.run_smoke_tests,
            enabled_allowlist=list(_pipeline["config"].skills.enabled_base_skills) or None,
            audit=lambda ev, payload: jaeger_tools._audit(ev, payload),
        )
        _agent_cache[key] = agent
    return _agent_cache[key]


def run_command(client: Any, user_text: str, session_key: str | None = None) -> None:
    key = session_key or _DEFAULT_SESSION_KEY
    history = _get_session_history(key)
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
        print(f"Jaeger agent failed: {exc}")
        report = LatencyReport(elapsed, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
        if _pipeline.get("show_latency"):
            print_latency(report)
        write_log({"user": user_text, "session_key": key, "error": str(exc),
                   "latency": asdict(report)})
        return

    elapsed = time.perf_counter() - started
    skipped = iter_out["skipped"]
    first_decision = iter_out["first_decision"]
    result = iter_out.get("result")

    if skipped:
        answer = iter_out["skipped_text"]
        if first_decision is not None:
            args = first_decision.get("args") or {}
            args_repr = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2]) if isinstance(args, dict) else ""
            tool_activity = [f"  ▸ {first_decision['tool']}({args_repr})"]
        else:
            tool_activity = []
    else:
        answer = result.output if hasattr(result, "output") else str(result)
        tool_activity, walked = _walk_new_messages(result)
        first_decision = first_decision or walked

    llm_times = list(model.last_call_times)
    decision_total = sum(llm_times)
    decision_first = llm_times[0] if llm_times else 0.0
    final_last = llm_times[-1] if len(llm_times) >= 1 else 0.0
    report = LatencyReport(
        total=elapsed,
        tool_calls=len(tool_activity),
        decision=decision_total,
        decision_ttft=decision_first,
        tool=max(0.0, elapsed - decision_total),
        final=final_last if len(llm_times) > 1 else 0.0,
        final_ttft=final_last if len(llm_times) > 1 else 0.0,
    )

    if _pipeline.get("show_tool_activity", True):
        for line in tool_activity:
            print(line)
    if answer:
        print(answer)
    if _pipeline.get("show_latency"):
        print_latency(report)
        if skipped:
            print("  (final-LLM skipped — tool result returned directly)")

    write_log({
        "user": user_text,
        "session_key": key,
        "answer": answer,
        "tool_calls": len(tool_activity),
        "tool_activity": tool_activity,
        "decision": first_decision,
        "skipped_final": skipped,
        "latency": asdict(report),
    })

    if skipped:
        history.extend(iter_out["skipped_msgs"])
        overflow = len(history) - _MAX_HISTORY_MESSAGES
        if overflow > 0:
            del history[:overflow]
    else:
        try:
            new_msgs = result.new_messages() if hasattr(result, "new_messages") else result.all_messages()
        except Exception:
            new_msgs = []
        history.extend(new_msgs)
        overflow = len(history) - _MAX_HISTORY_MESSAGES
        if overflow > 0:
            del history[:overflow]


# ---------------------------------------------------------------------------
# Llama-cpp-python client shim
# ---------------------------------------------------------------------------
class LlamaCppPythonClient:
    """Loads a Llama instance once and exposes `.llm` for LlamaCppModel."""

    def __init__(self, model_cfg: Any, warmup: bool = True) -> None:
        from llama_cpp import Llama

        path = Path(model_cfg.model_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")
        kwargs: dict[str, Any] = {
            "model_path": str(path),
            "n_ctx": model_cfg.ctx,
            "n_gpu_layers": model_cfg.gpu_layers,
            "n_batch": model_cfg.n_batch,
            "n_ubatch": model_cfg.n_ubatch,
            "flash_attn": model_cfg.flash_attn,
            "verbose": False,
        }
        if model_cfg.threads is not None:
            kwargs["n_threads"] = model_cfg.threads
        print(f"[jaeger] loading {path.name}...", flush=True)
        started = time.perf_counter()
        self.llm = Llama(**kwargs)
        print(f"[jaeger] loaded in {time.perf_counter() - started:.1f}s.", flush=True)
        if warmup:
            self.llm.create_chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1, temperature=0.0,
            )


# ---------------------------------------------------------------------------
# CLI loop with slash commands + multi-line paste detection
# ---------------------------------------------------------------------------
HELP_BANNER = """\
Commands (type at the You: prompt):
  /help              show this help
  /latency [on|off]  toggle the per-turn latency breakdown
  /tools [on|off]    toggle the tool-activity lines under each reply
  /setup             re-run the setup wizard (backs up the current instance)
  /skills            list registered skills
  /multi             enter multi-line mode (finish with a blank line)
  /quit              exit (also: exit, quit, Ctrl-D)

Pasting multiple lines is auto-detected — paste freely, the whole block
is sent as one turn.
"""


def _print_help() -> None:
    print(HELP_BANNER, end="", flush=True)


def _read_user_input(prompt_text: str = "You: ") -> str | None:
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
    try:
        extra: list[str] = []
        while sys.stdin in select.select([sys.stdin], [], [], 0.03)[0]:
            line = sys.stdin.readline()
            if line == "":
                break
            extra.append(line.rstrip("\n"))
        if extra:
            return "\n".join([first, *extra]).strip()
    except Exception:
        pass
    return first.strip()


def _handle_slash(cmd: str, client: Any | None) -> bool:
    parts = cmd.split()
    head = parts[0].lower()
    arg = parts[1].lower() if len(parts) > 1 else ""
    if head in {"/quit", "/exit"}:
        return False
    if head == "/help":
        _print_help()
        return True
    if head == "/latency":
        _pipeline["show_latency"] = (arg == "on") if arg in {"on", "off"} else not _pipeline.get("show_latency")
        print(f"  latency report → {'on' if _pipeline['show_latency'] else 'off'}")
        return True
    if head == "/tools":
        _pipeline["show_tool_activity"] = (arg == "on") if arg in {"on", "off"} else not _pipeline.get("show_tool_activity")
        print(f"  tool activity → {'on' if _pipeline['show_tool_activity'] else 'off'}")
        return True
    if head == "/skills":
        from .skill_loader import discover_skills
        for s in discover_skills(_pipeline["layout"]):
            print(f"  {s.zone:8s}  {s.name}_v{s.version}  ({s.module_path})")
        return True
    if head == "/setup":
        try:
            new_layout = run_wizard(force=True, instance_name=_pipeline["config"].instance_name)
            print(f"  setup complete — restart Jaeger to pick up changes at {new_layout.root}.")
        except Exception as exc:
            print(f"  /setup failed: {exc}")
        return True
    print(f"  unknown command: {head} (try /help)")
    return True


def cli_loop(client: Any) -> int:
    layout: InstanceLayout = _pipeline["layout"]
    print(f"[jaeger] Instance: {layout.root}")
    if _pipeline.get("show_help_on_start", True):
        _print_help()
    else:
        print("Type /help for commands. /quit to stop.")
    while True:
        text = _read_user_input("You: ")
        if text is None:
            print()
            return 0
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            return 0
        if text.startswith("/"):
            if not _handle_slash(text, client):
                return 0
            continue
        run_command(client, text)


# ---------------------------------------------------------------------------
# Self-test (no LLM)
# ---------------------------------------------------------------------------
def self_test(layout: InstanceLayout) -> int:
    """Exercise the sandbox + memory + skill loader without touching the LLM."""
    jaeger_tools.bind(layout)
    print(f"[jaeger] self-test against {layout.root}")
    checks: list[tuple[str, Any]] = [
        ("get_time", lambda: jaeger_tools.get_time()),
        ("calculate", lambda: jaeger_tools.calculate("(2+3)*4")),
        ("system_status", lambda: jaeger_tools.system_status()),
        ("file_write (allowed)", lambda: jaeger_tools.file_write("self_test/hello.txt", "hello jaeger")),
        ("file_read (allowed)",  lambda: jaeger_tools.file_read("skills/self_test/hello.txt")),
        ("file_write (.. escape rejected)", lambda: jaeger_tools.file_write("../identity.yaml", "bad")),
        ("file_write (absolute path rejected)", lambda: jaeger_tools.file_write("/etc/passwd", "bad")),
        ("file_read (credentials rejected)", lambda: jaeger_tools.file_read("credentials/anything")),
        ("remember/recall", lambda: (jaeger_tools.remember("k", "v"), jaeger_tools.recall("k"))),
        ("list_facts", lambda: jaeger_tools.list_facts()),
        ("forget", lambda: jaeger_tools.forget("k")),
        ("list_skill_dir", lambda: jaeger_tools.list_skill_dir(".")),
    ]
    fail = 0
    for label, fn in checks:
        try:
            result = fn()
        except Exception as exc:
            print(f"== {label} == FAILED: {exc}")
            fail += 1
            continue
        as_str = json.dumps(result, ensure_ascii=True, default=str)
        if len(as_str) > 140:
            as_str = as_str[:137] + "..."
        print(f"== {label} == {as_str}")
    # Sandbox negative-checks should have returned a dict with written=False / read=False
    # — confirm we got the rejection shape, not a stack trace.
    try:
        bad = jaeger_tools.file_write("../identity.yaml", "X")
        assert bad.get("written") is False, "sandbox failed to reject .. escape"
        bad2 = jaeger_tools.file_write("/etc/passwd", "X")
        assert bad2.get("written") is False, "sandbox failed to reject absolute path"
        bad3 = jaeger_tools.file_read("credentials/anything")
        assert bad3.get("read") is False, "sandbox failed to reject credentials read"
        print("== sandbox enforcement == OK (.. + abs path + credentials all rejected)")
    except AssertionError as exc:
        print(f"== sandbox enforcement == FAILED: {exc}")
        fail += 1

    # Skill discovery
    try:
        from .skill_loader import discover_skills
        discovered = discover_skills(layout)
        names = [f"{s.name}_v{s.version}({s.zone})" for s in discovered]
        print(f"== skill discovery == {names or '(none yet — base_skills empty)'}")
    except Exception as exc:
        print(f"== skill discovery == FAILED: {exc}")
        fail += 1

    # Credentials: round-trip + perm enforcement
    try:
        creds.set_credential(layout, "self_test_token", "abc123")
        v = creds.get_credential(layout, "self_test_token")
        assert v == "abc123", f"value round-trip mismatch: {v!r}"
        path = layout.credentials_dir / "self_test_token"
        # Verify perms
        import stat as _stat
        mode = _stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

        # Loosen perms and confirm refusal
        os.chmod(path, 0o644)
        try:
            creds.get_credential(layout, "self_test_token")
            raise AssertionError("get_credential should have refused on 0o644")
        except creds.CredentialError:
            pass
        os.chmod(path, 0o600)

        # Invalid name rejection
        try:
            creds.set_credential(layout, "../etc/passwd", "X")
            raise AssertionError("invalid name should have been rejected")
        except creds.CredentialError:
            pass

        creds.delete_credential(layout, "self_test_token")
        print("== credentials == OK (round-trip, perm enforcement, name validation)")
    except Exception as exc:
        print(f"== credentials == FAILED: {exc}")
        fail += 1

    # Migrations discovery
    try:
        from .migrations import discover_migrations
        migs = discover_migrations()
        print(f"== migrations == {[m['name'] for m in migs] or '(none registered — at head)'}")
    except Exception as exc:
        print(f"== migrations == FAILED: {exc}")
        fail += 1

    return 0 if fail == 0 else 1


# ---------------------------------------------------------------------------
# Credential CLI handlers
# ---------------------------------------------------------------------------
def _cli_set_credential(layout: InstanceLayout, name: str) -> int:
    """Read the value from stdin so it never appears in shell history.

    If stdin is a TTY, prompt with getpass (the value is echoed-suppressed).
    Otherwise read a single line from stdin (allows `echo $TOK | jaeger
    --set-credential NAME` for scripted setups; the user accepts that
    risk by piping).
    """
    import getpass
    if sys.stdin.isatty():
        try:
            value = getpass.getpass(f"Value for credential {name!r} (input hidden): ")
        except KeyboardInterrupt:
            print()
            return 2
    else:
        value = sys.stdin.readline().rstrip("\n")
    if not value:
        print("[jaeger] empty value — refusing to store.", file=sys.stderr, flush=True)
        return 2
    try:
        path = creds.set_credential(layout, name, value)
    except creds.CredentialError as exc:
        print(f"[jaeger] {exc}", file=sys.stderr, flush=True)
        return 2
    print(f"[jaeger] stored credential {name!r} at {path} (mode 0600).")
    return 0


def _cli_list_credentials(layout: InstanceLayout) -> int:
    names = creds.list_credentials(layout)
    if not names:
        print("(no credentials stored yet)")
        return 0
    print("Credentials in", layout.credentials_dir)
    for n in names:
        print(f"  {n}")
    return 0


def _cli_delete_credential(layout: InstanceLayout, name: str) -> int:
    try:
        existed = creds.delete_credential(layout, name)
    except creds.CredentialError as exc:
        print(f"[jaeger] {exc}", file=sys.stderr, flush=True)
        return 2
    if existed:
        print(f"[jaeger] deleted credential {name!r}.")
        return 0
    print(f"[jaeger] no credential named {name!r} to delete.")
    return 1


def _cli_migrate(layout: InstanceLayout) -> int:
    from .migrations import run_pending_migrations

    try:
        applied = run_pending_migrations(layout)
    except Exception as exc:
        print(f"[jaeger] migration failed: {exc}", file=sys.stderr, flush=True)
        return 2
    if not applied:
        print("[jaeger] instance is already at the installed core version — nothing to migrate.")
    else:
        print(f"[jaeger] applied {len(applied)} migration(s):")
        for name in applied:
            print(f"  ✓ {name}")
    return 0


# ---------------------------------------------------------------------------
# CLI argparse + main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Jaeger: self-improving local agent.")
    p.add_argument("prompt", nargs="*", help="Optional one-shot command.")
    p.add_argument("--instance", type=str, default=None,
                   help="Instance name (default: JAEGER_INSTANCE_NAME or 'default').")
    p.add_argument("--setup", action="store_true",
                   help="Run (or re-run) the setup wizard, then exit.")
    p.add_argument("--self-test", action="store_true",
                   help="Run the sandbox/memory/skill smoke tests without loading the LLM.")
    p.add_argument("--no-warmup", action="store_true", help="Skip llama-cpp warmup.")
    p.add_argument("--no-cron", action="store_true", help="Don't start the cron runner.")
    p.add_argument("--set-credential", metavar="NAME",
                   help="Store a credential under this name (value read from stdin), then exit.")
    p.add_argument("--list-credentials", action="store_true",
                   help="List stored credential names (values never printed) and exit.")
    p.add_argument("--delete-credential", metavar="NAME",
                   help="Delete a stored credential by name and exit.")
    p.add_argument("--migrate", action="store_true",
                   help="Run any pending core migrations against this instance and exit.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    instance_name = args.instance or default_instance_name()
    root = resolve_instance_dir(instance_name)
    layout = InstanceLayout(root=root)

    if args.setup or not layout.exists():
        layout = run_wizard(force=args.setup, instance_name=instance_name)

    # Manifest gate. On version mismatch try the migration runner; only
    # refuse-to-start if migrations don't bring us to parity.
    try:
        manifest = check_manifest(layout)
    except CoreVersionMismatch:
        try:
            from .migrations import run_pending_migrations
            applied = run_pending_migrations(layout)
            if applied:
                print(f"[jaeger] applied {len(applied)} migration(s) to reach core {CORE_VERSION}: "
                      + ", ".join(applied), flush=True)
            manifest = check_manifest(layout)  # must pass now
        except Exception as exc:
            print(f"[jaeger] refuse-to-start: {exc}", file=sys.stderr, flush=True)
            return 2

    # Lock
    lock = InstanceLock(layout)
    try:
        lock.acquire()
    except RuntimeError as exc:
        print(f"[jaeger] {exc}", file=sys.stderr, flush=True)
        return 2

    try:
        # Bind tools/memory + record start time on the manifest
        jaeger_tools.bind(layout)
        touch_manifest_started(layout, manifest)

        # Credential management — these subcommands skip model load.
        if args.set_credential:
            return _cli_set_credential(layout, args.set_credential)
        if args.list_credentials:
            return _cli_list_credentials(layout)
        if args.delete_credential:
            return _cli_delete_credential(layout, args.delete_credential)
        if args.migrate:
            return _cli_migrate(layout)

        if args.self_test:
            return self_test(layout)

        config: Config = load_yaml(layout.config_path, Config)
        _pipeline["layout"] = layout
        _pipeline["config"] = config
        _pipeline["show_latency"] = config.display.show_latency
        _pipeline["show_tool_activity"] = config.display.show_tool_activity
        _pipeline["show_help_on_start"] = config.display.show_help_on_start
        _pipeline["system_prompt"] = prompt_module.build_system_prompt(layout)

        # Log rotation at startup — idempotent, never blocks the boot.
        try:
            rep = log_rotation.rotate_now(layout, config.retention)
            if rep["rotated"] or rep["pruned_by_age"] or rep["pruned_by_size"]:
                print(f"[jaeger] log rotation: rotated={rep['rotated']} "
                      f"pruned_age={rep['pruned_by_age']} "
                      f"pruned_size={rep['pruned_by_size']}", flush=True)
        except Exception as exc:
            print(f"[jaeger] log rotation skipped: {exc}", flush=True)

        client = LlamaCppPythonClient(config.model, warmup=not args.no_warmup)
        # Force agent build now so skills load before the first prompt.
        _get_agent(client)

        # Cron runner: same llm_lock the chat loop uses, so a scheduled
        # prompt firing mid-conversation serializes cleanly.
        llm_lock = threading.Lock()
        _pipeline["llm_lock"] = llm_lock
        cron_runner: CronRunner | None = None
        if not args.no_cron:
            def _cron_callback(prompt: str, session_key: str | None = None) -> None:
                run_command(client, prompt, session_key=session_key)

            def _daily_housekeeping() -> None:
                try:
                    rep = log_rotation.rotate_now(layout, config.retention)
                    if rep["rotated"] or rep["pruned_by_age"] or rep["pruned_by_size"]:
                        print(f"[jaeger-cron] housekeeping: {rep}", flush=True)
                except Exception as exc:
                    print(f"[jaeger-cron] housekeeping skipped: {exc}", flush=True)

            cron_runner = CronRunner(
                _cron_callback, llm_lock=llm_lock,
                housekeeping=_daily_housekeeping,
            )
            cron_runner.start()

        prompt = " ".join(args.prompt).strip()
        try:
            if prompt:
                run_command(client, prompt)
                return 0
            return cli_loop(client)
        finally:
            if cron_runner is not None:
                cron_runner.shutdown(wait=False)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
