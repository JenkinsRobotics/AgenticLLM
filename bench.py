#!/usr/bin/env python3
"""Head-to-head benchmark: Pygentic vs Hermes on the same prompt set.

Loads each framework's model ONCE and runs the full prompt list against it,
then writes a side-by-side comparison table. Each framework's per-prompt
latency entries also land in its own logs/latency.jsonl (tagged with the
framework name), so historical runs accumulate for later analysis.

Run:
  python bench.py                       # both frameworks, default prompts
  python bench.py --only pygentic       # just one
  python bench.py --prompts file.txt    # custom prompt list (one per line)
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any


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

    # YouTube robot-content workflow — exercises research, scripting, TTS narration
    "search the web for trending youtube topics about home robots",
    "write a 4 sentence youtube intro script about a robot named Lilith discovering coffee and save it to youtube_intro.txt",
    "append a closing line to youtube_intro.txt asking viewers to subscribe",
    "narrate youtube_intro.txt out loud as if you are reading it for a youtube video",
    "come up with a catchy youtube title for a video about a robot vacuum gone rogue",
    "delete youtube_intro.txt",
]


def run_framework(name: str, prompts: list[str]) -> list[dict[str, Any]]:
    """Import the framework's agent, load its model once, run all prompts."""
    if name == "pygentic":
        from pygentic.llm_client import LlamaCppPythonClient
        from pygentic.main import run_command
        from pygentic.tools import ensure_workspace
    elif name == "hermes":
        from hermes.llm_client import LlamaCppPythonClient
        from hermes.main import run_command
        from hermes.tools import ensure_workspace
    else:
        raise ValueError(f"unknown framework: {name}")

    print(f"\n=== {name}: loading model ===", flush=True)
    client = LlamaCppPythonClient()
    ensure_workspace()

    results: list[dict[str, Any]] = []
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

    return results


def latency_from_log(framework: str, prompts: list[str]) -> dict[str, dict[str, float]]:
    """Read the latest matching log entry per prompt from the framework's jsonl."""
    log_path = Path(__file__).resolve().parent / framework / "logs" / "latency.jsonl"
    by_prompt: dict[str, dict[str, float]] = {}
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
            if user in prompts:
                by_prompt[user] = entry.get("latency", {})
    return by_prompt


def print_comparison(prompts: list[str], chosen: list[str]) -> None:
    rows = []
    logs = {fw: latency_from_log(fw, prompts) for fw in chosen}
    for prompt in prompts:
        row: dict[str, Any] = {"prompt": prompt}
        for fw in chosen:
            stats = logs.get(fw, {}).get(prompt, {})
            row[f"{fw}_total"] = stats.get("total")
            row[f"{fw}_decision_ttft"] = stats.get("decision_ttft")
        rows.append(row)

    header_parts = ["prompt".ljust(48)]
    for fw in chosen:
        header_parts.append(f"{fw} total".rjust(12))
        header_parts.append(f"{fw} ttft".rjust(10))
    print("\n" + " ".join(header_parts))
    print("-" * len(" ".join(header_parts)))
    for row in rows:
        prompt = (row["prompt"][:45] + "...") if len(row["prompt"]) > 48 else row["prompt"]
        parts = [prompt.ljust(48)]
        for fw in chosen:
            total = row.get(f"{fw}_total")
            ttft = row.get(f"{fw}_decision_ttft")
            parts.append(("%.3f" % total if total is not None else "  -").rjust(12))
            parts.append(("%.3f" % ttft if ttft is not None else "  -").rjust(10))
        print(" ".join(parts))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=["pygentic", "hermes"], help="Run just one framework.")
    parser.add_argument("--prompts", type=Path, help="Text file with one prompt per line.")
    parser.add_argument("--skip-run", action="store_true", help="Don't run new prompts; only summarize the existing logs.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prompts = DEFAULT_PROMPTS
    if args.prompts:
        prompts = [
            line.strip()
            for line in args.prompts.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    chosen = [args.only] if args.only else ["pygentic", "hermes"]

    if not args.skip_run:
        for fw in chosen:
            run_framework(fw, prompts)

    print_comparison(prompts, chosen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
