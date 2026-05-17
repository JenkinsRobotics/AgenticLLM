"""Cron-style scheduling skills.

  • schedule_prompt(cron_expr, prompt, name) — add a recurring prompt
  • list_schedules()                         — see what's active
  • cancel_schedule(name)                    — remove one

Persisted in <instance>/memory/schedules.jsonl, fired by CronRunner.
"""

from __future__ import annotations

from typing import Any

from .. import memory as mem


def schedule_prompt(cron_expr: str, prompt: str, name: str | None = None) -> dict[str, Any]:
    """Schedule a prompt for unattended execution on a cron expression.

    `cron_expr` is standard 5-field cron — e.g. "0 7 * * *" (7am daily),
    "*/10 * * * *" (every 10 minutes). The scheduled prompt fires in the
    same agent loop a fresh user turn would; tool results, memory updates,
    and TTS all behave the same.
    """
    try:
        row = mem.add_schedule(cron_expr=cron_expr, prompt=prompt, name=name)
    except Exception as exc:
        return {"scheduled": False, "error": str(exc)}
    return {"scheduled": True, **row}


def list_schedules() -> dict[str, Any]:
    """List every active scheduled prompt with its next-run timestamp."""
    rows = mem.list_schedules()
    return {"count": len(rows), "schedules": rows}


def cancel_schedule(name: str) -> dict[str, Any]:
    """Remove a previously-scheduled prompt by name."""
    ok = mem.cancel_schedule(name)
    return {"cancelled": ok, "name": name}
