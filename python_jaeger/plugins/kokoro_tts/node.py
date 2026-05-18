"""Kokoro TTS — synthesizes text via Kokoro KPipeline, plays through sounddevice.

This module is the plugin's actual implementation. It's a relocation of
the pipeline + playback code that used to live in `core/tools/speak.py`.
The agent-callable `speak()` / `speak_file()` Tools still live there, but
they now delegate into this plugin.

Why a plugin and not a core tool? Per the vocabulary contract, this
component bridges the agent to an external library (`kokoro`) + external
model files + speaker hardware. That's the plugin pattern. When we deploy
to robot hardware, this same plugin will graduate to a separate-process
ZMQ node on the Jetson while the rest of the framework stays put.

Public surface (consumed by core/tools/speak.py):
  • KokoroTTS()              — lazy-loaded singleton in practice
  • .warm()                  — pre-load weights so the first speak() is fast
  • .speak(text)             — synthesize + play, returns result dict
  • Module constants         — KOKORO_VOICE, KOKORO_LANG, KOKORO_SAMPLE_RATE
"""

from __future__ import annotations

import re
import time
from typing import Any


KOKORO_VOICE = "af_heart"
KOKORO_LANG = "a"
KOKORO_SAMPLE_RATE = 24000
# Sample rate the AEC reference buffer is expected to run at. AEC math
# requires near (mic) and far (TTS playback) at the same sample rate;
# the mic captures at 16 kHz, so Kokoro's 24 kHz output gets resampled
# down before being pushed to the reference buffer.
REFERENCE_SAMPLE_RATE = 16000


# ---------------------------------------------------------------------------
# Markdown stripping for TTS — agents emit asterisks, code fences, link
# syntax, etc., and Kokoro reads them literally otherwise.
# ---------------------------------------------------------------------------
def clean_for_tts(text: str) -> str:
    """Strip markdown the agent might emit so TTS doesn't read it literally.
    Removes code fences, inline code backticks, bold/italic asterisks,
    leading list markers, and markdown link syntax (keeping the link text)."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"^[\-\*\d\.\)]+\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _resample_to_reference_rate(audio_f32):
    """Resample Kokoro's 24 kHz output to the AEC reference sample rate
    (16 kHz). Polyphase keeps the voice band intact and adds well under
    a millisecond of latency."""
    import numpy as np
    from scipy.signal import resample_poly

    if audio_f32.size == 0:
        return np.zeros(0, dtype=np.float32)
    if KOKORO_SAMPLE_RATE == REFERENCE_SAMPLE_RATE:
        return audio_f32.astype(np.float32, copy=False)
    return resample_poly(audio_f32, up=REFERENCE_SAMPLE_RATE, down=KOKORO_SAMPLE_RATE).astype(np.float32)


# ---------------------------------------------------------------------------
# SSML parsing for paced narration
# ---------------------------------------------------------------------------
_SSML_SPEAK_TAG = re.compile(r"</?speak\s*>", re.IGNORECASE)
_SSML_TAG = re.compile(
    r'<break\s+time=["\'](\d+(?:\.\d+)?)\s*(ms|s)["\']\s*/?>|<breath\s*/?>',
    re.IGNORECASE,
)
_BREATH_GAP_MS = 220


def _ssml_segments(text: str):
    """Yield ('text', str) | ('silence_ms', int) chunks."""
    cleaned = _SSML_SPEAK_TAG.sub("", text)
    pos = 0
    for match in _SSML_TAG.finditer(cleaned):
        before = cleaned[pos:match.start()]
        if before.strip():
            yield ("text", before.strip())
        tag = match.group(0).lower()
        if tag.startswith("<break"):
            value = float(match.group(1))
            unit = match.group(2).lower()
            ms = int(value * 1000) if unit == "s" else int(value)
            yield ("silence_ms", ms)
        else:
            yield ("silence_ms", _BREATH_GAP_MS)
        pos = match.end()
    tail = cleaned[pos:]
    if tail.strip():
        yield ("text", tail.strip())


class KokoroTTS:
    """Lazy-loaded Kokoro pipeline + sounddevice playback.

    Single-instance in practice — `core/tools/speak.py` caches one in a
    module global. Thread-safety is intentionally minimal: Kokoro's pipeline
    is not designed for concurrent calls, and the agent's tool surface is
    serialized through the LLM lock anyway.
    """

    def __init__(
        self,
        *,
        voice: str = KOKORO_VOICE,
        lang: str = KOKORO_LANG,
        reference_buffer: Any = None,
    ) -> None:
        self.voice = voice
        self.lang = lang
        self._pipeline: Any = None
        # When set, every played frame is also pushed to this buffer so the
        # STT plugin's AEC can use it as the far-end reference. Without it,
        # AEC sees silence as far-end and barge-in won't work — but plain
        # set_paused()-based playback still works.
        self.reference_buffer = reference_buffer

    # ── pipeline lifecycle ────────────────────────────────────────────
    def _ensure_pipeline(self) -> Any:
        if self._pipeline is None:
            from kokoro import KPipeline
            self._pipeline = KPipeline(lang_code=self.lang, repo_id="hexgrad/Kokoro-82M")
        return self._pipeline

    def warm(self) -> dict[str, Any]:
        """Pre-load Kokoro so the first speak() doesn't pay the ~3–5 s
        weight-load tax. Idempotent."""
        started = time.perf_counter()
        try:
            pipe = self._ensure_pipeline()
            for _ in pipe(" ", voice=self.voice):
                break
        except Exception as exc:
            return {"warmed": False, "reason": str(exc)}
        return {"warmed": True, "seconds": round(time.perf_counter() - started, 3)}

    # ── synthesis + playback ──────────────────────────────────────────
    def _synthesize(self, text: str) -> tuple[Any, bool]:
        """Render the text to a single float32 audio buffer. Returns
        (audio, has_ssml). Caller is responsible for playback."""
        import numpy as np

        pipe = self._ensure_pipeline()
        chunks: list[Any] = []
        has_ssml = (
            "<break" in text.lower()
            or "<breath" in text.lower()
            or "<speak" in text.lower()
        )
        if has_ssml:
            for kind, value in _ssml_segments(text):
                if kind == "text":
                    for r in pipe(value, voice=self.voice):
                        if r.audio is not None:
                            chunks.append(np.asarray(r.audio, dtype=np.float32))
                else:
                    n = int(KOKORO_SAMPLE_RATE * value / 1000)
                    if n > 0:
                        chunks.append(np.zeros(n, dtype=np.float32))
        else:
            for r in pipe(text, voice=self.voice):
                if r.audio is not None:
                    chunks.append(np.asarray(r.audio, dtype=np.float32))
        if not chunks:
            return None, has_ssml
        return np.concatenate(chunks), has_ssml

    def speak(self, text: str) -> dict[str, Any]:
        """Synthesize speech with Kokoro and play through the default output.
        Supports minimal SSML: <speak>, <break time="Xms"/>, <breath/>.
        Blocks until playback finishes (or stop() is called from another
        thread). For non-blocking playback that supports barge-in, use
        `play_async()`. Markdown (`**bold**`, code fences, link syntax) is
        stripped before synthesis."""
        import sounddevice as sd

        cleaned = clean_for_tts(text)
        if not cleaned:
            return {"spoken": False, "reason": "empty text"}

        started = time.perf_counter()
        audio, has_ssml = self._synthesize(cleaned)
        if audio is None:
            return {"spoken": False, "reason": "no audio generated"}

        device = _play_audio_with_live_device(sd, audio, self.reference_buffer)
        if isinstance(device, dict):
            return {**device, "text": cleaned}
        return {
            "spoken": True,
            "text": cleaned,
            "chars": len(cleaned),
            "seconds": round(time.perf_counter() - started, 3),
            "ssml": has_ssml,
            "device": device,
        }

    # ── async playback (for barge-in) ─────────────────────────────────
    def play_async(self, text: str) -> dict[str, Any]:
        """Like speak(), but returns immediately and supports interruption.

        Kicks off a synthesis thread that streams Kokoro generator chunks
        into an OutputStream + queue. Each chunk is pushed to playback AS
        IT'S SYNTHESIZED, not after the whole utterance is rendered — so
        the user can interrupt during synthesis, not just during playback.

        AEC reference audio is resampled from 24 kHz down to 16 kHz before
        being pushed to the reference buffer (which the STT-side AEC reads
        at 16 kHz, the mic's native rate).

        Markdown stripping is applied before synthesis.

        Returns synthesis metadata. To know when playback actually ends,
        poll `is_playing()` or call `wait_until_done()`.
        """
        import numpy as np
        import sounddevice as sd
        import threading
        import queue as _queue

        cleaned = clean_for_tts(text)
        if not cleaned:
            return {"started": False, "reason": "empty text"}

        synth_started = time.perf_counter()

        # Fresh per-utterance cancel flag — set() to stop both synthesis
        # and playback. Threads check it between chunks.
        self._cancel = threading.Event()

        # Bounded audio queue between the synth thread and the playback
        # callback. None sentinel marks end-of-stream.
        self._play_q: "_queue.Queue[np.ndarray | None]" = _queue.Queue(maxsize=32)
        # Current chunk being drained by the callback.
        self._current_chunk = np.zeros(0, dtype=np.float32)
        self._stream_done = threading.Event()

        device = _resolve_live_device(sd)

        # Synthesis worker — runs in its own thread so play_async() returns.
        def _synth_loop() -> None:
            pipe = self._ensure_pipeline()
            try:
                has_ssml = (
                    "<break" in cleaned.lower()
                    or "<breath" in cleaned.lower()
                    or "<speak" in cleaned.lower()
                )
                if has_ssml:
                    for kind, value in _ssml_segments(cleaned):
                        if self._cancel.is_set():
                            return
                        if kind == "text":
                            for r in pipe(value, voice=self.voice):
                                if self._cancel.is_set():
                                    return
                                if r.audio is None:
                                    continue
                                self._enqueue_chunk(np.asarray(r.audio, dtype=np.float32))
                        else:
                            n = int(KOKORO_SAMPLE_RATE * value / 1000)
                            if n > 0:
                                self._enqueue_chunk(np.zeros(n, dtype=np.float32))
                else:
                    for r in pipe(cleaned, voice=self.voice):
                        if self._cancel.is_set():
                            return
                        if r.audio is None:
                            continue
                        self._enqueue_chunk(np.asarray(r.audio, dtype=np.float32))
            finally:
                # End-of-stream marker — callback drains, then signals done.
                try:
                    self._play_q.put_nowait(None)
                except Exception:
                    pass

        def _audio_cb(outdata, frames, time_info, status) -> None:
            # Pulls float32 mono frames from the queue, writes to outdata.
            if status:
                pass  # underruns happen briefly mid-utterance; ignore
            if self._cancel.is_set():
                outdata.fill(0)
                self._stream_done.set()
                raise sd.CallbackStop()
            out = np.zeros(frames, dtype=np.float32)
            n_filled = 0
            ended = False
            while n_filled < frames:
                if len(self._current_chunk) == 0:
                    try:
                        nxt = self._play_q.get_nowait()
                    except _queue.Empty:
                        break
                    if nxt is None:
                        ended = True
                        break
                    self._current_chunk = nxt
                take = min(frames - n_filled, len(self._current_chunk))
                out[n_filled:n_filled + take] = self._current_chunk[:take]
                self._current_chunk = self._current_chunk[take:]
                n_filled += take
            outdata[:, 0] = out
            if ended and n_filled == 0 and self._play_q.empty():
                self._stream_done.set()
                raise sd.CallbackStop()

        # Close any prior stream (idempotent).
        self._close_stream()
        try:
            self._stream = sd.OutputStream(
                samplerate=KOKORO_SAMPLE_RATE,
                channels=1,
                dtype="float32",
                blocksize=int(KOKORO_SAMPLE_RATE * 0.02),  # 20 ms blocks
                device=device,
                callback=_audio_cb,
                finished_callback=self._stream_done.set,
            )
            self._stream.start()
        except Exception as exc:
            return {"started": False, "reason": f"stream open failed: {exc}"}

        self._synth_thread = threading.Thread(
            target=_synth_loop, daemon=True, name="kokoro-synth",
        )
        self._synth_thread.start()

        return {
            "started": True,
            "text": cleaned,
            "chars": len(cleaned),
            "synth_started_s": round(time.perf_counter() - synth_started, 3),
            "device": device,
        }

    def _enqueue_chunk(self, chunk_24k) -> None:
        """Push a synthesis chunk to the playback queue AND to the AEC
        reference buffer (resampled to the reference sample rate)."""
        if chunk_24k.size == 0:
            return
        if self.reference_buffer is not None:
            try:
                ref = _resample_to_reference_rate(chunk_24k)
                self.reference_buffer.write(ref)
            except Exception:
                pass
        try:
            self._play_q.put(chunk_24k, timeout=5.0)
        except Exception:
            pass

    def _close_stream(self) -> None:
        s = getattr(self, "_stream", None)
        if s is not None:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
            self._stream = None

    def stop(self) -> None:
        """Stop async playback immediately. Drops the queue, signals
        synthesis to bail, closes the output stream, and clears AEC
        reference. Idempotent."""
        cancel = getattr(self, "_cancel", None)
        if cancel is not None:
            cancel.set()
        play_q = getattr(self, "_play_q", None)
        if play_q is not None:
            with play_q.mutex:
                play_q.queue.clear()
        self._close_stream()
        if self.reference_buffer is not None:
            self.reference_buffer.clear()

    def is_playing(self) -> bool:
        """True while async playback is active (chunks still queued or
        playing). Polled by the voice loop to know when an async speak
        has finished naturally."""
        s = getattr(self, "_stream", None)
        if s is None:
            return False
        try:
            if not s.active:
                return False
        except Exception:
            return False
        play_q = getattr(self, "_play_q", None)
        # Stream is active and either still has buffered audio or the
        # synthesis thread might still be feeding it.
        synth = getattr(self, "_synth_thread", None)
        if synth is not None and synth.is_alive():
            return True
        if play_q is not None and not play_q.empty():
            return True
        # Stream is active but queue is empty and synth has exited — about to drain.
        return not getattr(self, "_stream_done", threading.Event()).is_set() if False else True

    def wait_until_done(self) -> None:
        """Block until async playback finishes naturally (or stop() is called)."""
        done = getattr(self, "_stream_done", None)
        if done is None:
            return
        done.wait(timeout=120.0)
        self._close_stream()


def _resolve_live_device(sd) -> int | None:
    """Re-query the current system default output device each call so
    AirPods/Speakers swaps work mid-session."""
    try:
        info = sd.query_devices(kind="output")
        if isinstance(info, dict) and "index" in info:
            return int(info["index"])
    except Exception:
        pass
    return None


def _play_audio_with_live_device(sd, audio, reference_buffer=None):
    """Synchronous play. Pushes audio to the AEC reference buffer (if
    supplied) so STT can cancel echo even on sync paths."""
    # Reference push happens BEFORE play() so the far-end is available
    # the moment the mic callback might fire. Stale reference is fine.
    if reference_buffer is not None:
        try:
            reference_buffer.write(audio)
        except Exception:
            pass

    device = _resolve_live_device(sd)
    try:
        sd.play(audio, samplerate=KOKORO_SAMPLE_RATE, device=device)
        sd.wait()
        return device
    except Exception as first_exc:
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        device = _resolve_live_device(sd)
        try:
            sd.play(audio, samplerate=KOKORO_SAMPLE_RATE, device=device)
            sd.wait()
            return device
        except Exception as second_exc:
            return {
                "spoken": False,
                "reason": f"playback failed after reinit: {second_exc}",
                "first_error": str(first_exc),
                "device": device,
            }
