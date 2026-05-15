#!/usr/bin/env python3
"""Bench-style one-shot wrapper for NousResearch/hermes-agent.

Invokes `hermes chat -Q -q <prompt>` as a subprocess against the local
llama-cpp-python OpenAI-compatible server (started by ./start_llm.sh) and
returns a dict with the same shape our other frameworks' `run_for_voice`
produces, so the four agents can be compared in the same harness:

    {
        "text": "<final answer>",
        "elapsed_s": <float>,
        "session_id": "<hermes session id>",
        "raw_stdout": "<full captured output>",
    }

The hermes CLI is interactive by design (TUI, slash commands, REPL). The
`-Q -q` flags put it in "quiet single-shot" mode where it prints only the
session id and the final response, then exits.

Usage:
    python python_hermes_agent/run_prompt.py "what time is it"
    python python_hermes_agent/run_prompt.py --toolsets web,terminal "calculate 47 times 23 plus 12"
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
HERMES_BIN = PROJECT_ROOT / ".venv" / "bin" / "hermes"


def run_prompt(
    prompt: str,
    *,
    toolsets: str | None = None,
    timeout_s: float = 300.0,
) -> dict[str, Any]:
    """Drive a single hermes-agent turn and return its result as a dict."""
    if not HERMES_BIN.exists():
        return {
            "text": "",
            "error": f"hermes binary not found at {HERMES_BIN}. Run ./setup.sh first.",
            "elapsed_s": 0.0,
        }

    cmd = [str(HERMES_BIN), "chat", "-Q", "-q", prompt]
    if toolsets:
        cmd.extend(["-t", toolsets])

    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        return {
            "text": "",
            "error": f"hermes-agent timed out after {timeout_s}s",
            "elapsed_s": time.perf_counter() - started,
        }
    elapsed = time.perf_counter() - started

    raw = (proc.stdout or "") + (proc.stderr or "")
    text, session_id = _parse_quiet_output(proc.stdout or "")

    return {
        "text": text,
        "elapsed_s": elapsed,
        "session_id": session_id,
        "exit_code": proc.returncode,
        "raw_stdout": proc.stdout,
        "raw_stderr": proc.stderr,
    }


_SESSION_RE = re.compile(r"^session_id:\s*(\S+)\s*$", re.MULTILINE)
# Gemma's native channel markers can land on separate lines. Strip
# `<|channel>NAME` (opening + label), `<channel|>` (closer), and
# `<|/channel>` (alt closer) so the returned `text` is plain content.
_CHANNEL_OPEN = re.compile(r"<\|channel>\s*[a-zA-Z_]+\s*", re.IGNORECASE)
_CHANNEL_CLOSE = re.compile(r"<\s*/?\s*channel\s*\|?\s*>", re.IGNORECASE)


def _parse_quiet_output(stdout: str) -> tuple[str, str | None]:
    """Pull the session id (printed by `-Q`) off the top, return the rest as the answer."""
    session_id: str | None = None
    m = _SESSION_RE.search(stdout)
    if m:
        session_id = m.group(1)
        stdout = stdout[: m.start()] + stdout[m.end() :]
    cleaned = _CHANNEL_OPEN.sub("", stdout)
    cleaned = _CHANNEL_CLOSE.sub("", cleaned).strip()
    return cleaned, session_id


def _cli() -> int:
    p = argparse.ArgumentParser(description="Single-prompt wrapper for hermes-agent.")
    p.add_argument("prompt", help="The user prompt to send to hermes-agent.")
    p.add_argument(
        "--toolsets",
        "-t",
        default=None,
        help="Comma-separated toolsets to enable (default: hermes-agent's enabled set).",
    )
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--json", action="store_true", help="Print full result dict as JSON.")
    args = p.parse_args()

    result = run_prompt(args.prompt, toolsets=args.toolsets, timeout_s=args.timeout)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        if result.get("error"):
            print(f"[error] {result['error']}", file=sys.stderr)
            return 1
        print(result["text"])
        print(
            f"\n[hermes-agent] elapsed: {result['elapsed_s']:.2f}s  "
            f"session: {result.get('session_id', '?')}"
        )
    return 0 if result.get("exit_code", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_cli())
