#!/usr/bin/env python3
"""Head-to-head: python_jaeger vs python_pydantic_ai on the SAME Gemma weights.

We measure decision latency, total turn latency, and pass/fail on whether
each framework picked *some* tool when a tool was expected (we don't pin
exact tool names because the two frameworks have different surfaces; we
just want apples-to-apples performance, not correctness parity).

Run:
  python bench_jaeger.py                     # 7-prompt default set
  python bench_jaeger.py --runs 2            # repeat each prompt N times
  python bench_jaeger.py --only python_jaeger
  python bench_jaeger.py --prompts custom.txt

Each framework loads its model ONCE and runs the prompt list. The model
instance is freed between frameworks (gc + del) so the second framework
doesn't share KV cache state with the first.
"""

from __future__ import annotations

import argparse
import gc
import io
import json
import os
import statistics
import sys
import tempfile
import time
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent           # the benchmark/ dir
PROJECT_ROOT = ROOT.parent                       # repo root; framework dirs live here


# (prompt, expects_tool_call?). True = the framework should route to A tool,
# False = the framework should answer free-text. We don't pin tool names
# because Jaeger and pydantic_ai have intentionally different surfaces
# (file_write vs create_file, etc.) and renaming the tools is the point of
# Jaeger M1's sandbox.
DEFAULT_PROMPTS: list[tuple[str, bool]] = [
    ("what time is it", True),
    ("what time is it in shanghai", True),
    ("calculate 47 times 23 plus 12", True),
    ("what is the cpu and disk status of this machine", True),
    ("remember that my favorite color is teal", True),
    ("what is my favorite color?", True),
    ("tell me a one sentence story about a robot", False),
]


# ---------------------------------------------------------------------------
# Framework runners — each one wraps the framework's existing entry points.
# ---------------------------------------------------------------------------
def run_pydantic_ai(prompts: list[tuple[str, bool]], runs: int) -> list[dict[str, Any]]:
    from python_pydantic_ai.main import (
        LlamaCppPythonClient,
        init_from_env,
        run_command,
        shutdown_extensions,
    )
    from python_pydantic_ai.tools import ensure_workspace

    print("\n=== python_pydantic_ai: loading model ===", flush=True)
    client = LlamaCppPythonClient()
    ensure_workspace()
    init_from_env(client)

    log_path = PROJECT_ROOT / "python_pydantic_ai" / "logs" / "latency.jsonl"
    rows: list[dict[str, Any]] = []
    try:
        for run_idx in range(runs):
            for prompt, expects_tool in prompts:
                rows.append(_time_one_turn(
                    framework="python_pydantic_ai",
                    prompt=prompt,
                    expects_tool=expects_tool,
                    call=lambda: run_command(client, prompt, "auto"),
                    log_path=log_path,
                    run_idx=run_idx,
                ))
    finally:
        shutdown_extensions(wait=True)
        try:
            del client
        except UnboundLocalError:
            pass
        gc.collect()
    return rows


def run_jaeger(prompts: list[tuple[str, bool]], runs: int, instance_dir: Path) -> list[dict[str, Any]]:
    # Stage a throwaway instance dir so the benchmark doesn't disturb a
    # real one. The wizard isn't used — we write the three files directly
    # because we already know the answers.
    from python_jaeger.instance import InstanceLayout
    from python_jaeger.main import (
        LlamaCppPythonClient,
        _get_agent,
        _pipeline,
        run_command,
    )
    from python_jaeger.prompts import build_system_prompt
    from python_jaeger.schemas import (
        CORE_VERSION,
        Config,
        DisplayConfig,
        Identity,
        Manifest,
        ModelConfig,
        SkillsConfig,
        dump_json,
        dump_yaml,
        load_yaml,
    )
    from python_jaeger import tools as jaeger_tools

    layout = InstanceLayout(root=instance_dir)
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, Identity(
        name="BenchBot", role="benchmark target", personality="Concise. Bare facts."
    ))
    cfg = Config(
        instance_name="bench",
        model=ModelConfig(
            model_path=Path(
                "/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/"
                "gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf"
            )
        ),
        display=DisplayConfig(show_latency=False, show_tool_activity=False, show_help_on_start=False),
        skills=SkillsConfig(run_smoke_tests=False),  # don't slow startup
    )
    dump_yaml(layout.config_path, cfg)
    dump_json(layout.manifest_path, Manifest(instance_name="bench", core_version=CORE_VERSION))

    print("\n=== python_jaeger: loading model ===", flush=True)
    jaeger_tools.bind(layout)
    _pipeline["layout"] = layout
    _pipeline["config"] = load_yaml(layout.config_path, Config)
    _pipeline["system_prompt"] = build_system_prompt(layout)
    _pipeline["show_latency"] = False
    _pipeline["show_tool_activity"] = False
    _pipeline["show_help_on_start"] = False

    client = LlamaCppPythonClient(cfg.model, warmup=True)
    _get_agent(client)  # force agent + skill load now

    log_path = layout.latency_log_path
    rows: list[dict[str, Any]] = []
    try:
        for run_idx in range(runs):
            for prompt, expects_tool in prompts:
                rows.append(_time_one_turn(
                    framework="python_jaeger",
                    prompt=prompt,
                    expects_tool=expects_tool,
                    call=lambda: run_command(client, prompt),
                    log_path=log_path,
                    run_idx=run_idx,
                ))
    finally:
        try:
            del client
        except UnboundLocalError:
            pass
        gc.collect()
    return rows


# ---------------------------------------------------------------------------
# Per-turn timing + log scrape
# ---------------------------------------------------------------------------
def _time_one_turn(*, framework: str, prompt: str, expects_tool: bool,
                   call, log_path: Path, run_idx: int) -> dict[str, Any]:
    short = prompt if len(prompt) <= 60 else prompt[:57] + "..."
    print(f"--- {framework}[{run_idx}] :: {short!r}", flush=True)
    captured = io.StringIO()
    started = time.perf_counter()
    with redirect_stdout(captured):
        call()
    elapsed = time.perf_counter() - started
    last = _tail_log(log_path) or {}

    decision = (last.get("decision") or {}) if isinstance(last.get("decision"), dict) else {}
    chose_tool = bool(decision.get("tool"))
    matched = (chose_tool == expects_tool)
    lat = last.get("latency") or {}
    print(f"    elapsed={elapsed:.2f}s  tool={decision.get('tool') or '-'}  "
          f"expects_tool={expects_tool}  ok={matched}", flush=True)
    return {
        "framework": framework,
        "run_idx": run_idx,
        "prompt": prompt,
        "expects_tool": expects_tool,
        "chose_tool": chose_tool,
        "tool_name": decision.get("tool"),
        "match": matched,
        "elapsed_s": round(elapsed, 4),
        "decision_s": float(lat.get("decision", 0.0)),
        "tool_s": float(lat.get("tool", 0.0)),
        "final_s": float(lat.get("final", 0.0)),
        "skipped_final": bool(last.get("skipped_final")),
    }


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
        return json.loads(data.rstrip().rsplit("\n", 1)[-1])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_fw: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_fw.setdefault(r["framework"], []).append(r)

    summary: dict[str, Any] = {}
    for fw, recs in by_fw.items():
        elapsed = [r["elapsed_s"] for r in recs]
        decision = [r["decision_s"] for r in recs if r["decision_s"] > 0]
        passed = sum(1 for r in recs if r["match"])
        skipped = sum(1 for r in recs if r["skipped_final"])
        summary[fw] = {
            "turns": len(recs),
            "elapsed_median_s": round(statistics.median(elapsed), 3) if elapsed else None,
            "elapsed_mean_s":   round(statistics.fmean(elapsed), 3) if elapsed else None,
            "elapsed_min_s":    round(min(elapsed), 3) if elapsed else None,
            "elapsed_max_s":    round(max(elapsed), 3) if elapsed else None,
            "decision_median_s": round(statistics.median(decision), 3) if decision else None,
            "skip_final_count": skipped,
            "passed_routing":   passed,
        }
    return summary


def print_table(rows: list[dict[str, Any]]) -> None:
    by_prompt: dict[str, dict[str, dict[str, Any]]] = {}
    for r in rows:
        by_prompt.setdefault(r["prompt"], {})[r["framework"]] = r
    print()
    print(f"{'prompt':<60}  {'pydantic_ai':>14}  {'jaeger':>14}  {'Δ%':>7}")
    print("-" * 102)
    for prompt, fws in by_prompt.items():
        p = fws.get("python_pydantic_ai", {})
        j = fws.get("python_jaeger", {})
        p_e = p.get("elapsed_s")
        j_e = j.get("elapsed_s")
        delta = ""
        if p_e and j_e:
            pct = (j_e - p_e) / p_e * 100
            delta = f"{pct:+.1f}"
        short = prompt if len(prompt) <= 58 else prompt[:55] + "..."
        print(f"{short:<60}  {(f'{p_e:.2f}s' if p_e else '—'):>14}  "
              f"{(f'{j_e:.2f}s' if j_e else '—'):>14}  {delta:>7}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--only", choices=("python_jaeger", "python_pydantic_ai"), default=None)
    p.add_argument("--runs", type=int, default=1, help="Repeat each prompt N times (default 1).")
    p.add_argument("--prompts", type=Path, default=None,
                   help="Optional file with one prompt per line (assumes expects_tool=True).")
    p.add_argument("--instance-dir", type=Path, default=None,
                   help="Use this Jaeger instance dir instead of a temp one.")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    prompts: list[tuple[str, bool]]
    if args.prompts:
        prompts = [(line.strip(), True) for line in args.prompts.read_text().splitlines() if line.strip()]
    else:
        prompts = DEFAULT_PROMPTS
    print(f"Bench: {len(prompts)} prompt(s) × {args.runs} run(s) per framework.")

    all_rows: list[dict[str, Any]] = []
    instance_dir: Path | None = None

    if args.only in (None, "python_pydantic_ai"):
        all_rows.extend(run_pydantic_ai(prompts, args.runs))

    if args.only in (None, "python_jaeger"):
        instance_dir = args.instance_dir
        cleanup = False
        if instance_dir is None:
            tmp = Path(tempfile.mkdtemp(prefix="jaeger_bench_"))
            instance_dir = tmp / "instance"
            cleanup = True
        try:
            os.environ["JAEGER_INSTANCE_DIR"] = str(instance_dir)
            all_rows.extend(run_jaeger(prompts, args.runs, instance_dir))
        finally:
            if cleanup:
                import shutil
                shutil.rmtree(instance_dir.parent, ignore_errors=True)

    summary = summarize(all_rows)
    print("\n=== summary ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.only is None:
        print_table(all_rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
