#!/usr/bin/env python3
"""CLI loop for the Hermes Function-Calling framework.

Same model (Gemma 4 26B-A4B) and same tool implementations as Pygentic; the
differences are: (1) tools declared as JSON Schema inside <tools></tools> in
the system prompt, (2) the model emits <tool_call>{...}</tool_call> XML rather
than bare JSON, (3) tool results round-trip as <tool_response>{...}</tool_response>
in a follow-up user message, (4) no grammar constraint on decoding.
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

from . import prompts, tools
from .llm_client import DEFAULT_MODEL_PATH, LlamaCppPythonClient, LlamaCppServerClient
from .tool_router import ToolDecision, parse_decision, run_tool
from .tools import WORKSPACE, ensure_workspace


LOG_DIR = Path(__file__).resolve().parent / "logs"


def _build_base_system_prompt(
    extra_schemas: list[dict[str, Any]] | None = None,
    with_identity: bool = False,
) -> str:
    """Optionally prepend identity.md to the Hermes function-calling prompt."""
    base = prompts.system_prompt(extra_schemas)
    if not with_identity:
        return base
    try:
        from memory.memory_module import load_identity

        identity = load_identity()
    except Exception:
        identity = ""
    return f"{identity}\n\n{base}" if identity else base


# Pipeline state — mutated only at init time. Default values keep the fast
# path identical to pre-extension behavior.
_pipeline: dict[str, Any] = {
    "system_prompt": _build_base_system_prompt(with_identity=False),
    "llm_lock": None,
    "thinking_runner": None,
    "with_mcp": False,
    "with_thinking": False,
    "with_memory": False,
}

# Session-scoped message history. Populated only when --with-memory is set.
_session_history: list[dict[str, str]] = []
_MAX_HISTORY_MESSAGES = 20


@dataclass
class LatencyReport:
    decision: float
    decision_ttft: float
    tool: float
    final: float
    final_ttft: float
    total: float


def format_tool_result(result: dict[str, Any]) -> str:
    if "datetime" in result:
        return str(result["datetime"])
    if "content" in result:
        return str(result["content"])
    if "result" in result and "expression" in result:
        return f"{result['expression']} = {result['result']}"
    if result.get("spoken") is True:
        return f"(spoke {result.get('chars', 0)} chars in {result.get('seconds', 0)}s)"
    if result.get("remembered") is True:
        val = str(result.get("value", ""))
        if len(val) > 80:
            val = val[:77] + "..."
        return f"Saved: {result.get('key', '?')} = {val}"
    if result.get("forgotten") in (True, False) and "key" in result:
        if result["forgotten"]:
            return f"Forgot: {result['key']}"
        return f"(nothing to forget for key={result['key']!r})"
    if "found" in result and "key" in result and "value" in result:
        return str(result["value"]) if result["found"] else f"(no fact stored for {result['key']!r})"
    if "facts" in result and isinstance(result["facts"], dict):
        facts = result["facts"]
        if not facts:
            return "(no facts stored yet)"
        return "\n".join(f"- {k}: {v}" for k, v in sorted(facts.items()))
    return json.dumps(result, indent=2, ensure_ascii=True)


def print_latency(report: LatencyReport) -> None:
    print("Latency:")
    print(f"- decision: {report.decision:.3f}s  (ttft {report.decision_ttft:.3f}s)")
    print(f"- tool: {report.tool:.3f}s")
    print(f"- final: {report.final:.3f}s  (ttft {report.final_ttft:.3f}s)")
    print(f"- total: {report.total:.3f}s")


def write_log(entry: dict[str, Any]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / "latency.jsonl"
    entry = {
        "framework": "hermes",
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_id": os.environ.get("BENCH_RUN_ID"),
        **entry,
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")

    if _pipeline["with_memory"]:
        _record_turn(entry)


def _record_turn(entry: dict[str, Any]) -> None:
    """Append this turn to the cross-session episodic log + session history."""
    user = entry.get("user")
    decision_raw = entry.get("decision_raw")
    if not user or not decision_raw:
        return

    _session_history.append({"role": "user", "content": user})
    _session_history.append({"role": "assistant", "content": decision_raw})
    overflow = len(_session_history) - _MAX_HISTORY_MESSAGES
    if overflow > 0:
        del _session_history[:overflow]

    try:
        from memory.memory_module import append_episodic

        append_episodic({
            "timestamp": entry.get("timestamp"),
            "framework": "hermes",
            "user": user,
            "decision_raw": decision_raw,
            "answer": entry.get("answer") or entry.get("final"),
            "run_id": entry.get("run_id"),
        })
    except Exception as exc:
        print(f"[hermes] episodic append failed: {exc}", file=sys.stderr, flush=True)


def decide(client, user_text: str):
    # No grammar — Hermes idiom is unconstrained decoding. The system prompt
    # carries all tool schemas as JSON, so prefill is heavier than Pygentic.
    messages: list[dict[str, str]] = [{"role": "system", "content": _pipeline["system_prompt"]}]
    if _session_history:
        messages.extend(_session_history)
    messages.append({"role": "user", "content": user_text})
    return client.chat(
        messages,
        max_tokens=2048,
        temperature=0.0,
        top_p=0.8,
        stream=True,
    )


def finalize(
    client,
    user_text: str,
    raw_decision: str,
    decision: ToolDecision,
    tool_result: dict[str, Any],
):
    tool_response = json.dumps(
        {"name": decision.tool, "content": tool_result}, ensure_ascii=True
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": _pipeline["system_prompt"]}]
    if _session_history:
        messages.extend(_session_history)
    messages.extend([
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": raw_decision},
        {
            "role": "user",
            "content": f"<tool_response>\n{tool_response}\n</tool_response>\n\n{prompts.FINAL_INSTRUCTIONS}",
        },
    ])
    return client.chat(
        messages,
        max_tokens=512,
        temperature=0.0,
        top_p=0.8,
        stream=True,
    )


def run_command(client, user_text: str, default_mode: str) -> None:
    """Run one turn. When thinking is enabled, serializes against the LLM lock
    and queues a background thinking job after the main response."""
    lock = _pipeline["llm_lock"]
    if lock is not None:
        with lock:
            _run_main(client, user_text, default_mode)
    else:
        _run_main(client, user_text, default_mode)

    runner = _pipeline["thinking_runner"]
    if runner is not None:
        runner.queue(user_text, run_id=os.environ.get("BENCH_RUN_ID"))


def _decide_with_history(client, base_messages: list[dict[str, str]], extra_messages: list[dict[str, str]]):
    """Decide() variant that takes already-built messages so we can append
    prior steps' tool-call/tool-response pairs without rebuilding."""
    return client.chat(
        base_messages + extra_messages,
        max_tokens=2048,
        temperature=0.0,
        top_p=0.8,
        stream=True,
    )


def _run_main(client, user_text: str, default_mode: str) -> None:
    """Multi-step agent loop. Each step: decide -> tool -> append <tool_response>
    -> next step. Stops on {"final":"..."}-style answer, max_steps, or
    same-tool-twice loop detection.
    """
    total_started = time.perf_counter()
    max_steps = max(1, int(_pipeline.get("max_steps", 4) or 4))

    base_messages: list[dict[str, str]] = [{"role": "system", "content": _pipeline["system_prompt"]}]
    if _session_history:
        base_messages.extend(_session_history)
    base_messages.append({"role": "user", "content": user_text})

    extra: list[dict[str, str]] = []
    steps: list[dict[str, Any]] = []
    decision_total = 0.0
    decision_first_ttft = 0.0
    tool_total = 0.0
    first_decision_raw = ""
    first_decision_dict: dict[str, Any] | None = None
    first_parse_fallback: str | None = None
    final_answer: str | None = None
    final_latency = 0.0
    final_ttft = 0.0
    loop_seen: set[tuple[str, str]] = set()

    for step_idx in range(max_steps):
        try:
            decision_result = _decide_with_history(client, base_messages, extra)
        except Exception as exc:
            total = time.perf_counter() - total_started
            print(f"LLM request failed: {exc}")
            print_latency(LatencyReport(0.0, 0.0, 0.0, 0.0, 0.0, total))
            return

        decision_total += decision_result.latency_s
        if step_idx == 0:
            decision_first_ttft = decision_result.ttft_s
            first_decision_raw = decision_result.text

        try:
            decision = parse_decision(decision_result.text)
        except Exception as exc:
            total = time.perf_counter() - total_started
            print(f"Decision parse failed at step {step_idx+1}: {exc}")
            print(f"Raw model output: {decision_result.text}")
            print_latency(LatencyReport(decision_total, decision_first_ttft, tool_total, 0.0, 0.0, total))
            return

        if step_idx == 0:
            first_decision_dict = asdict(decision)
            first_parse_fallback = decision.parse_fallback

        if decision.final is not None:
            final_answer = decision.final
            break

        key = (decision.tool or "", json.dumps(decision.args, sort_keys=True, ensure_ascii=True))
        if key in loop_seen:
            final_answer = "(stopped: model repeated the same tool call — likely loop)"
            break
        loop_seen.add(key)

        tool_started = time.perf_counter()
        try:
            tool_result = run_tool(decision)
        except Exception as exc:
            tool_result = {"error": str(exc)}
        tool_latency = time.perf_counter() - tool_started
        tool_total += tool_latency

        steps.append({
            "step": step_idx + 1,
            "decision": asdict(decision),
            "tool_result": tool_result,
            "tool_latency": tool_latency,
        })

        # Append in Hermes format so the next iteration sees the call+response.
        tool_response = json.dumps({"name": decision.tool, "content": tool_result}, ensure_ascii=True)
        extra.append({"role": "assistant", "content": decision_result.text})
        extra.append({
            "role": "user",
            "content": f"<tool_response>\n{tool_response}\n</tool_response>",
        })

    if final_answer is None:
        if steps:
            last = steps[-1]
            mode_to_use = default_mode if default_mode != "auto" else last["decision"].get("mode", "natural")
            if mode_to_use == "fast":
                final_answer = format_tool_result(last["tool_result"])
            else:
                try:
                    decision_obj = ToolDecision(
                        tool=last["decision"]["tool"],
                        args=last["decision"]["args"],
                        mode=last["decision"]["mode"],
                        final=last["decision"]["final"],
                        parse_fallback=last["decision"].get("parse_fallback"),
                    )
                    final_result = finalize(client, user_text, "", decision_obj, last["tool_result"])
                    final_answer = final_result.text
                    final_latency = final_result.latency_s
                    final_ttft = final_result.ttft_s
                except Exception:
                    final_answer = format_tool_result(last["tool_result"])
        else:
            # No tool steps and no final — fall back to printing the raw output.
            final_answer = first_decision_raw.strip() or "(no decision produced)"

    # Surface silent format failures as before (only meaningful when zero steps ran).
    if not steps and first_decision_raw and any(t in first_decision_raw for t in ("tool_call", "call:")):
        first_parse_fallback = first_parse_fallback or "silent_format_fail"

    total = time.perf_counter() - total_started
    report = LatencyReport(
        decision=decision_total,
        decision_ttft=decision_first_ttft,
        tool=tool_total,
        final=final_latency,
        final_ttft=final_ttft,
        total=total,
    )
    print(final_answer)
    print_latency(report)
    if len(steps) > 1:
        print(f"  (chained {len(steps)} tool calls)")

    write_log(
        {
            "user": user_text,
            "decision_raw": first_decision_raw,
            "decision": first_decision_dict,
            "parse_fallback": first_parse_fallback,
            "steps": steps,
            "steps_taken": len(steps),
            "answer": final_answer,
            "mode": default_mode,
            "latency": asdict(report),
        }
    )


def cli_loop(client, mode: str) -> int:
    ensure_workspace()
    print(f"[hermes] Workspace: {WORKSPACE}")
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
    """Round-trip the parser through known-good Hermes-format strings."""
    ensure_workspace()
    checks = [
        ('<tool_call>\n{"name": "get_time", "arguments": {}}\n</tool_call>', "get_time"),
        ('<tool_call>{"name": "calculate", "arguments": {"expression": "(2+3)*4"}}</tool_call>', "calculate"),
        ("I think the answer is 42.", None),
    ]
    for raw, expected_tool in checks:
        decision = parse_decision(raw)
        if expected_tool is None:
            assert decision.final is not None, raw
            print(json.dumps({"raw": raw, "final": decision.final}, ensure_ascii=True))
        else:
            assert decision.tool == expected_tool, (decision.tool, expected_tool)
            result = run_tool(decision)
            print(json.dumps({"decision": asdict(decision), "result": result}, ensure_ascii=True))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hermes Function-Calling agent against local llama.cpp.")
    parser.add_argument("prompt", nargs="*", help="Optional one-shot command instead of interactive loop.")
    parser.add_argument("--backend", choices=["python", "server"], default="python")
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL_PATH)
    parser.add_argument("--ctx", type=int, default=8192)
    parser.add_argument("--gpu-layers", type=int, default=-1, help="-1 = all layers on GPU.")
    parser.add_argument("--batch", type=int, default=512)
    parser.add_argument("--ubatch", type=int, default=512)
    parser.add_argument("--no-flash-attn", action="store_true")
    parser.add_argument("--swa-full", action="store_true")
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--server", default="http://127.0.0.1:8080", help="llama.cpp server base URL.")
    parser.add_argument("--model", default="local", help="Model name sent to the OpenAI-compatible API.")
    parser.add_argument(
        "--mode",
        choices=["auto", "fast", "natural"],
        default="auto",
        help="How to return tool results.",
    )
    parser.add_argument("--no-health-check", action="store_true", help="Skip server health check.")
    parser.add_argument("--self-test", action="store_true", help="Test the Hermes parser without the LLM.")
    parser.add_argument(
        "--with-mcp",
        action="store_true",
        help="Opt-in: connect to MCP servers from mcp_config.json and expose their tools as mcp:server/tool.",
    )
    parser.add_argument(
        "--think",
        action="store_true",
        help="Opt-in: run a background thinking call after each turn; logs to thinking.jsonl.",
    )
    parser.add_argument(
        "--with-memory",
        action="store_true",
        help="Opt-in: inject identity.md, maintain session history, and append every turn to memory/episodic.jsonl.",
    )
    parser.add_argument(
        "--no-warm-tts",
        action="store_true",
        help="Skip Kokoro TTS warmup at startup. First speak/speak_file call will pay ~3-5s setup cost.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=4,
        help="Max chained tool calls per user turn (multi-step agent loop). 1 = single-step legacy behavior.",
    )
    return parser.parse_args()


def init_from_env(client) -> None:
    """Initialize extensions from BENCH_WITH_* env vars only.

    Used by bench.py, which imports run_command directly and bypasses argparse.
    Also warms Kokoro and sets a default max_steps so the bench gets the same
    pipeline as the interactive CLI by default.
    """
    class _A:
        with_mcp = False
        think = False
        with_memory = False

    init_extensions(_A(), client)
    _pipeline.setdefault("max_steps", 4)

    if os.environ.get("BENCH_NO_WARM_TTS") != "1":
        result = tools.warm_kokoro()
        if result.get("warmed"):
            print(f"[hermes] Kokoro warmed in {result.get('seconds')}s.", flush=True)


def shutdown_extensions(wait: bool = True) -> None:
    """Drain background thinking jobs. Called by bench.py at end of run."""
    runner = _pipeline["thinking_runner"]
    if runner is not None:
        runner.shutdown(wait=wait)


def init_extensions(args, client) -> None:
    """Mutate _pipeline once based on CLI flags + env vars."""
    with_mcp = args.with_mcp or os.environ.get("BENCH_WITH_MCP") == "1"
    with_thinking = args.think or os.environ.get("BENCH_WITH_THINKING") == "1"
    with_memory = args.with_memory or os.environ.get("BENCH_WITH_MEMORY") == "1"
    _pipeline["with_mcp"] = with_mcp
    _pipeline["with_thinking"] = with_thinking
    _pipeline["with_memory"] = with_memory

    if with_memory:
        _pipeline["system_prompt"] = _build_base_system_prompt(with_identity=True)
        try:
            from memory.memory_module import load_recent_turns

            recent = load_recent_turns(n=5)
            if recent:
                _session_history.extend(recent)
                print(
                    f"[hermes] memory on — identity injected, loaded {len(recent)//2} recent turn(s).",
                    flush=True,
                )
            else:
                print("[hermes] memory on — identity injected; no prior episodic turns.", flush=True)
        except Exception as exc:
            print(f"[hermes] --with-memory partial: {exc}", file=sys.stderr, flush=True)

    if with_mcp:
        try:
            import mcp_bridge

            registry = mcp_bridge.init_from_config()
            specs = registry.list_tools()
            if specs:
                extra_schemas = [
                    {
                        "name": s.qualified_name,
                        "description": s.description,
                        "parameters": s.input_schema or {"type": "object", "properties": {}},
                    }
                    for s in specs
                ]
                # Rebuild via the helper so identity stays prepended.
                _pipeline["system_prompt"] = _build_base_system_prompt(extra_schemas)
                print(f"[hermes] MCP enabled with {len(specs)} extended tool(s).", flush=True)
        except Exception as exc:
            print(f"[hermes] --with-mcp failed: {exc}", file=sys.stderr, flush=True)

    if with_thinking:
        try:
            import thinking_runner

            lock = threading.Lock()
            _pipeline["llm_lock"] = lock
            _pipeline["thinking_runner"] = thinking_runner.ThinkingRunner(
                client, "hermes", lock, _pipeline["system_prompt"]
            )
            print("[hermes] background thinking enabled — see thinking.jsonl.", flush=True)
        except Exception as exc:
            print(f"[hermes] --think failed: {exc}", file=sys.stderr, flush=True)


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()

    if args.backend == "server":
        client = LlamaCppServerClient(base_url=args.server, model=args.model)
        if not args.no_health_check and not client.health_check():
            print(f"llama.cpp server is not reachable at {args.server}")
            return 2
    else:
        try:
            client = LlamaCppPythonClient(
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
        except Exception as exc:
            print(f"Failed to load local llama.cpp model: {exc}")
            return 2

    init_extensions(args, client)

    if not args.no_warm_tts:
        result = tools.warm_kokoro()
        if result.get("warmed"):
            print(f"[hermes] Kokoro warmed in {result.get('seconds')}s.", flush=True)
        else:
            print(f"[hermes] Kokoro warmup skipped: {result.get('reason')}", file=sys.stderr, flush=True)

    _pipeline["max_steps"] = max(1, int(getattr(args, "max_steps", 4) or 4))

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
                print("[hermes] waiting for background thinking jobs...", flush=True)
            runner.shutdown(wait=True)


if __name__ == "__main__":
    raise SystemExit(main())
