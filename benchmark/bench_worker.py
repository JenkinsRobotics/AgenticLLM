#!/usr/bin/env python3
"""Subprocess worker for bench_all.py.

Loads ONE framework, runs a list of prompts, prints a single JSON object
to stdout, exits. Running each framework in its own subprocess gives it
a fresh Metal context — back-to-back loads in a single process leak
KV cache state into the next framework and trip `llama_decode -3` errors.

Invocation:
    python bench_worker.py <framework_name>
    (prompts read from stdin, one per line)

Output (stdout):
    {"framework": "...", "results": [{...}, ...]}

Errors:
    Anything written to stderr; non-zero exit on hard load failure.
"""

from __future__ import annotations

import gc
import importlib
import json
import os
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _extract_answer(stdout: str) -> tuple[str, list[str]]:
    """Pull the user-visible answer + tool-activity lines out of what
    `run_command` printed. Stops at the 'Latency:' block."""
    tool_activity: list[str] = []
    answer_lines: list[str] = []
    for line in stdout.splitlines():
        if line.startswith("Latency:"):
            break
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in ("▸", "🔊", "💾", "🗑", "🔍", "🌐", "📱", "📂", "⚠")):
            tool_activity.append(line)
            continue
        answer_lines.append(line)
    return "\n".join(answer_lines).strip(), tool_activity


def run_standard_framework(name: str, prompts: list[str]) -> list[dict[str, Any]]:
    """Driver for python_custom_json, python_hermes_xml, python_pydantic_ai —
    all expose the same init_extensions / run_command / shutdown_extensions
    surface."""
    main_mod = importlib.import_module(f"{name}.main")
    tools_mod = importlib.import_module(f"{name}.tools")

    print(f"[{name}] loading Gemma in-process...", file=sys.stderr, flush=True)
    started = time.perf_counter()
    client = main_mod.LlamaCppPythonClient(ctx=4096, warmup=True)
    print(f"[{name}] loaded in {time.perf_counter() - started:.1f}s", file=sys.stderr, flush=True)

    class _Args:
        with_memory = False
        with_mcp = False
        think = False
    main_mod.init_extensions(_Args(), client)
    tools_mod.ensure_workspace()

    prewarm_fn = getattr(main_mod, "prewarm", None)
    if prewarm_fn is not None:
        prewarm_fn(client)

    results: list[dict[str, Any]] = []
    for prompt in prompts:
        print(f"[{name}] :: {prompt!r}", file=sys.stderr, flush=True)
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
        text, tool_activity = _extract_answer(buf.getvalue())
        results.append({
            "framework": name,
            "prompt": prompt,
            "text": text,
            "tool_activity": tool_activity,
            "elapsed_s": elapsed,
            "error": err,
        })
    try:
        main_mod.shutdown_extensions(wait=False)
    except Exception:
        pass
    return results


def run_jaeger(prompts: list[str]) -> list[dict[str, Any]]:
    """Driver for python_jaeger — needs an ephemeral instance dir staged
    before model load (identity.yaml + config.yaml + manifest.json)."""
    import tempfile, shutil
    from python_jaeger.core.instance import InstanceLayout
    from python_jaeger.main import LlamaCppPythonClient, _get_agent, _pipeline, prewarm, run_command
    from python_jaeger.core.prompts import build_system_prompt
    from python_jaeger.core.schemas import (
        Config, DisplayConfig, Identity, Manifest, ModelConfig, SkillsConfig,
        dump_json, dump_yaml, load_yaml,
    )
    from python_jaeger.core import tools as jaeger_tools

    from model_resolver import resolve_model_path
    LLM_MODEL = str(resolve_model_path())

    tmp = Path(tempfile.mkdtemp(prefix="jaeger_bench_"))
    root = tmp / "instance"
    os.environ["JAEGER_INSTANCE_DIR"] = str(root)

    layout = InstanceLayout(root=root)
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, Identity(
        name="BenchBot", role="benchmark target",
        personality=(
            "Concise and direct. When the user asks you to save preferences, "
            "call remember proactively. When asked about prior preferences, "
            "call recall or list_facts first."
        ),
    ))
    dump_yaml(layout.config_path, Config(
        instance_name="bench",
        # Jaeger's system prompt (identity + v2 contract + tool schemas) runs
        # ~4-5K tokens, so 4096 would overflow. 8192 leaves room for prompts.
        model=ModelConfig(model_path=Path(LLM_MODEL), ctx=8192),
        display=DisplayConfig(show_latency=False, show_tool_activity=True, show_help_on_start=False),
        skills=SkillsConfig(run_smoke_tests=False),
    ))
    dump_json(layout.manifest_path, Manifest(instance_name="bench"))

    print(f"[python_jaeger] loading Gemma in-process (instance: {root})", file=sys.stderr, flush=True)
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
    prewarm(client)
    print(f"[python_jaeger] loaded in {time.perf_counter() - started:.1f}s", file=sys.stderr, flush=True)

    results: list[dict[str, Any]] = []
    try:
        for prompt in prompts:
            print(f"[python_jaeger] :: {prompt!r}", file=sys.stderr, flush=True)
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
            text, tool_activity = _extract_answer(buf.getvalue())
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


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: bench_worker.py <framework_name>", file=sys.stderr)
        return 2
    name = sys.argv[1]
    prompts = [line.strip() for line in sys.stdin if line.strip()]
    if not prompts:
        print("no prompts provided on stdin", file=sys.stderr)
        return 2

    if name == "python_jaeger":
        results = run_jaeger(prompts)
    elif name in ("python_custom_json", "python_hermes_xml", "python_pydantic_ai"):
        results = run_standard_framework(name, prompts)
    else:
        print(f"unknown framework: {name}", file=sys.stderr)
        return 2

    print(json.dumps({"framework": name, "results": results}, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
