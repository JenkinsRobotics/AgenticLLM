"""Kokoro TTS plugin — synthesizes speech via the Kokoro KPipeline and
plays through the system default audio output.

Bridges the agent to:
  • the `kokoro` library (Library)
  • Kokoro voice weight files (Model)
  • the speaker (Hardware)

The agent never imports this plugin directly. Instead, `core/tools/speak.py`
holds the thin shim that the agent calls (`speak(text)`, `speak_file(path)`,
`warm_kokoro()`); that shim delegates to `KokoroTTS` here.
"""

from __future__ import annotations

from .node import KokoroTTS, KOKORO_VOICE, KOKORO_LANG, KOKORO_SAMPLE_RATE

__all__ = ["KokoroTTS", "KOKORO_VOICE", "KOKORO_LANG", "KOKORO_SAMPLE_RATE"]
