#!/usr/bin/env python3
"""Multi-channel messaging gateway.

Loads the pydantic_ai agent ONCE, then starts every channel adapter that
has the env vars to authenticate. All channels share the same Gemma
instance, the same memory store, and the same SKILL/CRON state.

  Discord adapter:   needs DISCORD_BOT_TOKEN, optional DISCORD_ALLOWED_USER_IDS
  iMessage adapter:  needs IMESSAGE_ALLOWED_HANDLES (and Full Disk Access)

Run:
    python -m python_pydantic_ai.plugins.messaging_gateway
    python -m python_pydantic_ai.plugins.messaging_gateway --no-imessage
    python -m python_pydantic_ai.plugins.messaging_gateway --no-discord

The gateway also starts the CronRunner so scheduled prompts fire while
the messaging daemon is up. Ctrl-C cleanly shuts everything down.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import time
from typing import Any

from ..main import (
    LlamaCppPythonClient,
    init_extensions,
    prewarm,
    run_for_voice,
    shutdown_extensions,
)
from .. import tools as agent_tools
from ..memory.cron_runner import CronRunner


def _make_handler(client: Any) -> "callable":
    """Wrap run_for_voice into a sync `text -> reply` callback.

    Each bridge passes its own `session_key` so the per-channel rolling
    history stays isolated (Telegram chat A doesn't see Discord chat B,
    etc.). Older bridges that haven't been upgraded still work — they
    just hit the default key.
    """
    def handler(text: str, session_key: str | None = None) -> str:
        result = run_for_voice(client, text, session_key=session_key)
        return (result.get("text") or "").strip()
    return handler


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--no-discord", action="store_true")
    p.add_argument("--no-telegram", action="store_true")
    p.add_argument("--no-imessage", action="store_true")
    p.add_argument("--no-cron", action="store_true")
    args = p.parse_args()

    # Production posture: remote-message channels never get to destroy files
    # or memory without explicit user confirmation through the agent's
    # ask_user tool. Set the same env gate voice mode uses.
    os.environ.setdefault("DESTRUCTIVE_OPS_REQUIRE_CONFIRM", "1")

    # Setup wizard / config push. If memory/config.json doesn't exist we
    # offer the wizard interactively (Ctrl-C skips). Existing config is
    # applied to env vars so the bridges below pick up tokens automatically.
    try:
        from ...memory import config as user_config

        user_config.ensure_configured(prompt_if_missing=sys.stdin.isatty())
    except Exception as exc:
        print(f"[gateway] setup check skipped: {exc}", flush=True)

    print("[gateway] loading Gemma in-process...", flush=True)
    started = time.perf_counter()
    client = LlamaCppPythonClient(ctx=4096, warmup=True)
    print(f"[gateway] loaded in {time.perf_counter() - started:.1f}s", flush=True)

    class _Args:
        with_memory = True
        with_mcp = False
        think = False
    init_extensions(_Args(), client)
    agent_tools.ensure_workspace()
    prewarm(client)

    # Single lock guards all LLM access — voice loop, Discord, iMessage,
    # cron runner all serialize through it so two channels can't decode
    # against the same KV cache simultaneously.
    llm_lock = threading.Lock()
    handler = _make_handler(client)

    adapters: list[Any] = []
    if not args.no_discord and os.environ.get("DISCORD_BOT_TOKEN"):
        try:
            from .discord import DiscordBridge
            d = DiscordBridge(handler, llm_lock=llm_lock)
            d.start()
            adapters.append(d)
            print("[gateway] Discord adapter started", flush=True)
        except Exception as exc:
            print(f"[gateway] Discord adapter skipped: {exc}", flush=True)
    elif not args.no_discord:
        print("[gateway] Discord adapter skipped: DISCORD_BOT_TOKEN unset", flush=True)

    if not args.no_telegram and os.environ.get("TELEGRAM_BOT_TOKEN"):
        try:
            from .telegram import TelegramBridge
            t = TelegramBridge(handler, llm_lock=llm_lock)
            t.start()
            adapters.append(t)
            print("[gateway] Telegram adapter started", flush=True)
        except Exception as exc:
            print(f"[gateway] Telegram adapter skipped: {exc}", flush=True)
    elif not args.no_telegram:
        print("[gateway] Telegram adapter skipped: TELEGRAM_BOT_TOKEN unset", flush=True)

    if not args.no_imessage and sys.platform == "darwin":
        try:
            from .imessage import IMessageBridge
            im = IMessageBridge(handler, llm_lock=llm_lock)
            im.start()
            adapters.append(im)
        except Exception as exc:
            print(f"[gateway] iMessage adapter skipped: {exc}", flush=True)

    cron_runner: CronRunner | None = None
    if not args.no_cron:
        cron_runner = CronRunner(handler, llm_lock=llm_lock)
        cron_runner.start()
        print("[gateway] cron runner started", flush=True)

    if not adapters and cron_runner is None:
        print("[gateway] no adapters started — nothing to do; exiting", flush=True)
        return 1

    print("[gateway] ready. Ctrl-C to quit.", flush=True)
    stop = threading.Event()

    def _shutdown(*_: Any) -> None:
        print("\n[gateway] shutdown signal received", flush=True)
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    try:
        while not stop.is_set():
            stop.wait(1.0)
    finally:
        if cron_runner is not None:
            cron_runner.shutdown(wait=False)
        for ad in adapters:
            try:
                ad.stop()
            except Exception as exc:
                print(f"[gateway] adapter stop failed: {exc}", flush=True)
        shutdown_extensions(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
