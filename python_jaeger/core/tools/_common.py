"""Shared infrastructure for every Jaeger tool module.

Anything used by 2+ tool files lives here:
  • Module-level binding to the active InstanceLayout
  • Sandboxed path resolver (instance/skills/ scope enforcement)
  • Audit logger (logs/audit.log)
  • Git auto-commit helper for file_write

Each tool category file does `from ._common import _audit, ...` rather
than reaching back into the rest of the framework directly. Keeps
category files focused on their tools, free of cross-skill plumbing.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..instance import InstanceLayout


# ---------------------------------------------------------------------------
# Module-level binding: which instance does this process serve?
# ---------------------------------------------------------------------------
_layout: InstanceLayout | None = None


def bind(layout: InstanceLayout) -> None:
    """Wire all tool I/O to a specific instance dir. Called once at startup."""
    from .. import memory as mem
    global _layout
    _layout = layout
    mem.bind(layout)


def _require_layout() -> InstanceLayout:
    if _layout is None:
        raise RuntimeError("tools not bound — call python_jaeger.core.tools.bind(layout) first")
    return _layout


def get_layout() -> InstanceLayout:
    """Public accessor for tool files that need the active layout."""
    return _require_layout()


# ---------------------------------------------------------------------------
# Audit log — every sandbox-relevant operation gets recorded
# ---------------------------------------------------------------------------
def _audit(event: str, payload: dict[str, Any]) -> None:
    layout = _require_layout()
    layout.logs_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        **payload,
    }
    with layout.audit_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True, default=str) + "\n")


# ---------------------------------------------------------------------------
# Sandboxed path resolver (used by file_write / file_read / list_skill_dir)
# ---------------------------------------------------------------------------
class SandboxError(ValueError):
    """Raised when a path argument escapes the allowed zone."""


def _resolve_under(root: Path, path: str) -> Path:
    """Resolve `path` relative to `root` and verify the result lives inside
    `root`. Rejects absolute paths, `..` escapes, and symlinks that point
    outside the sandbox.

    Strips a leading `<root.name>/` prefix to make agent-supplied paths
    idempotent — Gemma 4 routinely says `skills/foo.txt` even though our
    file tools already sandbox to skills/. Without this, that produced
    `skills/skills/foo.txt`. Safe because we only strip when the first
    path component equals the sandbox root's own basename.
    """
    if not path:
        raise SandboxError("path must be non-empty")
    p = Path(path)
    if p.is_absolute():
        raise SandboxError("absolute paths are not allowed")
    if any(part == ".." for part in p.parts):
        raise SandboxError("'..' is not allowed in paths")
    if p.parts and p.parts[0] == root.name:
        p = Path(*p.parts[1:]) if len(p.parts) > 1 else Path(".")

    full = (root / p).resolve()
    try:
        full.relative_to(root.resolve())
    except ValueError as exc:
        raise SandboxError(f"path escapes the sandbox: {path!r}") from exc
    return full


# ---------------------------------------------------------------------------
# Git auto-commit — pairs with file_write to make every agent-authored
# change a real audit trail (commit per write, jaeger-agent author).
# ---------------------------------------------------------------------------
def git_autocommit(layout: InstanceLayout, rel_path: str, message: str) -> str | None:
    """Add + commit the agent-written file inside the instance's git repo.

    Best-effort: if git isn't available, or the repo wasn't initialized,
    or the staged content is unchanged, we silently return None. We never
    want a git hiccup to fail the agent's write — the on-disk content is
    the source of truth; git is the audit trail.
    """
    git_dir = layout.root / ".git"
    if not git_dir.exists() or shutil.which("git") is None:
        return None
    try:
        env = {
            "GIT_AUTHOR_NAME": "jaeger-agent",
            "GIT_AUTHOR_EMAIL": "agent@local",
            "GIT_COMMITTER_NAME": "jaeger-agent",
            "GIT_COMMITTER_EMAIL": "agent@local",
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(layout.root),
        }
        subprocess.run(
            ["git", "-C", str(layout.root), "add", rel_path],
            check=True, capture_output=True, timeout=5, env=env,
        )
        result = subprocess.run(
            ["git", "-C", str(layout.root), "commit", "-m", message],
            capture_output=True, timeout=5, env=env, text=True,
        )
        if result.returncode != 0:
            if "nothing to commit" in (result.stdout + result.stderr):
                return None
            _audit("git_commit_failed", {"path": rel_path, "stderr": result.stderr[:200]})
            return None
        sha = subprocess.run(
            ["git", "-C", str(layout.root), "rev-parse", "HEAD"],
            check=True, capture_output=True, timeout=5, text=True, env=env,
        ).stdout.strip()
        return sha[:12]
    except (subprocess.SubprocessError, OSError) as exc:
        _audit("git_commit_failed", {"path": rel_path, "error": str(exc)})
        return None
