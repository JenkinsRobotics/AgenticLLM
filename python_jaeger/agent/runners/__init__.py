"""In-process background runners owned by the framework.

Runners are NOT plugins under the strict vocabulary contract — they don't
bridge to external state, services, or hardware. They're just long-lived
work the framework manages on its own threads.

Current runners:
  • thinking_runner.ThinkingRunner — fires a chain-of-thought call after
    each user turn on a single-worker pool, sharing the main LLM lock.

CronRunner currently lives at core/cron_runner.py — moving it here is
on the cleanup list but not load-bearing.
"""

from __future__ import annotations

from . import thinking_runner  # re-export so callers can `from .core.runners import thinking_runner`

__all__ = ["thinking_runner"]
