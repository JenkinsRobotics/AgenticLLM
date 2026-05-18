#!/usr/bin/env python3
"""Five-way bench: python_custom_json, python_hermes_xml, python_pydantic_ai,
python_jaeger, python_hermes_agent.

The first four are in-process (we load the Gemma model once per framework,
serially, and call run_command). The fifth runs over HTTP — we start a
local llama_cpp.server, drive hermes-agent via its `hermes chat -Q -q`
CLI, and capture stdout + timing.

Jaeger has a different startup path than the other three in-process
frameworks (it needs an instance dir with identity.yaml + config.yaml +
manifest.json staged before model load); we handle that in
`run_jaeger_inprocess`, which uses an ephemeral instance under /tmp.

We use a curated 5-prompt subset that:
  - exercises a few different tool categories (time, calc, free-text, web, fs)
  - avoids the TTS prompts that have hung the Hermes-XML bench on Metal
  - works on hermes-agent's broader toolset (no expectation of a `get_time`
    tool, just a sensible answer)

Run:
    python bench_all.py
    python bench_all.py --skip-hermes-agent   # 4-way in-process only
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
# Make sibling framework packages importable regardless of cwd.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
VENV_PY = PROJECT_ROOT / ".venv" / "bin" / "python"
HERMES_BIN = PROJECT_ROOT / ".venv" / "bin" / "hermes"
LLM_PORT = int(os.environ.get("HERMES_LLM_PORT", "11435"))
from model_resolver import resolve_model_path
LLM_MODEL = str(resolve_model_path())


DEFAULT_PROMPTS: list[str] = [
    # Skip-final candidates (tool-result-is-the-answer) — these should hit
    # python_pydantic_ai's intercept path for sub-second turns.
    "what time is it",
    "what time is it in Tokyo",
    "calculate 47 times 23 plus 12",
    "calculate the square root of 12345",
    "what is the cpu and disk status of this machine",

    # Free-text (no tool needed) — exercises the model's direct response path.
    "tell me a one sentence story about a robot",
    "in three words, what is the capital of France",

    # Web tools — exercises external IO + a longer tool call.
    "search the web for recent news about local llms",
    "what is the current weather in Seattle",

    # Memory ops — only meaningful for the in-process frameworks.
    "remember that my favorite color is teal",
    "what is my favorite color",

    # File / workspace inspection — different tool surfaces across frameworks
    # but all should produce SOMETHING (each has its own equivalent).
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
# Jaeger in-process runner — same idea as run_inprocess but with the extra
# instance-dir setup the v2 framework requires (identity.yaml + config.yaml
# + manifest.json must exist before model load, no project-root memory dir
# to fall back on).
# ============================================================================
def run_jaeger_inprocess(prompts: list[str]) -> list[dict[str, Any]]:
    import tempfile, shutil
    from python_jaeger.core.instance import InstanceLayout
    from python_jaeger.main import LlamaCppPythonClient, _get_agent, _pipeline, prewarm, run_command
    from python_jaeger.core.prompts import build_system_prompt
    from python_jaeger.core.schemas import (
        Config, DisplayConfig, Identity, Manifest, ModelConfig, SkillsConfig,
        dump_json, dump_yaml, load_yaml,
    )
    from python_jaeger.core import tools as jaeger_tools

    tmp = Path(tempfile.mkdtemp(prefix="jaeger_bench_"))
    root = tmp / "instance"
    os.environ["JAEGER_INSTANCE_DIR"] = str(root)

    layout = InstanceLayout(root=root)
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, Identity(
        name="BenchBot",
        role="benchmark target",
        personality=(
            "Concise and direct. When the user asks you to save preferences, "
            "call remember proactively. When asked about prior preferences, "
            "call recall or list_facts first."
        ),
    ))
    dump_yaml(layout.config_path, Config(
        instance_name="bench",
        model=ModelConfig(model_path=Path(LLM_MODEL), ctx=4096),
        display=DisplayConfig(show_latency=False, show_tool_activity=True, show_help_on_start=False),
        skills=SkillsConfig(run_smoke_tests=False),
    ))
    dump_json(layout.manifest_path, Manifest(instance_name="bench"))

    print(f"\n=== python_jaeger: loading Gemma in-process (instance: {root}) ===", flush=True)
    started = time.perf_counter()
    jaeger_tools.bind(layout)
    _pipeline["layout"] = layout
    _pipeline["config"] = load_yaml(layout.config_path, Config)
    _pipeline["system_prompt"] = build_system_prompt(layout)
    _pipeline["show_latency"] = False
    _pipeline["show_tool_activity"] = True
    _pipeline["show_help_on_start"] = False
    client = LlamaCppPythonClient(_pipeline["config"].model, warmup=True)
    _get_agent(client)
    # Pre-pay the system-prompt + tool-schema prefill so the first
    # user-facing turn isn't cold (parity with python_pydantic_ai).
    prewarm(client)
    print(f"[python_jaeger] loaded in {time.perf_counter() - started:.1f}s", flush=True)

    results: list[dict[str, Any]] = []
    try:
        for prompt in prompts:
            print(f"\n--- python_jaeger :: {prompt!r}", flush=True)
            buf = StringIO()
            err_buf = StringIO()
            t0 = time.perf_counter()
            err: str | None = None
            try:
                with redirect_stdout(buf), redirect_stderr(err_buf):
                    run_command(client, prompt)
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
                "framework": "python_jaeger",
                "prompt": prompt,
                "text": text,
                "tool_activity": tool_activity,
                "elapsed_s": elapsed,
                "error": err,
            })
    finally:
        try:
            del client
        except UnboundLocalError:
            pass
        gc.collect()
        shutil.rmtree(tmp, ignore_errors=True)

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
        # hermes-agent's built-in system prompt + tool schema runs ~12-14K
        # tokens before the user prompt is even appended. 8192 caused
        # "Requested tokens (14144) exceed context window" on every turn;
        # 32768 leaves plenty of headroom on Gemma 4 (trained on 262K).
        "--n_ctx", "32768",
        "--n_gpu_layers", "-1",
        # Intentionally NO --chat_format: the hardcoded "gemma" template
        # is for Gemma 1/2 and leaks <|channel>thought\n… markers on
        # Gemma 4. Letting llama-cpp-python read the GGUF's embedded
        # chat template gives clean output for the Gemma 4 series.
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
    out.append("# Five-way agent benchmark")
    out.append("")
    out.append(
        "All agents driven by the same local Gemma 4 26B-A4B Q4_K_M weights. "
        "The in-process frameworks (`python_custom_json`, `python_hermes_xml`, "
        "`python_pydantic_ai`, `python_jaeger`) load the model directly; "
        "`python_hermes_agent` drives it over HTTP via `llama_cpp.server`."
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
    # Order matters: each framework load/teardown leaves residue in the Metal
    # KV cache that can corrupt subsequent llama_decode calls (we've reproduced
    # `llama_decode returned -3` mid-session in the framework loaded LAST when
    # 3+ frameworks ran before it). Putting `python_jaeger` first gives it a
    # clean Metal context; pydantic_ai is the most robust at recovery, so it
    # goes last among the in-process group.
    p.add_argument("--frameworks",
                   default="python_jaeger,python_custom_json,python_hermes_xml,python_pydantic_ai",
                   help="Comma-separated list of in-process frameworks to bench.")
    p.add_argument("--out", type=Path, default=ROOT / "BENCHMARK_5WAY.md",
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

    worker = ROOT / "bench_worker.py"
    for fw in args.frameworks.split(","):
        fw = fw.strip()
        if not fw:
            continue
        # Subprocess isolation: each framework gets a fresh Python process
        # and therefore a fresh Metal context. Single-process back-to-back
        # loads on Apple Silicon leak KV state across frameworks and trip
        # `llama_decode returned -3` mid-bench.
        print(f"\n=== {fw} (subprocess) ===", flush=True)
        prompts_blob = "\n".join(prompts)
        try:
            proc = subprocess.run(
                [sys.executable, str(worker), fw],
                input=prompts_blob, capture_output=True, text=True,
                timeout=900,
            )
        except subprocess.TimeoutExpired:
            print(f"[{fw}] TIMEOUT (15min)", flush=True)
            rows_by_fw[fw] = [{"framework": fw, "prompt": p, "text": "",
                               "tool_activity": [], "elapsed_s": 0.0,
                               "error": "subprocess timeout"} for p in prompts]
            continue
        # Worker prints framework status to stderr (live), JSON to stdout.
        # llama-cpp-python on Apple Metal often raises a non-zero exit from
        # an atexit teardown assert AFTER the worker has finished cleanly,
        # so we try to parse the JSON FIRST and only fall back to ERR if
        # the JSON itself is missing or malformed.
        if proc.stderr:
            print(proc.stderr, flush=True)
        try:
            # Find the JSON payload — it's the last non-empty line of stdout
            # (some shutdown noise can appear after it on some systems).
            json_line = ""
            for line in (proc.stdout or "").splitlines():
                if line.strip().startswith("{"):
                    json_line = line.strip()
            payload = json.loads(json_line) if json_line else {}
        except json.JSONDecodeError as exc:
            print(f"[{fw}] worker stdout not JSON: {exc}", flush=True)
            print(proc.stdout[-2000:], flush=True)
            payload = {}

        if payload.get("results"):
            rows_by_fw[fw] = payload["results"]
            if proc.returncode != 0:
                print(f"[{fw}] worker exited {proc.returncode} after producing "
                      "valid JSON (likely Metal atexit assert — harmless)",
                      flush=True)
        else:
            print(f"[{fw}] worker failed (exit {proc.returncode}); stderr tail:",
                  flush=True)
            print(proc.stderr[-2000:], flush=True)
            rows_by_fw[fw] = [{"framework": fw, "prompt": p, "text": "",
                               "tool_activity": [], "elapsed_s": 0.0,
                               "error": f"worker exit {proc.returncode}, no JSON"}
                              for p in prompts]

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
