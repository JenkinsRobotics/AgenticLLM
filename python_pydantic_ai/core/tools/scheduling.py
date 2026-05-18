"""Cron-style scheduling skills.

  • schedule_prompt(cron_expr, prompt, name) — add a recurring prompt
  • list_schedules()                         — see what's active
  • cancel_schedule(name)                    — remove one

Persisted in <framework>/memory/schedules.jsonl, fired by the CronRunner
inside plugins/voice_loop.py or plugins/messaging_gateway.py.
"""

from __future__ import annotations

from typing import Any


def schedule_prompt(cron_expr: str, prompt: str, name: str | None = None) -> dict[str, Any]:
    """Schedule a prompt to run unattended on a cron expression.

    `cron_expr` is standard 5-field cron — e.g. "0 7 * * *" for 7 AM daily,
    "*/10 * * * *" for every 10 minutes. The named schedule fires by
    invoking the same agent loop a fresh user turn would; tool results,
    memory updates, and TTS all behave the same. Use `list_schedules` /
    `cancel_schedule` to inspect and remove entries.
    """
    from ...memory.memory_module import add_schedule

    try:
        row = add_schedule(cron_expr=cron_expr, prompt=prompt, name=name)
    except Exception as exc:
        return {"scheduled": False, "error": str(exc)}
    return {"scheduled": True, **row}


def list_schedules() -> dict[str, Any]:
    """List every active scheduled prompt with its next-run timestamp."""
    from ...memory.memory_module import list_schedules as _ls

    rows = _ls()
    return {"count": len(rows), "schedules": rows}


def cancel_schedule(name: str) -> dict[str, Any]:
    """Remove a previously-scheduled prompt by name."""
    from ...memory.memory_module import cancel_schedule as _cs

    ok = _cs(name)
    return {"cancelled": ok, "name": name}
