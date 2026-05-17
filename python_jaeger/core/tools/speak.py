"""Text-to-speech skills using Kokoro (ported from pydantic_ai/skills/speak.py).

  • speak(text)        — synthesize + play through the default output device
  • speak_file(path)   — read a workspace file and narrate it
  • warm_kokoro()      — pre-load the Kokoro pipeline (call at startup so
                         the first user-facing speak isn't penalized by
                         weight load)

Minimal SSML supported: <speak>, <break time="200ms"/>, <breath/>.
Anything else falls through as plain text to Kokoro.

In Jaeger, `speak_file(path)` reads from the SANDBOXED skills/ dir only
(via the same `_resolve_under` that file_read uses), so it can't be
used to leak credentials or arbitrary files outside the skills sandbox.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ._common import SandboxError, _require_layout, _resolve_under


# ---------------------------------------------------------------------------
# Kokoro pipeline — lazy-loaded so startup stays fast
# ---------------------------------------------------------------------------
KOKORO_VOICE = "af_heart"
KOKORO_LANG = "a"
KOKORO_SAMPLE_RATE = 24000
_kokoro_pipeline: Any = None


def _ensure_kokoro() -> Any:
    global _kokoro_pipeline
    if _kokoro_pipeline is None:
        from kokoro import KPipeline
        _kokoro_pipeline = KPipeline(lang_code=KOKORO_LANG, repo_id="hexgrad/Kokoro-82M")
    return _kokoro_pipeline


def warm_kokoro() -> dict[str, Any]:
    """Pre-load Kokoro so the first speak() call doesn't pay the
    ~3-5 s weight-load tax."""
    started = time.perf_counter()
    try:
        pipe = _ensure_kokoro()
        for _ in pipe(" ", voice=KOKORO_VOICE):
            break
    except Exception as exc:
        return {"warmed": False, "reason": str(exc)}
    return {"warmed": True, "seconds": round(time.perf_counter() - started, 3)}


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


# ---------------------------------------------------------------------------
# speak / speak_file
# ---------------------------------------------------------------------------
def speak(text: str) -> dict[str, Any]:
    """Synthesize speech with Kokoro and play through the default output.

    Supports minimal SSML: <speak>, <break time="Xms"/>, <breath/>."""
    import numpy as np
    import sounddevice as sd

    cleaned = text.strip()
    if not cleaned:
        return {"spoken": False, "reason": "empty text"}

    pipe = _ensure_kokoro()
    started = time.perf_counter()
    chunks: list[Any] = []
    has_ssml = ("<break" in cleaned.lower()) or ("<breath" in cleaned.lower()) or ("<speak" in cleaned.lower())

    if has_ssml:
        for kind, value in _ssml_segments(cleaned):
            if kind == "text":
                for r in pipe(value, voice=KOKORO_VOICE):
                    if r.audio is not None:
                        chunks.append(np.asarray(r.audio, dtype=np.float32))
            else:
                n = int(KOKORO_SAMPLE_RATE * value / 1000)
                if n > 0:
                    chunks.append(np.zeros(n, dtype=np.float32))
    else:
        for r in pipe(cleaned, voice=KOKORO_VOICE):
            if r.audio is not None:
                chunks.append(np.asarray(r.audio, dtype=np.float32))

    if not chunks:
        return {"spoken": False, "reason": "no audio generated"}

    audio = np.concatenate(chunks)
    device = _play_audio_with_live_device(sd, audio)
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


def _play_audio_with_live_device(sd, audio):
    """Play `audio` through the *current* system default output device,
    re-resolving each call so AirPods/Speakers swaps work mid-session."""
    device: int | None = None
    try:
        info = sd.query_devices(kind="output")
        if isinstance(info, dict) and "index" in info:
            device = int(info["index"])
    except Exception:
        device = None
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
        try:
            info = sd.query_devices(kind="output")
            device = int(info["index"]) if isinstance(info, dict) and "index" in info else None
        except Exception:
            device = None
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


def speak_file(path: str) -> dict[str, Any]:
    """Read a file from <instance>/skills/ and speak it through Kokoro.

    Path is sandbox-resolved through the same logic as file_read — must
    stay inside the instance's skills/ zone."""
    layout = _require_layout()
    try:
        target = _resolve_under(layout.skills_dir, path)
    except SandboxError as exc:
        return {"spoken": False, "reason": str(exc), "path": path}
    if not target.exists() or not target.is_file():
        return {"spoken": False, "reason": "file not found", "path": path}
    text = target.read_text(encoding="utf-8")
    result = speak(text)
    result["from_file"] = str(target.relative_to(layout.root))
    return result
