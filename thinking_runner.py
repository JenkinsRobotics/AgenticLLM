"""Opt-in background thinking extension.

When --think is set, after each main turn the user's question is also dispatched
to a "thinking" LLM call running in a background thread. The thinking call uses
a chain-of-thought style system prompt and writes its result to thinking.jsonl
at the project root.

Why a background thread vs. inline:
- The main path returns immediately, so user-perceived latency is unchanged.
- The thinking call still uses the same llama.cpp model instance — we serialize
  with a lock so we never invoke the model concurrently (llama-cpp-python is
  not thread-safe for that).
- If the user submits the next prompt before thinking finishes, that prompt
  has to wait for the current thinking call to complete.

This is opt-in. Default agent paths pay zero cost.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "thinking.jsonl"


THINKING_SYSTEM_PROMPT = """You are a careful planning agent thinking through the user's request.

Think step by step about:
1. What the user wants accomplished
2. What information or decisions are required
3. Possible approaches and their tradeoffs
4. The recommended plan in 3-5 concrete steps

Be specific. Keep the whole response under 200 words. No tool calls — just analysis.
"""


class ThinkingRunner:
    """One per process. Submits thinking jobs to a single-worker pool that
    serializes against a shared LLM lock."""

    def __init__(self, client: Any, framework: str, llm_lock: threading.Lock) -> None:
        self.client = client
        self.framework = framework
        self.llm_lock = llm_lock
        # max_workers=1 so we never queue multiple think jobs against the model.
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="thinking")
        self._pending = 0
        self._pending_lock = threading.Lock()

    def queue(self, user_text: str, run_id: str | None = None) -> None:
        with self._pending_lock:
            self._pending += 1
        self.executor.submit(self._run, user_text, run_id)

    def _run(self, user_text: str, run_id: str | None) -> None:
        try:
            self._do_run(user_text, run_id)
        except Exception as exc:
            self._log_entry(
                user_text=user_text,
                run_id=run_id,
                thinking="",
                elapsed_s=0.0,
                error=str(exc),
            )
        finally:
            with self._pending_lock:
                self._pending -= 1

    def _do_run(self, user_text: str, run_id: str | None) -> None:
        started = time.perf_counter()
        with self.llm_lock:
            result = self.client.chat(
                [
                    {"role": "system", "content": THINKING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                max_tokens=512,
                temperature=0.7,
                top_p=0.95,
                stream=False,
            )
        elapsed = time.perf_counter() - started
        self._log_entry(
            user_text=user_text,
            run_id=run_id,
            thinking=result.text,
            elapsed_s=elapsed,
        )

    def _log_entry(
        self,
        *,
        user_text: str,
        run_id: str | None,
        thinking: str,
        elapsed_s: float,
        error: str | None = None,
    ) -> None:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "run_id": run_id,
            "framework": self.framework,
            "user": user_text,
            "elapsed_s": round(elapsed_s, 3),
            "thinking": thinking,
        }
        if error:
            entry["error"] = error
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def shutdown(self, wait: bool = True, timeout: float = 60.0) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=not wait)

    def pending(self) -> int:
        with self._pending_lock:
            return self._pending
