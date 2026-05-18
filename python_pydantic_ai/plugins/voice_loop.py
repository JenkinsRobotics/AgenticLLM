#!/usr/bin/env python3
"""Voice loop — STT → agent → TTS daemon, with optional barge-in.

Three runtime modes selected at startup:

  --stt-mode two_pass    (default)
      VAD-segmented STT with fast→accurate Whisper cascade.

  --stt-mode continuous
      Energy-segmented STT with rolling re-transcription. Lower commit
      latency, lighter memory footprint.

  --barge-in
      Allow the user to interrupt the AI mid-speech. Uses AEC (speexdsp)
      when available; without it, falls back to mic-pause heuristic.

Run:
    python -m python_pydantic_ai.plugins.voice_loop
    python -m python_pydantic_ai.plugins.voice_loop --stt-mode continuous
    python -m python_pydantic_ai.plugins.voice_loop --require-wake-word --barge-in

Mirrors python_jaeger.plugins.voice_loop. See docs/VOCABULARY.md for why
this file is the daemon orchestrator, not a Plugin itself.
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
from ..memory.cron_runner import CronRunner


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stt-mode", choices=["two_pass", "continuous"], default="two_pass",
                   help="Which STT algorithm to use.")
    p.add_argument("--require-wake-word", action="store_true",
                   help="Gate every utterance behind a wake phrase.")
    p.add_argument("--barge-in", action="store_true",
                   help="Allow user to interrupt AI mid-speech (non-blocking TTS).")
    p.add_argument("--no-aec", action="store_true",
                   help="Force AEC passthrough even if speexdsp is installed.")
    p.add_argument("--fast-model", type=str, default="base.en",
                   help="Whisper fast/continuous model name (default: base.en).")
    p.add_argument("--accurate-model", type=str, default="medium.en",
                   help="Whisper accurate model name (two_pass only, default: medium.en).")
    p.add_argument("--no-cron", action="store_true",
                   help="Don't start the cron runner alongside the voice loop.")
    p.add_argument("--no-chimes", action="store_true",
                   help="Disable wake / follow-up audio earcons.")
    args = p.parse_args()

    os.environ.setdefault("DESTRUCTIVE_OPS_REQUIRE_CONFIRM", "1")

    # ── Load the LLM ─────────────────────────────────────────────────
    print("[voice] loading Gemma in-process...", flush=True)
    started = time.perf_counter()
    client = LlamaCppPythonClient(ctx=4096, warmup=True)
    print(f"[voice] loaded in {time.perf_counter() - started:.1f}s", flush=True)

    class _Args:
        with_memory = True
        with_mcp = False
        think = False
    init_extensions(_Args(), client)
    prewarm(client)

    # ── AEC + reference buffer (only when barge-in is requested) ─────
    aec = None
    reference_buffer = None
    if args.barge_in:
        from ..core.audio import AECWrapper, ReferenceBuffer, aec_available
        if not args.no_aec and aec_available():
            aec = AECWrapper(sample_rate=16000, frame_ms=10, enabled=True)
            reference_buffer = ReferenceBuffer(sample_rate=16000, capacity_seconds=2.0)
            print(f"[voice] AEC enabled ({aec.backend}); barge-in via echo cancellation", flush=True)
        else:
            reason = "user-requested" if args.no_aec else "speexdsp not installed"
            print(f"[voice] AEC unavailable ({reason}); barge-in via mic-pause heuristic only", flush=True)

    # ── Chimes (wake + follow-up earcons) ────────────────────────────
    from ..core.audio import ChimePlayer
    chimes = ChimePlayer(
        enabled=not args.no_chimes,
        reference_buffer=reference_buffer,
    )

    # ── Warm TTS (and wire reference buffer if barge-in is on) ───────
    from ..core.tools.speak import _get_tts
    tts = _get_tts()
    if reference_buffer is not None:
        tts.reference_buffer = reference_buffer
    print("[voice] warming Kokoro TTS...", flush=True)
    warm_result = tts.warm()
    if warm_result.get("warmed"):
        print(f"[voice] Kokoro ready ({warm_result.get('seconds')}s)", flush=True)
    else:
        print(f"[voice] Kokoro warm failed: {warm_result.get('reason')} "
              f"— continuing; first speak() will pay the cost", flush=True)

    # ── Build STT in the requested mode ──────────────────────────────
    if args.stt_mode == "continuous":
        from .whisper_stt import WhisperSTTContinuous
        stt = WhisperSTTContinuous(
            model_name=args.fast_model,
            require_wake_word=args.require_wake_word,
            aec=aec, far_end_buffer=reference_buffer,
        )
    else:
        from .whisper_stt import WhisperSTTTwoPass
        stt = WhisperSTTTwoPass(
            fast_model_name=args.fast_model,
            accurate_model_name=args.accurate_model,
            require_wake_word=args.require_wake_word,
            aec=aec, far_end_buffer=reference_buffer,
        )
    stt.start()

    # ── Cron runner (optional) ───────────────────────────────────────
    llm_lock = threading.Lock()
    cron_runner: CronRunner | None = None
    if not args.no_cron:
        def _cron_callback(prompt: str, session_key: str | None = None) -> None:
            run_for_voice(client, prompt, session_key=session_key)
        cron_runner = CronRunner(_cron_callback, llm_lock=llm_lock)
        cron_runner.start()
        print("[voice] cron runner started", flush=True)

    mode_msg = f"mode={args.stt_mode}"
    if args.require_wake_word:
        mode_msg += ", wake-word required (say 'hey jaeger')"
    if args.barge_in:
        mode_msg += ", barge-in on"
    print(f"[voice] ready. {mode_msg}. Ctrl-C to quit.", flush=True)

    # ── Shutdown handling ────────────────────────────────────────────
    stop = threading.Event()

    def _shutdown(*_: Any) -> None:
        print("\n[voice] shutdown signal received", flush=True)
        stop.set()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    # ── Main loop ────────────────────────────────────────────────────
    try:
        while not stop.is_set():
            phrase = stt.next_phrase(timeout=1.0)
            if not phrase:
                continue
            print(f"[voice] user: {phrase!r}", flush=True)

            # Wake chime — brief tone tells the user "heard you, processing".
            # Pause mic during chime when there's no AEC to cancel it.
            if chimes.enabled("wake"):
                if reference_buffer is None:
                    stt.set_paused(True)
                chimes.play("wake")
                if reference_buffer is None:
                    stt.set_paused(False)

            if not args.barge_in:
                stt.set_paused(True)
            try:
                result = run_for_voice(client, phrase, session_key="voice")
            finally:
                if not args.barge_in:
                    stt.set_paused(False)

            text = (result.get("text") or "").strip()
            spoke_via_tool = result.get("spoke_via_tool", False)

            if not text or spoke_via_tool:
                if spoke_via_tool:
                    print("[voice] agent vocalized via tool — skipping post-turn speak", flush=True)
                stt.open_followup()
                continue

            if args.barge_in:
                # Install a callback the STT thread fires the moment it sees
                # sustained voice — sub-50 ms latency, no polling.
                interrupted = {"flag": False}

                def _on_user_speaks() -> None:
                    if not interrupted["flag"]:
                        interrupted["flag"] = True
                        print("[voice] barge-in detected — stopping TTS", flush=True)
                        tts.stop()

                stt.set_on_speech_detected(_on_user_speaks)
                try:
                    play_result = tts.play_async(text)
                    if not play_result.get("started"):
                        print(f"[voice] TTS skipped: {play_result.get('reason')}", flush=True)
                        stt.open_followup()
                        continue
                    tts.wait_until_done()
                finally:
                    stt.set_on_speech_detected(None)
                # Drop any phrases buffered during playback so a stale
                # utterance doesn't become the next "user input".
                stt.drain_pending()
                # Follow-up chime (barge-in path) — only safe when AEC is
                # active. Without AEC, open mic would hear the chime as a
                # phrase, so skip it.
                if (
                    stt.require_wake_word
                    and chimes.enabled("followup")
                    and reference_buffer is not None
                ):
                    chimes.play("followup")
                stt.open_followup()
            else:
                tts.speak(text)
                # Follow-up chime — rising two-note tone tells the user
                # "still listening, no wake word needed for the next phrase".
                if stt.require_wake_word and chimes.enabled("followup"):
                    if reference_buffer is None:
                        stt.set_paused(True)
                    chimes.play("followup")
                    if reference_buffer is None:
                        stt.set_paused(False)
                stt.open_followup()
    finally:
        try:
            tts.stop()
        except Exception:
            pass
        stt.stop()
        if cron_runner is not None:
            cron_runner.shutdown(wait=False)
        shutdown_extensions(wait=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
