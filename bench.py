#!/usr/bin/env python3
"""Head-to-head benchmark: Pygentic vs Hermes on the same prompt set.

Loads each framework's model ONCE and runs the full prompt list against it,
then writes a side-by-side comparison table. Each framework's per-prompt
latency entries also land in its own logs/latency.jsonl (tagged with the
framework name + a run_id), and an aggregate appends to bench_history.jsonl
at the project root so historical runs are easy to compare.

Run:
  python bench.py                       # both frameworks, default prompts
  python bench.py --only python_custom_json   # just one framework
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
    if name == "python_custom_json":
        from python_custom_json.llm_client import LlamaCppPythonClient
        from python_custom_json.main import init_from_env, run_command, shutdown_extensions
        from python_custom_json.tools import ensure_workspace
    elif name == "python_hermes_xml":
        from python_hermes_xml.llm_client import LlamaCppPythonClient
        from python_hermes_xml.main import init_from_env, run_command, shutdown_extensions
        from python_hermes_xml.tools import ensure_workspace
    elif name == "python_pydantic_ai":
        from python_pydantic_ai.main import (
            LlamaCppPythonClient,
            init_from_env,
            run_command,
            shutdown_extensions,
            ensure_workspace,
        )
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
        # Drop the Llama instance and force GC. Without this, residual KV
        # state from earlier frameworks can poison llama_decode on Apple
        # Metal — pydantic_ai (the 3rd framework) crashed with
        # `llama_decode returned -3` until we added this cleanup.
        try:
            del client
        except UnboundLocalError:
            pass
        import gc as _gc
        _gc.collect()

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


def write_results_doc() -> int:
    """Regenerate docs/BENCH_RESULTS.md from bench_history.jsonl AND
    a shorter root-level BENCHMARK.md for at-a-glance frequent checks.

    Both files are auto-regenerated; do not hand-edit them.
    """
    from collections import defaultdict

    original = [
        "what time is it",
        "calculate 47 times 23 plus 12",
        "list the workspace",
        "make a file called bench.txt with the message hello from the benchmark",
        "read bench.txt out loud",
        "search the web for recent news about local llms",
        "tell me a one sentence story about a robot",
        "delete bench.txt",
        "what is the cpu and disk status of this machine",
    ]
    all_prompts = original + [
        "what time is it in shanghai",
        "search the web for trending youtube topics about home robots",
        "write a 4 sentence youtube intro script about a robot named Lilith discovering coffee and save it to youtube_intro.txt",
        "append a closing line to youtube_intro.txt asking viewers to subscribe",
        "narrate youtube_intro.txt out loud as if you are reading it for a youtube video",
        "come up with a catchy youtube title for a video about a robot vacuum gone rogue",
        "delete youtube_intro.txt",
        "remember that my preferred youtube video length is 90 seconds",
        "what video length do I prefer?",
        "what do you know about me?",
        "forget my video length preference",
    ]

    if not HISTORY_PATH.exists():
        print("bench_history.jsonl not found — run `python bench.py` first.")
        return 1

    runs: dict[tuple[str, str], dict[str, dict[str, tuple[float | None, float | None]]]] = defaultdict(lambda: defaultdict(dict))
    with HISTORY_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            rid = e.get("run_id") or "(legacy)"
            mt = e.get("mode_tag") or "default"
            fw = e.get("framework")
            if not fw:
                continue
            runs[(rid, mt)][fw][e.get("prompt", "")] = (e.get("total"), e.get("decision_ttft"))

    latest: dict[str, str] = {}
    for (rid, mt) in runs:
        if mt not in latest or rid > latest[mt]:
            latest[mt] = rid
    if "default" not in latest:
        print("No `default` mode runs found in bench_history.jsonl.")
        return 1

    default_runs = sorted({rid for (rid, mt) in runs if mt == "default"})

    def short(p: str, n: int = 48) -> str:
        return p[: n - 3] + "..." if len(p) > n else p

    out: list[str] = []
    out.append("# Benchmark results")
    out.append("")
    out.append("Snapshot of the latest bench runs across modes. Regenerate with:")
    out.append("")
    out.append("```bash")
    out.append("python bench.py                  # adds a fresh default run to bench_history.jsonl")
    out.append("python bench.py --write-results  # rewrites this file from the latest entries")
    out.append("```")
    out.append("")
    out.append("See [BENCHMARKING.md](BENCHMARKING.md) for bench mechanics and mode flags.")
    out.append("")

    r12 = latest["default"]
    out.append("## Current baseline — default mode")
    out.append("")
    out.append(f"Run `{r12}`.")
    out.append("")
    out.append("| prompt | python_custom_json total | python_custom_json ttft | python_hermes_xml total | python_hermes_xml ttft |")
    out.append("|---|---:|---:|---:|---:|")
    for p in all_prompts:
        pyg = runs[(r12, "default")]["python_custom_json"].get(p, (None, None))
        her = runs[(r12, "default")]["python_hermes_xml"].get(p, (None, None))
        cells = [
            short(p),
            f"{pyg[0]:.3f}" if pyg[0] is not None else "–",
            f"{pyg[1]:.3f}" if pyg[1] is not None else "–",
            f"{her[0]:.3f}" if her[0] is not None else "–",
            f"{her[1]:.3f}" if her[1] is not None else "–",
        ]
        out.append("| " + " | ".join(cells) + " |")
    out.append("")

    if len(default_runs) >= 4:
        key_runs = [
            ("r1 first baseline", default_runs[0]),
            (f"r{len(default_runs)-1} prior", default_runs[-2]),
            (f"r{len(default_runs)} latest", default_runs[-1]),
        ]
        out.append("## Historical consistency — original 9 prompts")
        out.append("")
        out.append("Spot-check for regressions: if the latest column drifts >50% from r1 on")
        out.append("the simple-tool prompts (calc, list, delete, cpu/disk), investigate.")
        out.append("")
        for fw in ("python_custom_json", "python_hermes_xml", "python_pydantic_ai"):
            out.append(f"### {fw.capitalize()} — total (seconds)")
            out.append("")
            header = "| prompt |" + "".join(f" {label} |" for label, _ in key_runs)
            out.append(header)
            out.append("|---" + "|---:" * len(key_runs) + "|")
            for p in original:
                cells = [f"| {short(p)} |"]
                for _, rid in key_runs:
                    v = runs[(rid, "default")][fw].get(p, (None,))[0]
                    cells.append(f" {v:.3f} |" if v is not None else " – |")
                out.append("".join(cells))
            out.append("")

    out.append("## Mode comparison — latest run per mode")
    out.append("")
    modes_order = ["default", "think", "memory", "mcp", "mcp+think+memory"]
    modes = [(mt, latest[mt]) for mt in modes_order if mt in latest]
    for mt, rid in modes:
        out.append(f"- **{mt}** ⟶ run `{rid}`")
    out.append("")
    for fw in ("python_custom_json", "python_hermes_xml", "python_pydantic_ai"):
        out.append(f"### {fw.capitalize()} — total (seconds)")
        out.append("")
        header = "| prompt |" + "".join(f" {mt} |" for mt, _ in modes)
        out.append(header)
        out.append("|---" + "|---:" * len(modes) + "|")
        for p in all_prompts:
            cells = [f"| {short(p)} |"]
            for mt, rid in modes:
                v = runs[(rid, mt)][fw].get(p, (None,))[0]
                cells.append(f" {v:.3f} |" if v is not None else " – |")
            out.append("".join(cells))
        out.append("")

    out.append("## What to watch for in future runs")
    out.append("")
    out.append("- **Pygentic single-tool prompts** (calculate, list, delete, cpu/disk) should stay around 0.6–1.2 s. A jump to 3 s+ means the multi-step loop is firing when it shouldn't.")
    out.append("- **Hermes single-tool prompts** should stay around 0.5–1.1 s.")
    out.append("- **TTFT** for warm prompts should be ~0.10–0.15 s on both. Spikes to 0.5 s+ indicate a KV cache miss.")
    out.append("- **Memory prompts** route reliably only with `--with-memory`. Raw-mode failures there are expected, not regressions.")
    out.append("- **TTS prompts** are wall-clock-dominated by audio playback. Variance there is normal.")

    path = ROOT / "docs" / "BENCH_RESULTS.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)} ({len(out)} lines, {len(default_runs)} default runs, {len(modes)} modes)")

    # Also write the shorter root-level BENCHMARK.md
    _write_root_benchmark(runs, latest, original, all_prompts)
    return 0


def _expected_tool_map() -> dict[str, str | None]:
    """Mirror of bench.py's DEFAULT_PROMPTS expected_tool mapping."""
    return {text: expected for text, expected in DEFAULT_PROMPTS}


def _write_root_benchmark(
    runs: dict,
    latest: dict[str, str],
    original_prompts: list[str],
    all_prompts: list[str],
) -> None:
    """Write a compact, at-a-glance BENCHMARK.md at the project root.

    Four sections:
      1. Best record per framework (lowest latency ever per prompt)
      2. Latest 3-way comparison
      3. Per-tool average (latest run)
      4. Per-framework historical trend (last N runs)
    """
    if "default" not in latest:
        return

    target_frameworks = ("python_custom_json", "python_hermes_xml", "python_pydantic_ai")
    matching_runs = [
        rid
        for (rid, mt) in runs
        if mt == "default"
        and all(fw in runs[(rid, mt)] for fw in target_frameworks)
    ]
    if matching_runs:
        run_id = max(matching_runs)
    else:
        run_id = latest["default"]
    frameworks_in_run = [fw for fw in target_frameworks if fw in runs[(run_id, "default")]]
    if not frameworks_in_run:
        return

    expected = _expected_tool_map()

    # Index of all default-mode runs for the current framework names.
    # Skip runs that have ZERO data for a framework so we don't show empty
    # leading columns in the trend tables.
    default_runs_per_fw: dict[str, list[tuple[str, dict[str, float]]]] = {fw: [] for fw in target_frameworks}
    for (rid, mt), frameworks in runs.items():
        if mt != "default":
            continue
        for fw, prompts_dict in frameworks.items():
            if fw not in target_frameworks:
                continue
            totals_map = {p: v[0] for p, v in prompts_dict.items() if v[0] is not None}
            if not totals_map:
                continue  # nothing to show for this framework on this run
            default_runs_per_fw[fw].append((rid, totals_map))
    for fw in target_frameworks:
        default_runs_per_fw[fw].sort(key=lambda x: x[0])

    out: list[str] = []
    out.append("# Benchmark")
    out.append("")
    out.append(f"Last run: `{run_id}` · frameworks: {', '.join(frameworks_in_run)}")
    out.append("")
    out.append(f"Regenerate with `python bench.py && python bench.py --write-results`.")
    out.append(f"Detail history: [docs/BENCH_RESULTS.md](docs/BENCH_RESULTS.md).")
    out.append("")

    # ============================================================================
    # SECTION 1: Best record per framework (lowest ever seen per prompt)
    # ============================================================================
    out.append("## 1. Best record per framework (lowest latency ever)")
    out.append("")
    out.append("Each cell = the fastest result that framework has *ever* achieved on this prompt across all default-mode runs in `bench_history.jsonl`. Useful as a personal best target.")
    out.append("")
    header = "| prompt | tool |"
    sep = "|---|---|"
    for fw in frameworks_in_run:
        header += f" {fw} best |"
        sep += "---:|"
    out.append(header)
    out.append(sep)
    best_totals = {fw: 0.0 for fw in frameworks_in_run}
    best_counts = {fw: 0 for fw in frameworks_in_run}
    for prompt in all_prompts:
        tool = expected.get(prompt) or "(free-text)"
        row = f"| {prompt[:48] + ('...' if len(prompt) > 48 else '')} | `{tool}` |"
        for fw in frameworks_in_run:
            values = [
                totals_map[prompt]
                for _, totals_map in default_runs_per_fw[fw]
                if prompt in totals_map
            ]
            if values:
                best = min(values)
                best_totals[fw] += best
                best_counts[fw] += 1
                row += f" {best:.3f} |"
            else:
                row += " – |"
        out.append(row)
    sum_row = "| **best-of-bests total** | |"
    avg_row = "| **best-of-bests avg** | |"
    for fw in frameworks_in_run:
        n = best_counts[fw] or 1
        sum_row += f" **{best_totals[fw]:.2f}** |"
        avg_row += f" **{best_totals[fw] / n:.3f}** |"
    out.append(sum_row)
    out.append(avg_row)
    out.append("")

    # ============================================================================
    # SECTION 2: Latest 3-way comparison
    # ============================================================================
    out.append("## 2. Latest run — per-prompt totals")
    out.append("")
    header = "| prompt | tool |"
    sep = "|---|---|"
    for fw in frameworks_in_run:
        header += f" {fw} |"
        sep += "---:|"
    out.append(header)
    out.append(sep)
    framework_totals = {fw: 0.0 for fw in frameworks_in_run}
    framework_counts = {fw: 0 for fw in frameworks_in_run}
    for prompt in all_prompts:
        tool = expected.get(prompt) or "(free-text)"
        row = f"| {prompt[:48] + ('...' if len(prompt) > 48 else '')} | `{tool}` |"
        for fw in frameworks_in_run:
            v = runs[(run_id, "default")][fw].get(prompt, (None,))[0]
            if v is not None:
                framework_totals[fw] += v
                framework_counts[fw] += 1
                row += f" {v:.3f} |"
            else:
                row += " – |"
        out.append(row)
    sum_row = "| **TOTAL** | |"
    avg_row = "| **AVG / prompt** | |"
    for fw in frameworks_in_run:
        n = framework_counts[fw] or 1
        sum_row += f" **{framework_totals[fw]:.2f}** |"
        avg_row += f" **{framework_totals[fw] / n:.3f}** |"
    out.append(sum_row)
    out.append(avg_row)
    out.append("")

    # ============================================================================
    # SECTION 3: Per-tool averages on the latest run
    # ============================================================================
    out.append("## 3. Per-tool average seconds (latest run)")
    out.append("")
    tool_groups: dict[str, list[str]] = {}
    for prompt in all_prompts:
        t = expected.get(prompt) or "(free-text)"
        tool_groups.setdefault(t, []).append(prompt)
    header = "| tool | n prompts |"
    sep = "|---|---:|"
    for fw in frameworks_in_run:
        header += f" {fw} avg |"
        sep += "---:|"
    out.append(header)
    out.append(sep)
    tool_keys = sorted(t for t in tool_groups if t != "(free-text)")
    if "(free-text)" in tool_groups:
        tool_keys.append("(free-text)")
    for tool in tool_keys:
        prompts_in_group = tool_groups[tool]
        row = f"| `{tool}` | {len(prompts_in_group)} |"
        for fw in frameworks_in_run:
            values = []
            for p in prompts_in_group:
                v = runs[(run_id, "default")][fw].get(p, (None,))[0]
                if v is not None:
                    values.append(v)
            if values:
                row += f" {sum(values) / len(values):.3f} |"
            else:
                row += " – |"
        out.append(row)
    out.append("")

    # ============================================================================
    # SECTION 4: Per-framework historical trend (last N runs)
    # ============================================================================
    history_limit = 5
    out.append(f"## 4. Per-framework historical trend (last {history_limit} runs)")
    out.append("")
    out.append("Each framework's latencies across the most recent default-mode runs. Spot regressions and improvements over time.")
    out.append("")
    for fw in frameworks_in_run:
        fw_runs = default_runs_per_fw[fw][-history_limit:]
        if not fw_runs:
            continue
        out.append(f"### {fw}")
        out.append("")
        run_labels = []
        total_runs_for_fw = len(default_runs_per_fw[fw])
        first_index_shown = total_runs_for_fw - len(fw_runs) + 1
        for i, (rid, _) in enumerate(fw_runs):
            run_labels.append(f"r{first_index_shown + i}")
        header = "| prompt |"
        sep = "|---|"
        for label in run_labels:
            header += f" {label} |"
            sep += "---:|"
        out.append(header)
        out.append(sep)
        for prompt in all_prompts:
            row = f"| {prompt[:46] + ('...' if len(prompt) > 46 else '')} |"
            for _, totals_map in fw_runs:
                v = totals_map.get(prompt)
                row += f" {v:.3f} |" if v is not None else " – |"
            out.append(row)
        out.append("")
        out.append(f"Run IDs: " + ", ".join(f"`{label}`=`{rid}`" for label, (rid, _) in zip(run_labels, fw_runs)))
        out.append("")

    # ============================================================================
    # SECTION 5: Headlines
    # ============================================================================
    out.append("## Headlines")
    out.append("")
    fastest_fw = min(frameworks_in_run, key=lambda f: framework_totals[f])
    fastest_avg = framework_totals[fastest_fw] / (framework_counts[fastest_fw] or 1)
    slowest_fw = max(frameworks_in_run, key=lambda f: framework_totals[f])
    slowest_avg = framework_totals[slowest_fw] / (framework_counts[slowest_fw] or 1)
    out.append(f"- Latest fastest: **{fastest_fw}** ({framework_totals[fastest_fw]:.2f}s total, {fastest_avg:.3f}s avg).")
    out.append(f"- Latest slowest: **{slowest_fw}** ({framework_totals[slowest_fw]:.2f}s total, {slowest_avg:.3f}s avg).")
    out.append(f"- Latest gap: {slowest_avg - fastest_avg:.3f}s/prompt ({(slowest_avg / fastest_avg - 1) * 100:.1f}% slower).")
    best_avg_per_fw = {
        fw: best_totals[fw] / (best_counts[fw] or 1) for fw in frameworks_in_run
    }
    best_record_holder = min(best_avg_per_fw.keys(), key=lambda f: best_avg_per_fw[f])
    out.append(f"- Best-record holder (lowest avg across personal bests): **{best_record_holder}** ({best_avg_per_fw[best_record_holder]:.3f}s avg).")
    out.append("")

    # --- Side-by-side per-prompt totals -------------------------------------------
    out.append("## Per-prompt total seconds")
    out.append("")
    header = "| prompt | tool |"
    sep = "|---|---|"
    for fw in frameworks_in_run:
        header += f" {fw} |"
        sep += "---:|"
    out.append(header)
    out.append(sep)
    framework_totals = {fw: 0.0 for fw in frameworks_in_run}
    framework_counts = {fw: 0 for fw in frameworks_in_run}
    for prompt in all_prompts:
        tool = expected.get(prompt) or "(free-text)"
        row = f"| {prompt[:48] + ('...' if len(prompt) > 48 else '')} | `{tool}` |"
        for fw in frameworks_in_run:
            v = runs[(run_id, "default")][fw].get(prompt, (None,))[0]
            if v is not None:
                framework_totals[fw] += v
                framework_counts[fw] += 1
                row += f" {v:.3f} |"
            else:
                row += " – |"
        out.append(row)
    # totals
    sum_row = "| **TOTAL** | |"
    avg_row = "| **AVG / prompt** | |"
    for fw in frameworks_in_run:
        sum_row += f" **{framework_totals[fw]:.2f}** |"
        n = framework_counts[fw] or 1
        avg_row += f" **{framework_totals[fw] / n:.3f}** |"
    out.append(sum_row)
    out.append(avg_row)
    out.append("")

    # --- Per-tool average across frameworks ---------------------------------------
    out.append("## Per-tool average seconds (across the latest run)")
    out.append("")
    out.append("Each row groups prompts by the tool they were expected to call. `(free-text)` means no tool — model answered directly.")
    out.append("")
    # group prompts by expected tool
    tool_groups: dict[str, list[str]] = {}
    for prompt in all_prompts:
        t = expected.get(prompt) or "(free-text)"
        tool_groups.setdefault(t, []).append(prompt)

    header = "| tool | n prompts |"
    sep = "|---|---:|"
    for fw in frameworks_in_run:
        header += f" {fw} avg |"
        sep += "---:|"
    out.append(header)
    out.append(sep)
    # Sort tools for stable output; put free-text at the end
    tool_keys = sorted(t for t in tool_groups if t != "(free-text)")
    if "(free-text)" in tool_groups:
        tool_keys.append("(free-text)")
    for tool in tool_keys:
        prompts_in_group = tool_groups[tool]
        row = f"| `{tool}` | {len(prompts_in_group)} |"
        for fw in frameworks_in_run:
            values = []
            for p in prompts_in_group:
                v = runs[(run_id, "default")][fw].get(p, (None,))[0]
                if v is not None:
                    values.append(v)
            if values:
                row += f" {sum(values)/len(values):.3f} |"
            else:
                row += " – |"
        out.append(row)
    out.append("")

    # --- Summary ----------------------------------------------------------------
    out.append("## Headlines")
    out.append("")
    # Find slowest tool overall
    fastest_fw = min(frameworks_in_run, key=lambda f: framework_totals[f])
    fastest_avg = framework_totals[fastest_fw] / (framework_counts[fastest_fw] or 1)
    slowest_fw = max(frameworks_in_run, key=lambda f: framework_totals[f])
    slowest_avg = framework_totals[slowest_fw] / (framework_counts[slowest_fw] or 1)
    out.append(f"- Fastest framework on this run: **{fastest_fw}** ({framework_totals[fastest_fw]:.2f}s total, {fastest_avg:.3f}s avg).")
    out.append(f"- Slowest: **{slowest_fw}** ({framework_totals[slowest_fw]:.2f}s total, {slowest_avg:.3f}s avg).")
    out.append(f"- Gap: {slowest_avg - fastest_avg:.3f}s/prompt ({(slowest_avg/fastest_avg - 1) * 100:.1f}% slower).")
    out.append("")
    out.append("See `docs/BENCH_RESULTS.md` for the historical view and per-mode breakdown (default / mcp / think / memory / mcp+think+memory).")

    bench_path = ROOT / "BENCHMARK.md"
    bench_path.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {bench_path.relative_to(ROOT)} (root-level table)")


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
        for fw in ("python_custom_json", "python_hermes_xml", "python_pydantic_ai"):
            cols.append(f"{mt[:6]}_{fw[:3]}_t".rjust(12))
    header = " ".join(cols)
    print("\n" + header)
    print("-" * len(header))

    for prompt in prompts_in_order:
        display = prompt[:45] + "..." if len(prompt) > 48 else prompt
        row = [display.ljust(48)]
        for mt in mode_tags:
            for fw in ("python_custom_json", "python_hermes_xml", "python_pydantic_ai"):
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
    parser.add_argument("--only", choices=["python_custom_json", "python_hermes_xml", "python_pydantic_ai"], help="Run just one framework.")
    parser.add_argument("--prompts", type=Path, help="Text file with one prompt per line.")
    parser.add_argument("--skip-run", action="store_true", help="Don't run new prompts; only summarize existing logs.")
    parser.add_argument("--history", action="store_true", help="Show recent bench-run history per prompt.")
    parser.add_argument("--history-limit", type=int, default=5, help="How many recent runs to show in --history.")
    parser.add_argument("--compare", nargs="+", default=None, help="Compare latest runs of these mode_tags (e.g. --compare default think memory).")
    parser.add_argument("--write-results", action="store_true", help="Regenerate docs/BENCH_RESULTS.md from bench_history.jsonl and exit.")
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
    if args.write_results:
        return write_results_doc()

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

    chosen = [args.only] if args.only else ["python_custom_json", "python_hermes_xml", "python_pydantic_ai"]

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
