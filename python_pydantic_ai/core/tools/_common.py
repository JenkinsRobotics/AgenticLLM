"""Shared helpers for every skill module in this package.

Anything used by 2+ skill files lives here — workspace paths, destructive-
op confirmation policy, common constants. Keeps each category file focused
on its tools and free of cross-skill plumbing.
"""

from __future__ import annotations

import os
from pathlib import Path


# This file lives at python_pydantic_ai/core/tools/_common.py — the
# workspace dir is at the framework root, three parents up.
WORKSPACE = Path(__file__).resolve().parent.parent.parent / "workspace"


def ensure_workspace() -> None:
    """Make sure the framework's sandboxed workspace exists."""
    WORKSPACE.mkdir(parents=True, exist_ok=True)


def workspace_path(path: str) -> Path:
    """Resolve a workspace-relative path with escape protection.

    Rejects any target that resolves outside WORKSPACE. Every file tool
    routes its `path` argument through here so the agent can never
    accidentally (or deliberately) write outside the sandbox.
    """
    ensure_workspace()
    target = (WORKSPACE / path).resolve()
    if not target.is_relative_to(WORKSPACE):
        raise ValueError("path must stay inside agent_test/workspace")
    return target


def destructive_confirm_required() -> bool:
    """Production / voice modes set DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1 so
    the agent must preview destructive ops before committing.
    Bench / dev keep the legacy behavior (zero perf cost when unset)."""
    return os.environ.get("DESTRUCTIVE_OPS_REQUIRE_CONFIRM", "").strip() in ("1", "true", "yes")
