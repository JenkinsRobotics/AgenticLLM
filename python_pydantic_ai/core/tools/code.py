"""Code-execution skills.

  • run_python(code, timeout_s) — execute a Python snippet in an isolated
                                  subprocess (fresh interpreter, fresh
                                  tempdir as cwd, capped output, hard
                                  timeout).

Use this for novel logic the existing dedicated tools don't cover:
non-trivial math, data wrangling, regex on a string the user pasted, etc.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from typing import Any


def run_python(code: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """Execute Python code in a fresh, isolated subprocess.

    Sandboxing rules — all enforced by the subprocess boundary, not the
    snippet:
      - Fresh `python` with no inherited site-packages of ours (uses the
        venv's python so common libs are available but no `tools` /
        `python_pydantic_ai` modules leak in).
      - cwd is a fresh tempdir, not the workspace — the snippet cannot
        accidentally clobber the agent's files.
      - 10s timeout by default (the model may pass `timeout_s`).
      - Hard size cap on captured stdout/stderr (200 KB each) so a runaway
        loop can't blow up our log file.

    Returns: {ok, stdout, stderr, exit_code, elapsed_s, timed_out}.
    """
    cleaned = (code or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty code"}

    MAX_CAP = 200_000  # bytes per stream

    started = time.perf_counter()
    timed_out = False
    with tempfile.TemporaryDirectory(prefix="agent_run_python_") as scratch:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", cleaned],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=scratch,
                env={"PATH": os.environ.get("PATH", ""), "HOME": scratch},
            )
            exit_code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = (exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    elapsed = time.perf_counter() - started

    truncated_stdout = stdout[:MAX_CAP]
    truncated_stderr = stderr[:MAX_CAP]
    return {
        "ok": exit_code == 0 and not timed_out,
        "exit_code": exit_code,
        "stdout": truncated_stdout,
        "stderr": truncated_stderr,
        "stdout_truncated": len(stdout) > MAX_CAP,
        "stderr_truncated": len(stderr) > MAX_CAP,
        "elapsed_s": round(elapsed, 3),
        "timed_out": timed_out,
    }
