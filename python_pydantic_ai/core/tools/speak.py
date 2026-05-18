"""Text-to-speech tool shims — delegate to the kokoro_tts plugin.

  • speak(text)        — synthesize + play through the default output device
  • speak_file(path)   — read a workspace file and narrate it
  • warm_kokoro()      — pre-load the Kokoro pipeline at startup

Under the vocabulary contract, the actual Kokoro pipeline + sounddevice
playback lives in `python_pydantic_ai/plugins/kokoro_tts/` (it bridges to
an external library + hardware → Plugin). The functions here are the
agent-callable Tool surface — `main.py` registers `speak()` / `speak_file()`
/ `warm_kokoro()` with the agent, and those wrappers call into here.

The sandbox check for `speak_file()` stays in core because the file
resolution must be enforced regardless of which TTS backend is active.

Module-level constants are re-exported from the plugin so existing callers
that imported them from this module keep working.
"""

from __future__ import annotations

from typing import Any

from ._common import WORKSPACE, workspace_path

# Re-export plugin constants so existing imports keep working.
from ...plugins.kokoro_tts import (
    KOKORO_LANG,
    KOKORO_SAMPLE_RATE,
    KOKORO_VOICE,
    KokoroTTS,
)


# Single shared instance — Kokoro's pipeline isn't designed for concurrent
# use, and the agent's tool surface serializes through the LLM lock anyway.
_tts: KokoroTTS | None = None


def _get_tts() -> KokoroTTS:
    global _tts
    if _tts is None:
        _tts = KokoroTTS(voice=KOKORO_VOICE, lang=KOKORO_LANG)
    return _tts


def warm_kokoro() -> dict[str, Any]:
    """Pre-load Kokoro so the first speak() doesn't pay the ~3–5 s
    weight-load tax. Idempotent."""
    return _get_tts().warm()


def speak(text: str) -> dict[str, Any]:
    """Synthesize speech with Kokoro and play through the default output.
    Supports minimal SSML: <speak>, <break time="Xms"/>, <breath/>."""
    return _get_tts().speak(text)


def speak_file(path: str) -> dict[str, Any]:
    """Read a workspace file and speak its contents through Kokoro.

    The sandbox check (workspace_path) stays in core rather than in the
    plugin so swapping out the TTS backend doesn't accidentally relax
    file-access boundaries."""
    target = workspace_path(path)
    if not target.exists() or not target.is_file():
        return {"spoken": False, "reason": "file not found", "path": path}
    text = target.read_text(encoding="utf-8")
    result = _get_tts().speak(text)
    result["from_file"] = str(target.relative_to(WORKSPACE))
    return result
