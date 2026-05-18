#!/usr/bin/env python3
"""Full benchmark across every agentic framework in this repo.

Runs the canonical 23-prompt suite against:
  - python_custom_json   (raw JSON-emitting agent, in-process)
  - python_hermes_xml    (XML tool-call agent, in-process)
  - python_pydantic_ai   (pydantic-ai over Gemma, in-process)
  - python_jaeger        (Jaeger v2 pipeline, in-process)
  - python_hermes_agent  (NousResearch hermes-agent over HTTP via
                          llama_cpp.server — driven by the `hermes` CLI)

Every framework is loaded in its own subprocess (bench_worker.py) so each
gets a fresh Metal context — back-to-back loads in a single process leak
KV state across frameworks on Apple Silicon and trip `llama_decode -3`
mid-bench. python_hermes_agent is the exception: it talks to a separate
llama_cpp.server we start/stop here.

Each run regenerates `benchmark/BENCHMARK.md` with:
  1. Best record per framework (lowest latency ever, per prompt)
  2. Latest run — per-prompt totals (cross-framework)
  3. Per-tool average seconds (latest run, cross-framework)
  4. Per-framework historical trend (last 5 runs)
  5. Headlines

Per-(framework × prompt × run) rows append to `bench_history.jsonl` so
sections 1 and 4 stay meaningful across runs. Raw payload lands in
`bench_results.json`.

Run:
  python bench.py                                # all 5 frameworks, full suite
  python bench.py --frameworks python_jaeger     # subset
  python bench.py --runs 3                       # repeat each prompt N times
  python bench.py --prompts custom.txt           # one prompt per line
  python bench.py --skip-hermes-agent            # 4 in-process only
  python bench.py --no-history --no-md           # one-off, JSON only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent           # benchmark/
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

WORKER = ROOT / "bench_worker.py"
HISTORY_PATH = ROOT / "bench_history.jsonl"
JSON_OUT = ROOT / "bench_results.json"
MD_OUT = ROOT / "BENCHMARK.md"

VENV_PY = PROJECT_ROOT / ".venv" / "bin" / "python"
HERMES_BIN = PROJECT_ROOT / ".venv" / "bin" / "hermes"
LLM_PORT = int(os.environ.get("HERMES_LLM_PORT", "11435"))

# Jaeger first: each framework load leaves KV residue on Metal. Putting
# python_jaeger first gives it a clean context; python_pydantic_ai recovers
# best from residue, so it goes last in the in-process group.
IN_PROCESS_FRAMEWORKS_DEFAULT = (
    "python_jaeger,python_custom_json,python_hermes_xml,python_pydantic_ai"
)


# ---------------------------------------------------------------------------
# Canonical prompt suite (mirrors BENCHMARK.md's historical 23-prompt set).
# expected_tool uses the "common" name; Jaeger's surface is mapped via
# JAEGER_TOOL_ALIASES so the per-tool table still groups correctly.
# ---------------------------------------------------------------------------
DEFAULT_PROMPTS: list[tuple[str, str | None]] = [
    ("what time is it", "get_time"),
    ("what time is it in shanghai", "get_time"),
    ("calculate 47 times 23 plus 12", "calculate"),
    ("calculate the square root of 12345", "calculate"),
    ("list the workspace", "list_directory"),
    ("make a file called bench.txt with the message hello from the benchmark", "create_file"),
    ("read bench.txt out loud", "speak_file"),
    ("search the web for recent news about local llms", "web_search"),
    ("what is the current weather in Seattle", "get_weather"),
    ("tell me a one sentence story about a robot", None),
    ("in three words, what is the capital of France", None),
    ("delete bench.txt", "delete_file"),
    ("what is the cpu and disk status of this machine", "system_status"),

    # YouTube robot-content workflow (create → append → speak → delete)
    ("search the web for trending youtube topics about home robots", "web_search"),
    ("write a 4 sentence youtube intro script about a robot named Lilith discovering coffee and save it to youtube_intro.txt", "create_file"),
    ("append a closing line to youtube_intro.txt asking viewers to subscribe", "append_file"),
    ("narrate youtube_intro.txt out loud as if you are reading it for a youtube video", "speak_file"),
    ("come up with a catchy youtube title for a video about a robot vacuum gone rogue", None),
    ("delete youtube_intro.txt", "delete_file"),

    # Memory layer
    ("remember that my preferred youtube video length is 90 seconds", "remember"),
    ("what video length do I prefer?", "recall"),
    ("what do you know about me?", "list_facts"),
    ("forget my video length preference", "forget"),
]

# Jaeger renamed a couple of tools when it sandboxed file I/O to skills/.
# We keep the canonical name in DEFAULT_PROMPTS for the cross-framework
# table and translate per-row when annotating Jaeger results.
JAEGER_TOOL_ALIASES: dict[str, str] = {
    "create_file": "file_write",
    "list_directory": "list_skill_dir",
}


# ---------------------------------------------------------------------------
# bench_worker.py invocation (in-process frameworks)
# ---------------------------------------------------------------------------
def run_via_worker(framework: str, prompts: list[str], timeout_s: float) -> list[dict[str, Any]]:
    if not WORKER.exists():
        raise FileNotFoundError(f"bench_worker.py missing at {WORKER}")
    blob = "\n".join(prompts)
    print(f"\n=== {framework} (subprocess worker, {len(prompts)} prompts) ===",
          flush=True)
    try:
        proc = subprocess.run(
            [sys.executable, str(WORKER), framework],
            input=blob, capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        print(f"[{framework}] TIMEOUT after {timeout_s:.0f}s", flush=True)
        return [{"framework": framework, "prompt": p, "text": "",
                 "tool_activity": [], "elapsed_s": 0.0,
                 "error": f"subprocess timeout after {timeout_s:.0f}s"} for p in prompts]
    if proc.stderr:
        print(proc.stderr, flush=True)

    json_line = ""
    for line in (proc.stdout or "").splitlines():
        if line.strip().startswith("{"):
            json_line = line.strip()
    if not json_line:
        print(f"[{framework}] worker stdout had no JSON (exit {proc.returncode}); tail:",
              flush=True)
        print((proc.stdout or "")[-2000:], flush=True)
        return [{"framework": framework, "prompt": p, "text": "",
                 "tool_activity": [], "elapsed_s": 0.0,
                 "error": f"worker exit {proc.returncode}, no JSON"} for p in prompts]
    payload = json.loads(json_line)
    if proc.returncode != 0 and payload.get("results"):
        print(f"[{framework}] worker exited {proc.returncode} after producing "
              "valid JSON (likely Metal atexit assert — harmless)", flush=True)
    return payload.get("results", [])


# ---------------------------------------------------------------------------
# python_hermes_agent — HTTP via llama_cpp.server + `hermes chat -Q -q`
# ---------------------------------------------------------------------------
def _wait_for_port(host: str, port: int, timeout_s: float = 60.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def start_llama_server(log_path: Path) -> subprocess.Popen:
    from model_resolver import resolve_model_path
    model = str(resolve_model_path())
    if not Path(model).exists():
        raise FileNotFoundError(f"model not found: {model}")
    cmd = [
        str(VENV_PY), "-m", "llama_cpp.server",
        "--model", model,
        "--host", "127.0.0.1",
        "--port", str(LLM_PORT),
        # hermes-agent prefills ~12-14K tokens of system + tool schema before
        # the user message; 32K leaves headroom (Gemma 4 trained on 262K).
        "--n_ctx", "32768",
        "--n_gpu_layers", "-1",
        # No --chat_format: let llama-cpp-python read the GGUF's embedded
        # template. The hardcoded "gemma" template is for Gemma 1/2 and
        # leaks <|channel>thought\n markers on Gemma 4.
        "--model_alias", "gemma-4-26b-a4b",
    ]
    log_fh = log_path.open("w")
    print(f"\n=== starting local LLM server on :{LLM_PORT} (log: {log_path.name}) ===",
          flush=True)
    proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT,
                            cwd=str(PROJECT_ROOT))
    if not _wait_for_port("127.0.0.1", LLM_PORT, timeout_s=120.0):
        proc.terminate()
        raise RuntimeError(f"LLM server didn't open :{LLM_PORT} in 120s")
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{LLM_PORT}/v1/models",
                                        timeout=2) as resp:
                if resp.status == 200:
                    break
        except Exception:
            time.sleep(0.5)
    print(f"[llm-server] ready (pid={proc.pid})", flush=True)
    return proc


def stop_llama_server(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    print(f"\n=== stopping local LLM server (pid={proc.pid}) ===", flush=True)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def run_hermes_agent(prompts: list[str], timeout_s: float = 240.0) -> list[dict[str, Any]]:
    if not HERMES_BIN.exists():
        raise FileNotFoundError("hermes CLI missing — run python_hermes_agent/setup.sh")

    results: list[dict[str, Any]] = []
    for prompt in prompts:
        print(f"\n--- python_hermes_agent :: {prompt!r}", flush=True)
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                [str(HERMES_BIN), "chat", "-Q", "-q", prompt],
                capture_output=True, text=True, timeout=timeout_s,
                cwd=str(PROJECT_ROOT),
            )
            elapsed = time.perf_counter() - t0
            stdout = proc.stdout or ""
            # Strip any leaked Gemma channel markers.
            stdout = re.sub(r"<\|channel>\s*[a-zA-Z_]+\s*", "", stdout)
            stdout = re.sub(r"<\s*/?\s*channel\s*\|?\s*>", "", stdout)
            stdout = re.sub(r"^session_id:.*$", "", stdout, flags=re.MULTILINE)
            text = stdout.strip()
            print(f"  elapsed: {elapsed:.2f}s (exit={proc.returncode})")
            results.append({
                "framework": "python_hermes_agent",
                "prompt": prompt,
                "text": text,
                "tool_activity": [],
                "elapsed_s": elapsed,
                "error": proc.stderr.strip()[:400] if proc.returncode != 0 else None,
            })
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - t0
            print(f"  TIMEOUT after {timeout_s:.0f}s", flush=True)
            results.append({
                "framework": "python_hermes_agent",
                "prompt": prompt, "text": "", "tool_activity": [],
                "elapsed_s": elapsed,
                "error": f"timeout after {timeout_s:.0f}s",
            })
    return results


# ---------------------------------------------------------------------------
# Tool inference from `tool_activity` lines printed by run_command()
# ---------------------------------------------------------------------------
_TOOL_RE = re.compile(r"▸\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\(")


def infer_tool(tool_activity: list[str]) -> str | None:
    for line in tool_activity:
        m = _TOOL_RE.search(line)
        if m:
            return m.group(1)
    return None


def expected_for(framework: str, canonical_tool: str | None) -> str | None:
    """Translate the canonical expected tool name to a framework-specific
    alias. Today only python_jaeger renames anything."""
    if canonical_tool is None:
        return None
    if framework == "python_jaeger":
        return JAEGER_TOOL_ALIASES.get(canonical_tool, canonical_tool)
    return canonical_tool


# ---------------------------------------------------------------------------
# History — append-only JSONL, one row per (framework × prompt × run)
# ---------------------------------------------------------------------------
def append_history(run_id: str, rows_by_fw: dict[str, list[dict[str, Any]]]) -> None:
    with HISTORY_PATH.open("a", encoding="utf-8") as fh:
        for fw, rows in rows_by_fw.items():
            for r in rows:
                fh.write(json.dumps({
                    "run_id": run_id,
                    "mode_tag": "default",
                    "framework": fw,
                    "prompt": r["prompt"],
                    "expected_tool": r.get("expected_tool"),
                    "called_tool": r.get("called_tool"),
                    "total": r["elapsed_s"],
                    "error": r.get("error"),
                    "text": (r.get("text") or "")[:200],
                }) + "\n")


def load_history() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------
def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "—"


def _tool_label(name: str | None) -> str:
    return f"`{name}`" if name else "`(free-text)`"


def _short(prompt: str, n: int = 50) -> str:
    return prompt if len(prompt) <= n else prompt[: n - 3] + "..."


def render_markdown(*, run_id: str,
                    prompts: list[tuple[str, str | None]],
                    frameworks: list[str],
                    latest: dict[str, dict[str, dict[str, Any]]],
                    history: list[dict[str, Any]]) -> str:
    """latest[fw][prompt] = {elapsed_s, text, called_tool, ...}"""

    # ---- Pre-compute best-of-bests per (framework, prompt) ----
    best: dict[str, dict[str, float]] = defaultdict(dict)
    for rec in history:
        fw = rec.get("framework")
        p = rec.get("prompt")
        t = rec.get("total")
        if not fw or not p or t is None:
            continue
        cur = best[fw].get(p)
        if cur is None or t < cur:
            best[fw][p] = t

    # ---- Last 5 distinct run_ids per framework, in insertion order ----
    fw_run_ids: dict[str, list[str]] = defaultdict(list)
    for rec in history:
        fw = rec.get("framework")
        rid = rec.get("run_id")
        if fw and rid and rid not in fw_run_ids[fw]:
            fw_run_ids[fw].append(rid)
    fw_last5: dict[str, list[str]] = {fw: ids[-5:] for fw, ids in fw_run_ids.items()}
    # Per-(framework, prompt, run_id) lookup
    fw_hist: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for rec in history:
        fw = rec.get("framework")
        rid = rec.get("run_id")
        p = rec.get("prompt")
        if not fw or not rid or not p:
            continue
        if rid in fw_last5.get(fw, []):
            fw_hist[fw][p][rid] = rec.get("total", 0.0)

    out: list[str] = []
    out.append("# Benchmark")
    out.append("")
    out.append(f"Last run: `{run_id}` · frameworks: {', '.join(frameworks)}")
    out.append("")
    out.append("Regenerate with `python bench.py`. History: `bench_history.jsonl` "
               "(one row per framework × prompt × run). Raw payload: `bench_results.json`.")
    out.append("")

    # ---- 1. Best record per framework (lowest latency ever) ----
    out.append("## 1. Best record per framework (lowest latency ever)")
    out.append("")
    out.append("Each cell = the fastest result that framework has *ever* achieved on this "
               "prompt across all runs in `bench_history.jsonl`. Useful as a personal best target.")
    out.append("")
    header = "| prompt | tool |" + "".join(f" {fw} best |" for fw in frameworks)
    sep = "|---|---|" + "---:|" * len(frameworks)
    out.append(header)
    out.append(sep)
    totals = {fw: 0.0 for fw in frameworks}
    counts = {fw: 0 for fw in frameworks}
    for prompt, tool in prompts:
        cells = []
        for fw in frameworks:
            v = best[fw].get(prompt)
            if v is not None:
                totals[fw] += v
                counts[fw] += 1
            cells.append(_fmt(v))
        out.append(f"| {_short(prompt)} | {_tool_label(tool)} | " + " | ".join(cells) + " |")
    out.append("| **best-of-bests total** | |" +
               "".join(f" **{totals[fw]:.2f}** |" for fw in frameworks))
    out.append("| **best-of-bests avg** | |" +
               "".join(f" **{(totals[fw] / counts[fw] if counts[fw] else 0):.3f}** |"
                       for fw in frameworks))
    out.append("")

    # ---- 2. Latest run — per-prompt totals ----
    out.append("## 2. Latest run — per-prompt totals")
    out.append("")
    header = "| prompt | tool |" + "".join(f" {fw} |" for fw in frameworks)
    sep = "|---|---|" + "---:|" * len(frameworks)
    out.append(header)
    out.append(sep)
    latest_totals = {fw: 0.0 for fw in frameworks}
    latest_counts = {fw: 0 for fw in frameworks}
    for prompt, tool in prompts:
        cells = []
        for fw in frameworks:
            row = latest.get(fw, {}).get(prompt)
            t = row.get("elapsed_s") if row else None
            if t is not None:
                latest_totals[fw] += t
                latest_counts[fw] += 1
            cells.append(_fmt(t))
        out.append(f"| {_short(prompt)} | {_tool_label(tool)} | " + " | ".join(cells) + " |")
    out.append("| **TOTAL** | |" +
               "".join(f" **{latest_totals[fw]:.2f}** |" for fw in frameworks))
    out.append("| **AVG / prompt** | |" +
               "".join(f" **{(latest_totals[fw] / latest_counts[fw] if latest_counts[fw] else 0):.3f}** |"
                       for fw in frameworks))
    out.append("")

    # ---- 3. Per-tool averages (latest run) ----
    out.append("## 3. Per-tool average seconds (latest run)")
    out.append("")
    header = "| tool | n prompts |" + "".join(f" {fw} avg |" for fw in frameworks)
    sep = "|---|---:|" + "---:|" * len(frameworks)
    out.append(header)
    out.append(sep)
    by_tool: dict[str | None, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    counts_by_tool: dict[str | None, int] = defaultdict(int)
    for prompt, tool in prompts:
        counts_by_tool[tool] += 1
        for fw in frameworks:
            row = latest.get(fw, {}).get(prompt)
            t = row.get("elapsed_s") if row else None
            if t is not None:
                by_tool[tool][fw].append(t)
    named = sorted([k for k in by_tool if k is not None])
    for k in named + ([None] if None in by_tool else []):
        cells = []
        for fw in frameworks:
            vals = by_tool[k].get(fw, [])
            cells.append(f"{statistics.fmean(vals):.3f}" if vals else "—")
        out.append(f"| {_tool_label(k)} | {counts_by_tool[k]} | " + " | ".join(cells) + " |")
    out.append("")

    # ---- 4. Per-framework historical trend (last 5 runs) ----
    out.append("## 4. Per-framework historical trend (last 5 runs)")
    out.append("")
    out.append("Each framework's latencies across the most recent runs. Spot regressions and "
               "improvements over time.")
    out.append("")
    for fw in frameworks:
        out.append(f"### {fw}")
        out.append("")
        runs = fw_last5.get(fw, [])
        if not runs:
            out.append("_No history yet._")
            out.append("")
            continue
        header = "| prompt |" + "".join(f" r{i+1} |" for i in range(len(runs)))
        sep = "|---|" + "---:|" * len(runs)
        out.append(header)
        out.append(sep)
        for prompt, _ in prompts:
            cells = [_fmt(fw_hist[fw][prompt].get(rid)) for rid in runs]
            out.append("| " + _short(prompt) + " | " + " | ".join(cells) + " |")
        out.append("")
        out.append("Run IDs: " +
                   ", ".join(f"`r{i+1}`=`{rid}`" for i, rid in enumerate(runs)))
        out.append("")

    # ---- 5. Headlines ----
    out.append("## Headlines")
    out.append("")
    finalists = [(fw, latest_totals[fw], latest_counts[fw])
                 for fw in frameworks if latest_counts[fw]]
    if finalists:
        fastest = min(finalists, key=lambda x: x[1] / x[2])
        slowest = max(finalists, key=lambda x: x[1] / x[2])
        out.append(f"- Latest fastest: **{fastest[0]}** "
                   f"({fastest[1]:.2f}s total, {fastest[1] / fastest[2]:.3f}s avg).")
        out.append(f"- Latest slowest: **{slowest[0]}** "
                   f"({slowest[1]:.2f}s total, {slowest[1] / slowest[2]:.3f}s avg).")
        if fastest[0] != slowest[0]:
            fast_avg = fastest[1] / fastest[2]
            slow_avg = slowest[1] / slowest[2]
            gap_pct = (slow_avg - fast_avg) / fast_avg * 100 if fast_avg else 0
            out.append(f"- Latest gap: {slow_avg - fast_avg:.3f}s/prompt "
                       f"({gap_pct:.1f}% slower).")
        # Best-of-bests winner
        bob = [(fw, totals[fw] / counts[fw]) for fw in frameworks if counts[fw]]
        if bob:
            winner = min(bob, key=lambda x: x[1])
            out.append(f"- Best-record holder (lowest avg across personal bests): "
                       f"**{winner[0]}** ({winner[1]:.3f}s avg).")
    else:
        out.append("- No latest-run data captured.")
    out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--frameworks", default=IN_PROCESS_FRAMEWORKS_DEFAULT,
                   help=f"Comma-separated in-process frameworks (default: {IN_PROCESS_FRAMEWORKS_DEFAULT}).")
    p.add_argument("--skip-hermes-agent", action="store_true",
                   help="Skip the HTTP-based python_hermes_agent run.")
    p.add_argument("--runs", type=int, default=1,
                   help="Repeat each prompt N times within each framework's worker run.")
    p.add_argument("--prompts", type=Path, default=None,
                   help="Custom prompt file (one per line; expected_tool left None).")
    p.add_argument("--timeout", type=float, default=900,
                   help="Per-framework subprocess timeout in seconds (default 900).")
    p.add_argument("--no-history", action="store_true",
                   help="Don't append to bench_history.jsonl.")
    p.add_argument("--no-md", action="store_true",
                   help="Don't regenerate BENCHMARK.md.")
    p.add_argument("--md-out", type=Path, default=MD_OUT)
    p.add_argument("--json-out", type=Path, default=JSON_OUT)
    return p.parse_args()


def main() -> int:
    args = parse_args()

    if args.prompts:
        prompts: list[tuple[str, str | None]] = [
            (line.strip(), None)
            for line in args.prompts.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    else:
        prompts = DEFAULT_PROMPTS
    if not prompts:
        print("no prompts to run", file=sys.stderr)
        return 2

    inprocess = [f.strip() for f in args.frameworks.split(",") if f.strip()]
    frameworks = list(inprocess)
    if not args.skip_hermes_agent:
        frameworks.append("python_hermes_agent")

    run_id = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    print(f"Bench: {len(prompts)} prompt(s) × {args.runs} run(s) "
          f"across {len(frameworks)} framework(s)")
    print(f"  run_id: {run_id}")
    print(f"  frameworks: {', '.join(frameworks)}")

    # Repeat the prompt list `runs` times for each framework
    flat_prompts = [p for _ in range(args.runs) for p, _ in prompts]
    expected_canonical = {p: t for p, t in prompts}

    raw_by_fw: dict[str, list[dict[str, Any]]] = {}
    t0 = time.perf_counter()

    # In-process frameworks via bench_worker.py
    for fw in inprocess:
        rows = run_via_worker(fw, flat_prompts, timeout_s=args.timeout)
        for r in rows:
            canon = expected_canonical.get(r["prompt"])
            r["expected_tool"] = expected_for(fw, canon)
            r["called_tool"] = infer_tool(r.get("tool_activity") or [])
        raw_by_fw[fw] = rows

    # python_hermes_agent over HTTP
    if not args.skip_hermes_agent:
        log_path = PROJECT_ROOT / "logs" / "bench_llm_server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        server = None
        try:
            server = start_llama_server(log_path)
            rows = run_hermes_agent(flat_prompts)
            for r in rows:
                canon = expected_canonical.get(r["prompt"])
                r["expected_tool"] = canon
                r["called_tool"] = None  # hermes-agent CLI doesn't surface tool names
            raw_by_fw["python_hermes_agent"] = rows
        finally:
            stop_llama_server(server)

    wall = time.perf_counter() - t0

    # ---- Collapse repeats: latest[fw][prompt] = aggregated row ----
    latest: dict[str, dict[str, dict[str, Any]]] = {}
    for fw, rows in raw_by_fw.items():
        by_prompt: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            by_prompt[r["prompt"]].append(r)
        merged: dict[str, dict[str, Any]] = {}
        for p, rs in by_prompt.items():
            ok = [r for r in rs if not r.get("error")]
            if not ok:
                merged[p] = rs[-1]
                continue
            mean = statistics.fmean(r["elapsed_s"] for r in ok)
            row = dict(ok[-1])
            row["elapsed_s"] = mean
            row["n_runs"] = len(ok)
            merged[p] = row
        latest[fw] = merged

    # ---- Write JSON ----
    args.json_out.write_text(
        json.dumps({
            "run_id": run_id,
            "wall_clock_s": round(wall, 3),
            "frameworks": frameworks,
            "prompts": [{"prompt": p, "expected_tool": t} for p, t in prompts],
            "runs_per_prompt": args.runs,
            "results": raw_by_fw,
        }, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nWrote {args.json_out.relative_to(ROOT)} ({wall:.1f}s wall).")

    # ---- Append history ----
    if not args.no_history:
        append_history(run_id, raw_by_fw)
        total_rows = sum(len(rs) for rs in raw_by_fw.values())
        print(f"Appended {total_rows} row(s) to {HISTORY_PATH.name}.")

    # ---- Render markdown ----
    if not args.no_md:
        history = load_history()
        md = render_markdown(
            run_id=run_id,
            prompts=prompts,
            frameworks=frameworks,
            latest=latest,
            history=history,
        )
        args.md_out.write_text(md, encoding="utf-8")
        print(f"Wrote {args.md_out.relative_to(ROOT)}.")
        # Print just the headlines to stdout — the full table is in the file.
        for line in md.splitlines():
            if line.startswith("- ") or line.startswith("## Headlines"):
                print(line)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
