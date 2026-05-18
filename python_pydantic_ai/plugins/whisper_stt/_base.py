"""Shared helpers used by both two_pass.py and continuous.py.

Plugin-internal — not exported through __init__.py. Both STT modes need:
  • _MicStream            — sounddevice InputStream + pauseable queue
  • _warm_stt             — silence-pass priming so first phrase isn't slow
  • _normalize            — lowercase + strip punctuation for wake-word match
  • _find_wake_in_text    — substring + fuzzy wake-phrase matcher
  • DEFAULT_WAKE_PHRASES  — canonical wake-phrase list (handles Whisper
                            mishearings: yeager/yager/jager/jaeger)

`_VadWorker` is two-pass specific (energy-segmentation in continuous mode
replaces it), so it stays in two_pass.py.

AEC integration is OPTIONAL: if a caller passes an `aec` instance and a
`far_end_buffer` to `_MicStream`, near-end audio is filtered before being
queued. If no AEC is wired, mic frames pass through unchanged.
"""

from __future__ import annotations

import queue
import re
import sys
import time
from difflib import SequenceMatcher
from typing import Any

import numpy as np


_WAKE_PREFIXES = ("ok", "okay", "hey")
_ASSISTANT_NAMES = ("jaeger", "yeager", "yager", "jager")
DEFAULT_WAKE_PHRASES = tuple(f"{p} {n}" for p in _WAKE_PREFIXES for n in _ASSISTANT_NAMES)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _find_wake_in_text(
    text: str,
    wake_phrases: tuple[str, ...],
    wake_match_threshold: float,
) -> tuple[bool, str]:
    """Return (matched, remainder_after_wake). Looks for an exact substring
    first, then falls back to fuzzy windowed matching."""
    norm = _normalize(text)
    for phrase in wake_phrases:
        idx = norm.find(phrase)
        if idx != -1:
            return True, norm[idx + len(phrase):].strip()
    tokens = norm.split()
    for phrase in wake_phrases:
        n = len(phrase.split())
        for i in range(0, max(0, len(tokens) - n + 1)):
            window = " ".join(tokens[i:i + n])
            if SequenceMatcher(None, window, phrase).ratio() >= wake_match_threshold:
                return True, " ".join(tokens[i + n:]).strip()
    return False, ""


def _warm_stt(model, label: str, sample_rate: int) -> None:
    """Run a 1.5-second silence transcription so the first real phrase doesn't
    pay model setup cost. Whisper rejects audio under 1000 ms (skips
    inference + warns), so 1.5 s is the safe minimum for warming."""
    warm_audio = np.zeros(int(sample_rate * 1.5), dtype=np.float32)
    print(f"[{label}] warming up...", flush=True)
    t0 = time.perf_counter()
    try:
        list(model.transcribe(warm_audio, language="en"))
    except Exception as exc:
        print(f"[{label}] warm-up skipped: {exc}", file=sys.stderr, flush=True)
    else:
        print(f"[{label}] primed ({time.perf_counter() - t0:.1f}s).", flush=True)


class _MicStream:
    """sounddevice InputStream + queue + pause flag.

    Optional AEC hook: if `aec` (object with `process(near, far)` method) and
    `far_end_buffer` (object with `pop_frame()` method) are passed in, each
    captured frame is filtered against the far-end reference before being
    queued. This is what makes barge-in possible — the mic stays open during
    TTS playback but the AI's own voice gets canceled out.

    If aec is None, frames pass through unchanged. Callers that don't want
    barge-in can use `set_paused(True)` during TTS instead.
    """

    def __init__(
        self,
        *,
        sample_rate: int,
        frame_samples: int,
        max_queue_frames: int = 200,
        device: Any = None,
        aec: Any = None,
        far_end_buffer: Any = None,
    ) -> None:
        import sounddevice as sd  # deferred — plugin owns the import

        self.sample_rate = sample_rate
        self.frame_samples = frame_samples
        self.q: queue.Queue[np.ndarray] = queue.Queue(maxsize=max_queue_frames)
        self.paused = False
        self.aec = aec
        self.far_end_buffer = far_end_buffer
        self._stream = sd.InputStream(
            device=device,
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=frame_samples,
            callback=self._cb,
        )

    def _apply_aec(self, near: np.ndarray) -> np.ndarray:
        """Run AEC on a captured frame if AEC + far-end buffer are wired."""
        if self.aec is None or self.far_end_buffer is None:
            return near
        far = self.far_end_buffer.pop_frame(len(near))
        try:
            return self.aec.process(near, far)
        except Exception as exc:
            print(f"[mic] AEC passthrough on error: {exc}", file=sys.stderr, flush=True)
            return near

    def _cb(self, indata, frames, time_info, status) -> None:
        if status:
            print(f"[mic] {status}", file=sys.stderr)
        if self.paused or frames != self.frame_samples:
            return
        sample = indata.copy()
        if self.aec is not None:
            # AEC is per-channel mono; reshape to 1D, process, reshape back.
            mono = sample[:, 0]
            clean = self._apply_aec(mono)
            sample = clean.reshape(-1, 1)
        try:
            self.q.put_nowait(sample)
        except queue.Full:
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
            try:
                self.q.put_nowait(sample)
            except queue.Full:
                pass

    def start(self) -> None:
        self._stream.start()

    def stop(self) -> None:
        try:
            self._stream.stop()
        finally:
            self._stream.close()

    def drain(self) -> None:
        with self.q.mutex:
            self.q.queue.clear()

    def set_paused(self, paused: bool) -> None:
        if paused == self.paused:
            return
        self.paused = paused
        if not paused:
            # Anything captured during the pause boundary is stale.
            self.drain()
