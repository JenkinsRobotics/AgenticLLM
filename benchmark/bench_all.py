#!/usr/bin/env python3
"""Four-way bench: python_custom_json vs python_hermes_xml vs python_pydantic_ai vs python_hermes_agent.

The first three are in-process (we load the Gemma model once per framework,
serially, and call run_for_voice). The fourth runs over HTTP — we start a
local llama_cpp.server, drive hermes-agent via its `hermes chat -Q -q`
CLI, and capture stdout + timing.

We use a curated 5-prompt subset that:
  - exercises a few different tool categories (time, calc, free-text, web, fs)
  - avoids the TTS prompts that have hung the Hermes-XML bench on Metal
  - works on hermes-agent's broader toolset (no expectation of a `get_time`
    tool, just a sensible answer)

Run:
    python bench_all.py
    python bench_all.py --skip-hermes-agent   # 3-way (no HTTP server needed)
    python bench_all.py --prompts file.txt    # custom prompt list

Results land in bench_all_results.json + an at-a-glance markdown table
printed to stdout (and saved to BENCHMARK_4WAY.md).
"""

from __future__ import annotations

import argparse
import gc
import importlib
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent           # the benchmark/ dir
PROJECT_ROOT = ROOT.parent                       # repo root; venv + main.py live here
VENV_PY = PROJECT_ROOT / ".venv" / "bin" / "python"
HERMES_BIN = PROJECT_ROOT / ".venv" / "bin" / "hermes"
LLM_PORT = int(os.environ.get("HERMES_LLM_PORT", "11435"))
LLM_MODEL = os.environ.get(
    "HERMES_LLM_MODEL",
    "/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/"
    "gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf",
)


DEFAULT_PROMPTS: list[str] = [
    "what time is it",
    "calculate 47 times 23 plus 12",
    "tell me a one sentence story about a robot",
    "search the web for recent news about local llms",
    "list files in the workspace directory",
]


# ============================================================================
# In-process framework runner — loads Gemma in-process, runs all prompts,
# tears down. Same pattern bench.py uses for sequential framework runs.
# ============================================================================
def _extract_answer_from_run_command_output(stdout: str) -> tuple[str, list[str]]:
    """Pull the user-visible answer + tool-activity lines out of what
    `run_command` printed. Stops at the 'Latency:' block so we don't
    include the perf table."""
    lines = stdout.splitlines()
    tool_activity: list[str] = []
    answer_lines: list[str] = []
    for line in lines:
        if line.startswith("Latency:"):
            break
        stripped = line.strip()
        if not stripped:
            continue
        # Tool-activity lines from pydantic_ai/hermes use ▸ / 🔊 / 💾 prefixes
        if any(stripped.startswith(p) for p in ("▸", "🔊", "💾", "🗑", "🔍", "🌐", "📱", "📂", "⚠")):
            tool_activity.append(line)
            continue
        answer_lines.append(line)
    return "\n".join(answer_lines).strip(), tool_activity


def run_inprocess(name: str, prompts: list[str]) -> list[dict[str, Any]]:
    main_mod = importlib.import_module(f"{name}.main")
    tools_mod = importlib.import_module(f"{name}.tools")

    print(f"\n=== {name}: loading Gemma in-process ===", flush=True)
    started = time.perf_counter()
    client = main_mod.LlamaCppPythonClient(ctx=4096, warmup=True)
    print(f"[{name}] loaded in {time.perf_counter() - started:.1f}s", flush=True)

    class _Args:
        with_memory = False
        with_mcp = False
        think = False

    main_mod.init_extensions(_Args(), client)
    tools_mod.ensure_workspace()
    # Prewarm so the first prompt isn't penalized by cold KV cache. Only
    # python_pydantic_ai exposes `prewarm`; the other two amortize the
    # cost into their first real turn naturally.
    prewarm_fn = getattr(main_mod, "prewarm", None)
    if prewarm_fn is not None:
        prewarm_fn(client)

    results: list[dict[str, Any]] = []
    try:
        for prompt in prompts:
            print(f"\n--- {name} :: {prompt!r}", flush=True)
            buf = StringIO()
            err_buf = StringIO()
            t0 = time.perf_counter()
            err: str | None = None
            try:
                with redirect_stdout(buf), redirect_stderr(err_buf):
                    main_mod.run_command(client, prompt, "auto")
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
            elapsed = time.perf_counter() - t0
            captured = buf.getvalue()
            text, tool_activity = _extract_answer_from_run_command_output(captured)
            print(f"  text:    {text[:120]!r}")
            for line in tool_activity:
                print(f"  {line.strip()}")
            print(f"  elapsed: {elapsed:.2f}s")
            results.append({
                "framework": name,
                "prompt": prompt,
                "text": text,
                "tool_activity": tool_activity,
                "elapsed_s": elapsed,
                "error": err,
            })
    finally:
        try:
            main_mod.shutdown_extensions(wait=False)
        except Exception:
            pass
        try:
            del client
        except UnboundLocalError:
            pass
        gc.collect()

    return results


# ============================================================================
# HTTP server lifecycle for hermes-agent
# ============================================================================
def wait_for_port(host: str, port: int, timeout_s: float = 60.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def start_llama_server(log_path: Path) -> subprocess.Popen:
    if not Path(LLM_MODEL).exists():
        raise FileNotFoundError(f"model not found: {LLM_MODEL}")
    cmd = [
        str(VENV_PY), "-m", "llama_cpp.server",
        "--model", LLM_MODEL,
        "--host", "127.0.0.1",
        "--port", str(LLM_PORT),
        "--n_ctx", "8192",
        "--n_gpu_layers", "-1",
        "--chat_format", "gemma",
        "--model_alias", "gemma-4-26b-a4b",
    ]
    log_fh = log_path.open("w")
    print(f"\n=== starting local LLM server on :{LLM_PORT} (log: {log_path}) ===", flush=True)
    proc = subprocess.Popen(cmd, stdout=log_fh, stderr=subprocess.STDOUT, cwd=str(PROJECT_ROOT))
    if not wait_for_port("127.0.0.1", LLM_PORT, timeout_s=120.0):
        proc.terminate()
        raise RuntimeError(f"LLM server didn't open :{LLM_PORT} in 120s — see {log_path}")
    # /v1/models is the readiness signal we actually care about
    import urllib.request
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{LLM_PORT}/v1/models", timeout=2) as resp:
                if resp.status == 200:
                    break
        except Exception:
            time.sleep(0.5)
    print(f"[llm-server] ready (pid={proc.pid})", flush=True)
    return proc


def stop_llama_server(proc: subprocess.Popen) -> None:
    if proc is None:
        return
    print(f"\n=== stopping local LLM server (pid={proc.pid}) ===", flush=True)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ============================================================================
# hermes-agent runner — subprocess CLI for each prompt
# ============================================================================
def run_hermes_agent(prompts: list[str], timeout_s: float = 240.0) -> list[dict[str, Any]]:
    if not HERMES_BIN.exists():
        raise FileNotFoundError(f"hermes CLI missing — run python_hermes_agent/setup.sh")

    results: list[dict[str, Any]] = []
    for prompt in prompts:
        print(f"\n--- python_hermes_agent :: {prompt!r}", flush=True)
        t0 = time.perf_counter()
        try:
            proc = subprocess.run(
                [str(HERMES_BIN), "chat", "-Q", "-q", prompt],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=str(PROJECT_ROOT),
            )
            elapsed = time.perf_counter() - t0
            stdout = proc.stdout or ""
            # Strip Gemma's native channel markers if any leaked through.
            import re
            stdout = re.sub(r"<\|channel>\s*[a-zA-Z_]+\s*", "", stdout)
            stdout = re.sub(r"<\s*/?\s*channel\s*\|?\s*>", "", stdout)
            stdout = re.sub(r"^session_id:.*$", "", stdout, flags=re.MULTILINE)
            text = stdout.strip()
            print(f"  text:    {text[:120]!r}")
            print(f"  elapsed: {elapsed:.2f}s  (exit={proc.returncode})")
            results.append({
                "framework": "python_hermes_agent",
                "prompt": prompt,
                "text": text,
                "tool_activity": [],
                "elapsed_s": elapsed,
                "spoke_via_tool": False,
                "exit_code": proc.returncode,
                "error": proc.stderr.strip()[:400] if proc.returncode != 0 else None,
            })
        except subprocess.TimeoutExpired:
            elapsed = time.perf_counter() - t0
            print(f"  TIMEOUT after {timeout_s:.0f}s", flush=True)
            results.append({
                "framework": "python_hermes_agent",
                "prompt": prompt,
                "text": "",
                "tool_activity": [],
                "elapsed_s": elapsed,
                "error": f"timeout after {timeout_s:.0f}s",
            })
    return results


# ============================================================================
# Reporting
# ============================================================================
def short(s: str, n: int = 60) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def render_markdown_table(prompts: list[str], rows_by_fw: dict[str, list[dict[str, Any]]]) -> str:
    frameworks = list(rows_by_fw.keys())
    out: list[str] = []
    out.append("# Four-way agent benchmark")
    out.append("")
    out.append(
        "All four agents driven by the same local Gemma 4 26B-A4B Q4_K_M weights. "
        "The first three load the model in-process; `python_hermes_agent` drives it "
        "over HTTP via `llama_cpp.server`."
    )
    out.append("")
    out.append("## Per-prompt total seconds")
    out.append("")
    header = "| prompt |" + "".join(f" {fw} |" for fw in frameworks)
    sep = "|---|" + "---:|" * len(frameworks)
    out.append(header)
    out.append(sep)
    totals = {fw: 0.0 for fw in frameworks}
    counts = {fw: 0 for fw in frameworks}
    for i, prompt in enumerate(prompts):
        row = [f"| {short(prompt, 56)} |"]
        for fw in frameworks:
            entries = rows_by_fw[fw]
            r = entries[i] if i < len(entries) else None
            if r and r.get("error"):
                row.append(" ERR |")
            elif r is not None:
                t = r.get("elapsed_s")
                if t is not None:
                    totals[fw] += t
                    counts[fw] += 1
                    row.append(f" {t:.2f} |")
                else:
                    row.append(" – |")
            else:
                row.append(" – |")
        out.append("".join(row))
    sum_row = "| **TOTAL** |"
    avg_row = "| **AVG / prompt** |"
    for fw in frameworks:
        sum_row += f" **{totals[fw]:.2f}** |"
        n = counts[fw] or 1
        avg_row += f" **{totals[fw] / n:.2f}** |"
    out.append(sum_row)
    out.append(avg_row)
    out.append("")
    out.append("## Per-prompt answers")
    out.append("")
    for i, prompt in enumerate(prompts):
        out.append(f"### `{prompt}`")
        out.append("")
        out.append("| agent | answer |")
        out.append("|---|---|")
        for fw in frameworks:
            entries = rows_by_fw[fw]
            r = entries[i] if i < len(entries) else None
            ans = short(r.get("text") if r else "", 110) if r else ""
            ans = ans.replace("|", "\\|").replace("\n", " ⏎ ")
            out.append(f"| {fw} | {ans or '–'} |")
        out.append("")
    return "\n".join(out)


# ============================================================================
# Main
# ============================================================================
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--prompts", type=Path, default=None,
                   help="Optional file with one prompt per line; default is the curated 5-prompt subset.")
    p.add_argument("--skip-hermes-agent", action="store_true",
                   help="Skip the HTTP-based hermes-agent run.")
    p.add_argument("--frameworks", default="python_custom_json,python_hermes_xml,python_pydantic_ai",
                   help="Comma-separated list of in-process frameworks to bench.")
    p.add_argument("--out", type=Path, default=ROOT / "BENCHMARK_4WAY.md",
                   help="Where to write the markdown table.")
    p.add_argument("--json-out", type=Path, default=ROOT / "bench_all_results.json",
                   help="Where to write the raw JSON results.")
    args = p.parse_args()

    if args.prompts:
        prompts = [
            line.strip() for line in args.prompts.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    else:
        prompts = DEFAULT_PROMPTS

    print(f"Benchmarking {len(prompts)} prompts across {len(args.frameworks.split(',')) + (0 if args.skip_hermes_agent else 1)} agents.")
    print(f"  prompts: {prompts}")

    rows_by_fw: dict[str, list[dict[str, Any]]] = {}

    for fw in args.frameworks.split(","):
        fw = fw.strip()
        if not fw:
            continue
        rows_by_fw[fw] = run_inprocess(fw, prompts)
        # Aggressively reclaim Metal/KV state before the next framework loads.
        gc.collect()
        time.sleep(0.5)

    if not args.skip_hermes_agent:
        log_path = PROJECT_ROOT / "logs" / "bench_all_llm_server.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        server_proc = None
        try:
            server_proc = start_llama_server(log_path)
            rows_by_fw["python_hermes_agent"] = run_hermes_agent(prompts)
        finally:
            stop_llama_server(server_proc)

    args.json_out.write_text(
        json.dumps({"prompts": prompts, "results": rows_by_fw}, indent=2, default=str),
        encoding="utf-8",
    )
    md = render_markdown_table(prompts, rows_by_fw)
    args.out.write_text(md, encoding="utf-8")

    print("\n" + "=" * 72)
    print(md)
    print("=" * 72)
    print(f"\nWrote {args.out.relative_to(ROOT)} and {args.json_out.relative_to(ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
