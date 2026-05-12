#!/usr/bin/env python3
"""CLI loop for measuring agentic tool latency against llama.cpp server."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import prompts
from .llm_client import DEFAULT_MODEL_PATH, LlamaCppPythonClient, LlamaCppServerClient
from .tool_router import DECISION_GRAMMAR, ToolDecision, parse_decision, run_tool
from .tools import WORKSPACE, ensure_workspace


LOG_DIR = Path(__file__).resolve().parent / "logs"


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
    entry = {"framework": "pygentic", **entry}
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def decide(client, user_text: str):
    # Grammar stops at end-of-JSON, so this ceiling only matters for tool
    # calls with long string args (e.g. create_file with multi-paragraph
    # content). Short routing decisions still finish in ~30-50 tokens.
    return client.chat(
        [
            {"role": "system", "content": prompts.DECISION_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        max_tokens=2048,
        temperature=0.0,
        top_p=0.8,
        stream=True,
        grammar=DECISION_GRAMMAR,
    )


def finalize(client, user_text: str, decision: ToolDecision, tool_result: dict[str, Any]):
    return client.chat(
        [
            {"role": "system", "content": prompts.FINAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
            {
                "role": "assistant",
                "content": json.dumps({"tool": decision.tool, "args": decision.args}, ensure_ascii=True),
            },
            {"role": "user", "content": "Tool result: " + json.dumps(tool_result, ensure_ascii=True)},
        ],
        max_tokens=256,
        temperature=0.0,
        top_p=0.8,
        stream=True,
    )


def run_command(client, user_text: str, default_mode: str) -> None:
    total_started = time.perf_counter()
    try:
        decision_result = decide(client, user_text)
    except Exception as exc:
        total = time.perf_counter() - total_started
        print(f"LLM request failed: {exc}")
        print_latency(LatencyReport(0.0, 0.0, 0.0, 0.0, 0.0, total))
        return

    try:
        decision = parse_decision(decision_result.text)
    except Exception as exc:
        total = time.perf_counter() - total_started
        print(f"Decision parse failed: {exc}")
        print(f"Raw model output: {decision_result.text}")
        print_latency(
            LatencyReport(decision_result.latency_s, decision_result.ttft_s, 0.0, 0.0, 0.0, total)
        )
        return

    if decision.final is not None:
        total = time.perf_counter() - total_started
        print(decision.final)
        report = LatencyReport(
            decision_result.latency_s, decision_result.ttft_s, 0.0, 0.0, 0.0, total
        )
        print_latency(report)
        write_log(
            {
                "user": user_text,
                "decision_raw": decision_result.text,
                "final": decision.final,
                "latency": asdict(report),
            }
        )
        return

    tool_started = time.perf_counter()
    try:
        tool_result = run_tool(decision)
    except Exception as exc:
        tool_result = {"error": str(exc)}
    tool_latency = time.perf_counter() - tool_started

    mode = default_mode if default_mode != "auto" else decision.mode
    final_latency = 0.0
    final_ttft = 0.0
    if mode == "fast":
        answer = format_tool_result(tool_result)
    else:
        try:
            final_result = finalize(client, user_text, decision, tool_result)
        except Exception as exc:
            total = time.perf_counter() - total_started
            print(f"Final LLM request failed: {exc}")
            print("Tool result:")
            print(format_tool_result(tool_result))
            print_latency(
                LatencyReport(
                    decision_result.latency_s,
                    decision_result.ttft_s,
                    tool_latency,
                    0.0,
                    0.0,
                    total,
                )
            )
            return
        answer = final_result.text
        final_latency = final_result.latency_s
        final_ttft = final_result.ttft_s

    total = time.perf_counter() - total_started
    report = LatencyReport(
        decision=decision_result.latency_s,
        decision_ttft=decision_result.ttft_s,
        tool=tool_latency,
        final=final_latency,
        final_ttft=final_ttft,
        total=total,
    )
    print(answer)
    print_latency(report)
    write_log(
        {
            "user": user_text,
            "decision_raw": decision_result.text,
            "decision": asdict(decision),
            "tool_result": tool_result,
            "answer": answer,
            "mode": mode,
            "latency": asdict(report),
        }
    )


def cli_loop(client, mode: str) -> int:
    ensure_workspace()
    print(f"[pygentic] Workspace: {WORKSPACE}")
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
    ensure_workspace()
    checks = [
        '{"tool":"get_time","args":{}}',
        '{"tool":"create_file","args":{"path":"self_test/hello.txt","content":"hello"}}',
        '{"tool":"append_file","args":{"path":"self_test/hello.txt","content":" world"}}',
        '{"tool":"read_file","args":{"path":"self_test/hello.txt"}}',
        '{"tool":"list_directory","args":{"path":"self_test"}}',
        '{"tool":"calculate","args":{"expression":"(2 + 3) * 4"}}',
        '{"tool":"delete_file","args":{"path":"self_test/hello.txt"}}',
        '{"tool":"system_status","args":{}}',
    ]
    for raw in checks:
        decision = parse_decision(raw)
        result = run_tool(decision)
        print(json.dumps({"decision": asdict(decision), "result": result}, ensure_ascii=True))
    # speak() is excluded from self-test so we don't spam audio.
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Headless agent test against local llama.cpp.")
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
    parser.add_argument("--self-test", action="store_true", help="Test safe tools without the LLM server.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()

    if args.backend == "server":
        client = LlamaCppServerClient(base_url=args.server, model=args.model)
        if not args.no_health_check and not client.health_check():
            print(f"llama.cpp server is not reachable at {args.server}")
            print("Start llama-server first, then rerun this CLI.")
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

    prompt = " ".join(args.prompt).strip()
    if prompt:
        ensure_workspace()
        run_command(client, prompt, args.mode)
        return 0
    return cli_loop(client, args.mode)


if __name__ == "__main__":
    raise SystemExit(main())
