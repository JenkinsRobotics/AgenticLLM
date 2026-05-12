#!/usr/bin/env python3
"""Head-to-head benchmark: Pygentic vs Hermes on the same prompt set.

Loads each framework's model ONCE and runs the full prompt list against it,
then writes a side-by-side comparison table. Each framework's per-prompt
latency entries also land in its own logs/latency.jsonl (tagged with the
framework name + a run_id), and an aggregate appends to bench_history.jsonl
at the project root so historical runs are easy to compare.

Run:
  python bench.py                       # both frameworks, default prompts
  python bench.py --only pygentic       # just one
  python bench.py --prompts file.txt    # custom prompt list (one per line)
  python bench.py --skip-run            # re-summarize existing logs
  python bench.py --history             # show recent runs per prompt
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
HISTORY_PATH = ROOT / "bench_history.jsonl"


DEFAULT_PROMPTS: list[str] = [
    # General tool routing
    "what time is it",
    "calculate 47 times 23 plus 12",
    "list the workspace",
    "make a file called bench.txt with the message hello from the benchmark",
    "read bench.txt out loud",
    "search the web for recent news about local llms",
    "tell me a one sentence story about a robot",
    "delete bench.txt",
    "what is the cpu and disk status of this machine",

    # YouTube robot-content workflow
    "search the web for trending youtube topics about home robots",
    "write a 4 sentence youtube intro script about a robot named Lilith discovering coffee and save it to youtube_intro.txt",
    "append a closing line to youtube_intro.txt asking viewers to subscribe",
    "narrate youtube_intro.txt out loud as if you are reading it for a youtube video",
    "come up with a catchy youtube title for a video about a robot vacuum gone rogue",
    "delete youtube_intro.txt",
]


# Prompts that exercise MCP-only capability. Added to the regular set when
# --with-mcp is passed. They should fail (or fall back to web_search) without MCP.
MCP_PROMPTS: list[str] = [
    "use the mcp:web/fetch tool to retrieve https://example.com and tell me what it says",
    "fetch the homepage of https://news.ycombinator.com using mcp:web/fetch and list the first three story titles",
]


def run_framework(name: str, prompts: list[str]) -> list[dict[str, Any]]:
    """Import the framework's agent, load its model once, run all prompts.

    Honors BENCH_WITH_MCP / BENCH_WITH_THINKING env vars by calling each
    framework's init_from_env() after the model is loaded.
    """
    if name == "pygentic":
        from pygentic.llm_client import LlamaCppPythonClient
        from pygentic.main import init_from_env, run_command, shutdown_extensions
        from pygentic.tools import ensure_workspace
    elif name == "hermes":
        from hermes.llm_client import LlamaCppPythonClient
        from hermes.main import init_from_env, run_command, shutdown_extensions
        from hermes.tools import ensure_workspace
    else:
        raise ValueError(f"unknown framework: {name}")

    print(f"\n=== {name}: loading model ===", flush=True)
    client = LlamaCppPythonClient()
    ensure_workspace()
    init_from_env(client)

    results: list[dict[str, Any]] = []
    try:
        for prompt in prompts:
            print(f"\n--- {name} :: {prompt!r}", flush=True)
            captured = io.StringIO()
            started = time.perf_counter()
            with redirect_stdout(captured):
                run_command(client, prompt, "auto")
            elapsed = time.perf_counter() - started
            output = captured.getvalue()
            print(output.rstrip(), flush=True)
            results.append({"prompt": prompt, "elapsed_s": elapsed, "output": output})
    finally:
        shutdown_extensions(wait=True)

    return results


def latest_log_entries(framework: str, run_id: str | None, prompts: list[str]) -> dict[str, dict[str, Any]]:
    """Return the most recent log entry per prompt for this framework.

    If run_id is provided, prefer entries from that run; otherwise take the
    latest matching entry overall.
    """
    log_path = ROOT / framework / "logs" / "latency.jsonl"
    by_prompt: dict[str, dict[str, Any]] = {}
    if not log_path.exists():
        return by_prompt
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("framework") != framework:
                continue
            user = entry.get("user")
            if user not in prompts:
                continue
            if run_id is not None and entry.get("run_id") != run_id:
                # Only collect this run when run_id is specified
                continue
            by_prompt[user] = entry
    return by_prompt


def append_history(
    run_id: str,
    frameworks: list[str],
    prompts: list[str],
    mode_tag: str,
) -> None:
    """After a bench run, append one aggregate line per (framework, prompt)."""
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        for fw in frameworks:
            entries = latest_log_entries(fw, run_id, prompts)
            for prompt in prompts:
                entry = entries.get(prompt)
                if entry is None:
                    continue
                latency = entry.get("latency") or {}
                record = {
                    "run_id": run_id,
                    "mode_tag": mode_tag,
                    "framework": fw,
                    "prompt": prompt,
                    "total": latency.get("total"),
                    "decision_ttft": latency.get("decision_ttft"),
                    "decision": latency.get("decision"),
                    "tool": latency.get("tool"),
                    "final": latency.get("final"),
                    "mode": entry.get("mode"),
                }
                handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def print_comparison(prompts: list[str], chosen: list[str], run_id: str | None) -> None:
    logs = {fw: latest_log_entries(fw, run_id, prompts) for fw in chosen}
    # Fallback: if a fresh run_id had no matches (e.g. skip-run mode), use latest overall
    for fw in chosen:
        if not logs[fw]:
            logs[fw] = latest_log_entries(fw, None, prompts)

    header_parts = ["prompt".ljust(48)]
    for fw in chosen:
        header_parts.append(f"{fw} total".rjust(12))
        header_parts.append(f"{fw} ttft".rjust(10))
    header = " ".join(header_parts)
    print("\n" + header)
    print("-" * len(header))
    for prompt in prompts:
        display = (prompt[:45] + "...") if len(prompt) > 48 else prompt
        parts = [display.ljust(48)]
        for fw in chosen:
            entry = logs.get(fw, {}).get(prompt) or {}
            latency = entry.get("latency") or {}
            total = latency.get("total")
            ttft = latency.get("decision_ttft")
            parts.append(("%.3f" % total if total is not None else "  -").rjust(12))
            parts.append(("%.3f" % ttft if ttft is not None else "  -").rjust(10))
        print(" ".join(parts))


def show_history(limit_runs: int) -> int:
    if not HISTORY_PATH.exists():
        print("No bench_history.jsonl yet. Run `python bench.py` to create one.")
        return 0

    entries: list[dict[str, Any]] = []
    with HISTORY_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not entries:
        print("bench_history.jsonl is empty.")
        return 0

    # Group by prompt; within each prompt, group by framework and sort by run_id.
    by_prompt: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for e in entries:
        prompt = e.get("prompt") or ""
        fw = e.get("framework") or "?"
        by_prompt.setdefault(prompt, {}).setdefault(fw, []).append(e)

    for prompt in sorted(by_prompt):
        print(f"\n{prompt}")
        for fw in sorted(by_prompt[prompt]):
            runs = sorted(by_prompt[prompt][fw], key=lambda r: r.get("run_id") or "")
            recent = runs[-limit_runs:]
            for r in recent:
                total = r.get("total")
                ttft = r.get("decision_ttft")
                total_s = f"{total:6.3f}s" if total is not None else "    -  "
                ttft_s = f"{ttft:.3f}s" if ttft is not None else "  -"
                marker = "  <- latest" if r is runs[-1] else ""
                print(f"  {r.get('run_id','?')}  {fw:9s}  total {total_s}  ttft {ttft_s}{marker}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["pygentic", "hermes"], help="Run just one framework.")
    parser.add_argument("--prompts", type=Path, help="Text file with one prompt per line.")
    parser.add_argument("--skip-run", action="store_true", help="Don't run new prompts; only summarize existing logs.")
    parser.add_argument("--history", action="store_true", help="Show recent bench-run history per prompt.")
    parser.add_argument("--history-limit", type=int, default=5, help="How many recent runs to show in --history.")
    parser.add_argument("--with-mcp", action="store_true", help="Enable MCP extension and add MCP-flavored prompts.")
    parser.add_argument("--think", action="store_true", help="Enable background thinking extension during the run.")
    parser.add_argument("--mode-tag", default=None, help="Override mode tag in bench_history.jsonl (default auto: default/mcp/think/mcp+think).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.history:
        return show_history(args.history_limit)

    prompts = DEFAULT_PROMPTS
    if args.prompts:
        prompts = [
            line.strip()
            for line in args.prompts.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    elif args.with_mcp:
        prompts = DEFAULT_PROMPTS + MCP_PROMPTS

    chosen = [args.only] if args.only else ["pygentic", "hermes"]

    # Derive a mode tag for the history entries (default | mcp | think | mcp+think)
    if args.mode_tag:
        mode_tag = args.mode_tag
    elif args.with_mcp and args.think:
        mode_tag = "mcp+think"
    elif args.with_mcp:
        mode_tag = "mcp"
    elif args.think:
        mode_tag = "think"
    else:
        mode_tag = "default"

    run_id: str | None = None
    if not args.skip_run:
        run_id = datetime.now(timezone.utc).isoformat(timespec="seconds")
        os.environ["BENCH_RUN_ID"] = run_id
        if args.with_mcp:
            os.environ["BENCH_WITH_MCP"] = "1"
        else:
            os.environ.pop("BENCH_WITH_MCP", None)
        if args.think:
            os.environ["BENCH_WITH_THINKING"] = "1"
        else:
            os.environ.pop("BENCH_WITH_THINKING", None)
        print(f"\n[bench] run_id = {run_id}  mode = {mode_tag}", flush=True)
        for fw in chosen:
            run_framework(fw, prompts)
        append_history(run_id, chosen, prompts, mode_tag)
        print(f"\n[bench] appended {len(prompts) * len(chosen)} entries to {HISTORY_PATH.name} (mode_tag={mode_tag})", flush=True)

    print_comparison(prompts, chosen, run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
