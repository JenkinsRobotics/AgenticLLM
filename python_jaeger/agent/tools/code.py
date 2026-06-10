"""Code-execution skills.

  • run_python(code, timeout_s) — execute a Python snippet in a sandboxed
                                  subprocess (fresh interpreter, fresh
                                  tempdir cwd, capped output, hard timeout)
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

    Sandboxing rules — all enforced by the subprocess boundary:
      - Fresh `python -I` (isolated) with no inherited site-packages.
      - cwd is a fresh tempdir, not the workspace.
      - 10s default timeout (overridable).
      - 200 KB cap on captured stdout/stderr.

    Returns {ok, exit_code, stdout, stderr, elapsed_s, timed_out}.
    """
    cleaned = (code or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty code"}
    MAX = 200_000
    started = time.perf_counter()
    timed_out = False
    with tempfile.TemporaryDirectory(prefix="jaeger_run_") as scratch:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", cleaned],
                capture_output=True, text=True, timeout=timeout_s,
                cwd=scratch,
                env={"PATH": os.environ.get("PATH", ""), "HOME": scratch},
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")) or ""
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")) or ""
    elapsed = time.perf_counter() - started
    return {
        "ok": exit_code == 0 and not timed_out,
        "exit_code": exit_code,
        "stdout": stdout[:MAX],
        "stderr": stderr[:MAX],
        "elapsed_s": round(elapsed, 3),
        "timed_out": timed_out,
    }
