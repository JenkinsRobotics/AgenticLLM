"""macOS host control skills (ported from pydantic_ai/skills/files.py).

  • launch_url(url)      — open a URL in the default browser
  • open_file(path)      — open a workspace file in its default macOS app
  • open_app(app_name)   — launch a macOS application by name

`open_file` is sandbox-resolved to <instance>/skills/ (the agent's
writable area) — it can only open files the agent itself has authored
or that already live in skills/.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any

from ._common import SandboxError, _require_layout, _resolve_under


def launch_url(url: str) -> dict[str, Any]:
    """Open a URL in the default web browser (macOS `open`)."""
    clean = url.strip()
    if not (clean.startswith("http://") or clean.startswith("https://")):
        return {"error": "URL must start with http:// or https://", "url": clean}
    if platform.system() != "Darwin":
        return {"error": f"launch_url only supported on macOS (got {platform.system()})", "url": clean}
    try:
        result = subprocess.run(["open", clean], capture_output=True, timeout=5)
        if result.returncode != 0:
            return {"error": result.stderr.decode("utf-8", errors="replace")[:200], "url": clean}
    except Exception as exc:
        return {"error": str(exc), "url": clean}
    return {"opened": True, "url": clean}


def open_file(path: str) -> dict[str, Any]:
    """Open a file from <instance>/skills/ in its default macOS app.

    Sandbox-resolved — can only open files inside the agent's writable
    skills directory.
    """
    layout = _require_layout()
    try:
        target = _resolve_under(layout.skills_dir, path)
    except SandboxError as exc:
        return {"error": str(exc), "path": path}
    if not target.exists():
        return {"error": "file not found", "path": path}
    if platform.system() != "Darwin":
        return {"error": f"open_file only supported on macOS (got {platform.system()})", "path": str(target)}
    try:
        result = subprocess.run(["open", str(target)], capture_output=True, timeout=5)
        if result.returncode != 0:
            return {"error": result.stderr.decode("utf-8", errors="replace")[:200], "path": str(target)}
    except Exception as exc:
        return {"error": str(exc), "path": str(target)}
    return {"opened": True, "path": str(target.relative_to(layout.root))}


def open_app(app_name: str) -> dict[str, Any]:
    """Launch a macOS application by name (e.g. 'Safari', 'Notes')."""
    clean = app_name.strip()
    if not clean:
        return {"error": "empty app name"}
    if platform.system() != "Darwin":
        return {"error": f"open_app only supported on macOS (got {platform.system()})", "app": clean}
    try:
        result = subprocess.run(["open", "-a", clean], capture_output=True, timeout=5)
        if result.returncode != 0:
            return {"error": result.stderr.decode("utf-8", errors="replace")[:200], "app": clean}
    except Exception as exc:
        return {"error": str(exc), "app": clean}
    return {"opened": True, "app": clean}
