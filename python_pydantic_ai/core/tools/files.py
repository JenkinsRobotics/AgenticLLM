"""File + host control skills.

  • create_file / append_file / read_file / delete_file / list_directory
    — sandboxed to <framework>/workspace/
  • launch_url, open_file, open_app
    — macOS-only host control via the `open` command

Destructive ops (delete_file) are approval-gated when
DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1 (voice / production); bench / dev
default skips the gate for speed.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any

from ._common import WORKSPACE, destructive_confirm_required, workspace_path


# ---------------------------------------------------------------------------
# Workspace file ops
# ---------------------------------------------------------------------------
def create_file(path: str, content: str) -> dict[str, Any]:
    target = workspace_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "created": True,
        "path": str(target.relative_to(WORKSPACE)),
        "bytes": len(content.encode("utf-8")),
    }


def append_file(path: str, content: str) -> dict[str, Any]:
    target = workspace_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(content)
    return {
        "appended": True,
        "path": str(target.relative_to(WORKSPACE)),
        "bytes": len(content.encode("utf-8")),
    }


def delete_file(path: str, confirm: bool = False) -> dict[str, Any]:
    """Delete a workspace file.

    When DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1 is set (voice / production mode),
    the first call previews the deletion instead of executing — the agent
    is expected to call `ask_user` to get explicit human authorization
    and then call `delete_file(path, confirm=True)` to commit. When the
    env var is unset (default / bench), `confirm` is ignored.
    """
    target = workspace_path(path)
    if not target.exists():
        return {"deleted": False, "reason": "not found", "path": path}
    if target.is_dir():
        return {"deleted": False, "reason": "is a directory", "path": path}

    if destructive_confirm_required() and not confirm:
        size = target.stat().st_size
        return {
            "deleted": False,
            "preview": True,
            "path": str(target.relative_to(WORKSPACE)),
            "size_bytes": size,
            "hint": "Ask the user to confirm, then call delete_file again with confirm=True.",
        }

    target.unlink()
    return {"deleted": True, "path": str(target.relative_to(WORKSPACE))}


def read_file(path: str) -> dict[str, Any]:
    target = workspace_path(path)
    return {
        "path": str(target.relative_to(WORKSPACE)),
        "content": target.read_text(encoding="utf-8"),
    }


def list_directory(path: str = ".") -> dict[str, Any]:
    target = workspace_path(path)
    if not target.exists():
        raise FileNotFoundError(str(target.relative_to(WORKSPACE)))
    if not target.is_dir():
        raise NotADirectoryError(str(target.relative_to(WORKSPACE)))

    entries = []
    for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        entries.append(
            {
                "name": child.name,
                "type": "directory" if child.is_dir() else "file",
                "bytes": child.stat().st_size if child.is_file() else None,
            }
        )
    return {"path": str(target.relative_to(WORKSPACE)), "entries": entries}


# ---------------------------------------------------------------------------
# macOS host control
# ---------------------------------------------------------------------------
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
    """Open a workspace file in its default macOS app."""
    target = workspace_path(path)
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
    return {"opened": True, "path": str(target.relative_to(WORKSPACE))}


def open_app(app_name: str) -> dict[str, Any]:
    """Launch a macOS application by name (e.g. 'Safari', 'Notes', 'Terminal')."""
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
