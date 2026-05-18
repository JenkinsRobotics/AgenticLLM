"""Background thread that fires scheduled prompts when they come due.

Designed to be started by a long-running process (plugins/voice_loop.py,
plugins/messaging_gateway.py, the bench harness with --think, etc.).
The bench harness intentionally
does NOT start the runner — schedules tools work standalone (write to
schedules.jsonl) and the runner is a separate concern.

Usage:
    runner = CronRunner(callback=lambda prompt: run_for_voice(client, prompt))
    runner.start()
    ...
    runner.shutdown()
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from . import memory_module as mm


class CronRunner(threading.Thread):
    """Polls memory.schedules.jsonl for due rows and fires the callback.

    The callback receives the prompt string. It runs on the runner's
    thread so the caller's main loop isn't blocked, but tool invocations
    can race with main-loop calls — caller is responsible for serializing
    LLM access (a `threading.Lock` shared with the main loop is the
    canonical pattern).
    """

    def __init__(
        self,
        callback: Callable[[str], Any],
        *,
        poll_s: float = 30.0,
        llm_lock: threading.Lock | None = None,
    ) -> None:
        super().__init__(daemon=True, name="cron-runner")
        self._callback = callback
        self._poll_s = max(1.0, float(poll_s))
        self._lock = llm_lock
        self._stop = threading.Event()

    def shutdown(self, wait: bool = True) -> None:
        self._stop.set()
        if wait:
            self.join(timeout=5.0)

    def run(self) -> None:
        while not self._stop.is_set():
            # Claim atomically — the file lock inside `claim_due_schedules`
            # guarantees a second runner on the same host won't double-fire
            # this tick's due schedules. The mark-ran row was written under
            # the same lock, so we can fire outside the lock safely.
            try:
                claimed = mm.claim_due_schedules(now=datetime.now(timezone.utc))
            except Exception as exc:
                print(f"[cron-runner] claim error: {exc}", flush=True)
                claimed = []
            for sched in claimed:
                if self._stop.is_set():
                    break
                name = sched.get("name") or "?"
                prompt = sched.get("prompt") or ""
                if not prompt:
                    continue
                print(f"[cron-runner] firing {name!r}: {prompt!r}", flush=True)
                try:
                    if self._lock is not None:
                        with self._lock:
                            self._invoke(prompt, name)
                    else:
                        self._invoke(prompt, name)
                except Exception as exc:
                    print(f"[cron-runner] {name!r} callback failed: {exc}", flush=True)
            # Wait for the next tick, but wake immediately on shutdown.
            self._stop.wait(self._poll_s)

    def _invoke(self, prompt: str, schedule_name: str) -> None:
        """Call the handler with a cron-specific session key when supported,
        so scheduled prompts don't bleed into any user chat's rolling history."""
        key = f"cron:{schedule_name}"
        try:
            self._callback(prompt, session_key=key)
        except TypeError:
            self._callback(prompt)
