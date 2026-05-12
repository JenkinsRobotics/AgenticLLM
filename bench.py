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

# Sentinel value for the (prompt, expected_tool) tuples: skip validation.
# Used for prompts loaded from a user file where we can't know what's expected.
_SKIP_VALIDATION = "_skip_"


# Prompts are (text, expected_tool) pairs. expected_tool == None means the
# prompt should be answered as a free-text final (no tool). expected_tool ==
# "*" means we don't care which tool, just that A tool was picked. A failed
# expectation is counted in the bench summary at the end of each run.
DEFAULT_PROMPTS: list[tuple[str, str | None]] = [
    # General tool routing
    ("what time is it", "get_time"),
    ("what time is it in shanghai", "get_time"),
    ("calculate 47 times 23 plus 12", "calculate"),
    ("list the workspace", "list_directory"),
    ("make a file called bench.txt with the message hello from the benchmark", "create_file"),
    ("read bench.txt out loud", "speak_file"),
    ("search the web for recent news about local llms", "web_search"),
    ("tell me a one sentence story about a robot", None),
    ("delete bench.txt", "delete_file"),
    ("what is the cpu and disk status of this machine", "system_status"),

    # YouTube robot-content workflow
    ("search the web for trending youtube topics about home robots", "web_search"),
    ("write a 4 sentence youtube intro script about a robot named Lilith discovering coffee and save it to youtube_intro.txt", "create_file"),
    ("append a closing line to youtube_intro.txt asking viewers to subscribe", "append_file"),
    ("narrate youtube_intro.txt out loud as if you are reading it for a youtube video", "speak_file"),
    ("come up with a catchy youtube title for a video about a robot vacuum gone rogue", None),
    ("delete youtube_intro.txt", "delete_file"),

    # Memory layer — natural phrasings, let the model pick its own keys
    ("remember that my preferred youtube video length is 90 seconds", "remember"),
    ("what video length do I prefer?", "recall"),
    ("what do you know about me?", "list_facts"),
    ("forget my video length preference", "forget"),
]


# Prompts that exercise MCP-only capability. Added to the regular set when
# --with-mcp is passed. They should fail (or fall back to web_search) without MCP.
MCP_PROMPTS: list[tuple[str, str | None]] = [
    ("use the mcp:web/fetch tool to retrieve https://example.com and tell me what it says", "mcp:web/fetch"),
    ("fetch the homepage of https://news.ycombinator.com using mcp:web/fetch and list the first three story titles", "mcp:web/fetch"),
]


def run_framework(name: str, prompts: list[tuple[str, str | None]]) -> list[dict[str, Any]]:
    """Import the framework's agent, load its model once, run all prompts.

    prompts is a list of (text, expected_tool) tuples. After each turn the
    framework's most recent log entry is checked: did the chosen tool match
    expected_tool? Was there a parse fallback? Mismatches are accumulated
    and printed in the run summary.
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

    log_path = ROOT / name / "logs" / "latency.jsonl"

    print(f"\n=== {name}: loading model ===", flush=True)
    client = LlamaCppPythonClient()
    ensure_workspace()
    init_from_env(client)

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    try:
        for prompt_text, expected_tool in prompts:
            print(f"\n--- {name} :: {prompt_text!r}", flush=True)
            captured = io.StringIO()
            started = time.perf_counter()
            with redirect_stdout(captured):
                run_command(client, prompt_text, "auto")
            elapsed = time.perf_counter() - started
            output = captured.getvalue()
            print(output.rstrip(), flush=True)

            # Read the just-written log entry for validation.
            last_entry = _tail_log(log_path)
            actual_tool = None
            if last_entry:
                dec = last_entry.get("decision") or {}
                actual_tool = dec.get("tool") if isinstance(dec, dict) else None
            parse_fallback = (last_entry or {}).get("parse_fallback")

            verdict = _check_expectation(expected_tool, actual_tool, parse_fallback)
            print(f"    [check] {verdict['summary']}", flush=True)
            if verdict["status"] != "ok":
                failures.append({
                    "prompt": prompt_text,
                    "expected_tool": expected_tool,
                    "actual_tool": actual_tool,
                    "parse_fallback": parse_fallback,
                    "verdict": verdict["summary"],
                })

            results.append({
                "prompt": prompt_text,
                "elapsed_s": elapsed,
                "output": output,
                "expected_tool": expected_tool,
                "actual_tool": actual_tool,
                "parse_fallback": parse_fallback,
                "verdict_status": verdict["status"],
            })
    finally:
        shutdown_extensions(wait=True)

    # Per-framework summary
    passed = sum(1 for r in results if r["verdict_status"] == "ok")
    total = len(results)
    print(f"\n[{name}] correctness: {passed}/{total} prompts passed expected_tool check.", flush=True)
    for fail in failures:
        print(f"  FAIL: {fail['prompt'][:60]!r}  ->  {fail['verdict']}", flush=True)

    return results


def _tail_log(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            chunk = min(8192, size)
            handle.seek(max(0, size - chunk))
            data = handle.read().decode("utf-8", errors="replace")
        last_line = data.rstrip().rsplit("\n", 1)[-1]
        return json.loads(last_line)
    except Exception:
        return None


def _check_expectation(
    expected_tool: str | None,
    actual_tool: str | None,
    parse_fallback: str | None,
) -> dict[str, str]:
    if expected_tool == _SKIP_VALIDATION:
        return {"status": "ok", "summary": "(validation skipped)"}
    if parse_fallback == "silent_format_fail":
        return {"status": "fail", "summary": "silent format failure (model emitted malformed tool call, parsed as final)"}
    if expected_tool is None:
        if actual_tool is None:
            return {"status": "ok", "summary": "final-answer as expected"}
        return {"status": "warn", "summary": f"expected free-text final, got tool={actual_tool!r}"}
    if expected_tool == "*":
        return {"status": "ok", "summary": f"any tool — got {actual_tool!r}"} if actual_tool else {
            "status": "fail",
            "summary": "expected any tool, got final answer",
        }
    if actual_tool == expected_tool:
        suffix = f" (recovered via {parse_fallback})" if parse_fallback else ""
        return {"status": "ok", "summary": f"matched {expected_tool!r}{suffix}"}
    return {
        "status": "fail",
        "summary": f"expected {expected_tool!r}, got {actual_tool!r}",
    }


def _prompt_texts(prompts: list[tuple[str, str | None]] | list[str]) -> list[str]:
    """Accept either a list of strings or a list of (text, expected_tool) tuples."""
    out: list[str] = []
    for item in prompts:
        if isinstance(item, tuple):
            out.append(item[0])
        else:
            out.append(item)
    return out


def latest_log_entries(
    framework: str,
    run_id: str | None,
    prompts: list[tuple[str, str | None]] | list[str],
) -> dict[str, dict[str, Any]]:
    """Return the most recent log entry per prompt for this framework."""
    log_path = ROOT / framework / "logs" / "latency.jsonl"
    by_prompt: dict[str, dict[str, Any]] = {}
    if not log_path.exists():
        return by_prompt
    prompt_texts = set(_prompt_texts(prompts))
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("framework") != framework:
                continue
            user = entry.get("user")
            if user not in prompt_texts:
                continue
            if run_id is not None and entry.get("run_id") != run_id:
                continue
            by_prompt[user] = entry
    return by_prompt


def append_history(
    run_id: str,
    frameworks: list[str],
    prompts: list[tuple[str, str | None]] | list[str],
    mode_tag: str,
) -> None:
    """After a bench run, append one aggregate line per (framework, prompt)."""
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        for fw in frameworks:
            entries = latest_log_entries(fw, run_id, prompts)
            for prompt in _prompt_texts(prompts):
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


def print_comparison(
    prompts: list[tuple[str, str | None]] | list[str],
    chosen: list[str],
    run_id: str | None,
) -> None:
    logs = {fw: latest_log_entries(fw, run_id, prompts) for fw in chosen}
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
    for prompt in _prompt_texts(prompts):
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


def show_compare(mode_tags: list[str]) -> int:
    """Cross-mode comparison table for the most recent run of each mode_tag.

    Example:  python bench.py --compare default think memory
    """
    if not HISTORY_PATH.exists():
        print("bench_history.jsonl not found.")
        return 0

    entries: list[dict[str, Any]] = []
    with HISTORY_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Most recent run_id per mode_tag
    latest_run: dict[str, str] = {}
    for entry in entries:
        mt = entry.get("mode_tag")
        rid = entry.get("run_id")
        if not mt or not rid or mt not in mode_tags:
            continue
        if mt not in latest_run or rid > latest_run[mt]:
            latest_run[mt] = rid

    # Index by (prompt, framework, mode_tag) -> total / ttft
    idx: dict[tuple[str, str, str], tuple[float | None, float | None]] = {}
    prompts_in_order: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        mt = entry.get("mode_tag")
        if mt not in mode_tags or entry.get("run_id") != latest_run.get(mt):
            continue
        prompt = entry.get("prompt") or ""
        fw = entry.get("framework") or ""
        if prompt and prompt not in seen:
            prompts_in_order.append(prompt)
            seen.add(prompt)
        idx[(prompt, fw, mt)] = (entry.get("total"), entry.get("decision_ttft"))

    # Header
    cols = ["prompt".ljust(48)]
    for mt in mode_tags:
        for fw in ("pygentic", "hermes"):
            cols.append(f"{mt[:6]}_{fw[:3]}_t".rjust(12))
    header = " ".join(cols)
    print("\n" + header)
    print("-" * len(header))

    for prompt in prompts_in_order:
        display = prompt[:45] + "..." if len(prompt) > 48 else prompt
        row = [display.ljust(48)]
        for mt in mode_tags:
            for fw in ("pygentic", "hermes"):
                total, _ = idx.get((prompt, fw, mt), (None, None))
                row.append(("%.3f" % total if total is not None else "  -").rjust(12))
        print(" ".join(row))

    # Footer with the run_ids that fed this view
    print("")
    for mt in mode_tags:
        if mt in latest_run:
            print(f"  {mt}: {latest_run[mt]}")
        else:
            print(f"  {mt}: (no run found)")
    return 0


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
    parser.add_argument("--compare", nargs="+", default=None, help="Compare latest runs of these mode_tags (e.g. --compare default think memory).")
    parser.add_argument("--with-mcp", action="store_true", help="Enable MCP extension and add MCP-flavored prompts.")
    parser.add_argument("--think", action="store_true", help="Enable background thinking extension during the run.")
    parser.add_argument("--with-memory", action="store_true", help="Enable identity + session history + episodic log during the run.")
    parser.add_argument("--mode-tag", default=None, help="Override mode tag in bench_history.jsonl.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.history:
        return show_history(args.history_limit)
    if args.compare:
        return show_compare(args.compare)

    prompts: list[tuple[str, str | None]] = DEFAULT_PROMPTS
    if args.prompts:
        # User-supplied prompts: no expected_tool — skip validation per prompt.
        prompts = [
            (line.strip(), _SKIP_VALIDATION)
            for line in args.prompts.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    elif args.with_mcp:
        prompts = DEFAULT_PROMPTS + MCP_PROMPTS

    chosen = [args.only] if args.only else ["pygentic", "hermes"]

    # Derive a mode tag for the history entries.
    if args.mode_tag:
        mode_tag = args.mode_tag
    else:
        parts: list[str] = []
        if args.with_mcp:
            parts.append("mcp")
        if args.think:
            parts.append("think")
        if args.with_memory:
            parts.append("memory")
        mode_tag = "+".join(parts) if parts else "default"

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
        if args.with_memory:
            os.environ["BENCH_WITH_MEMORY"] = "1"
        else:
            os.environ.pop("BENCH_WITH_MEMORY", None)
        print(f"\n[bench] run_id = {run_id}  mode = {mode_tag}", flush=True)
        for fw in chosen:
            run_framework(fw, prompts)
        append_history(run_id, chosen, prompts, mode_tag)
        print(f"\n[bench] appended {len(prompts) * len(chosen)} entries to {HISTORY_PATH.name} (mode_tag={mode_tag})", flush=True)

    print_comparison(prompts, chosen, run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
