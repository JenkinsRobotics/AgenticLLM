"""Smoke test for the kokoro_tts plugin.

Confirms importability without kokoro installed AND without invoking
hardware. Actual TTS synthesis is NOT tested here — it requires the
~80 MB Kokoro weights download and a speaker.
"""

from __future__ import annotations


def test_node_class_importable() -> None:
    """The KokoroTTS class should import cleanly. Kokoro library import is
    deferred to _ensure_pipeline(), so the class can be loaded without the
    SDK installed."""
    from python_jaeger.plugins.kokoro_tts import KokoroTTS

    assert KokoroTTS is not None
    tts = KokoroTTS()
    assert tts.voice == "af_heart"
    assert tts.lang == "a"
    assert tts._pipeline is None  # lazy — not loaded until warm()/speak()


def test_constants_exported() -> None:
    """Module-level constants are part of the public surface."""
    from python_jaeger.plugins.kokoro_tts import (
        KOKORO_VOICE, KOKORO_LANG, KOKORO_SAMPLE_RATE,
    )
    assert KOKORO_VOICE == "af_heart"
    assert KOKORO_LANG == "a"
    assert KOKORO_SAMPLE_RATE == 24000


if __name__ == "__main__":
    test_node_class_importable()
    test_constants_exported()
    print("kokoro_tts plugin smoke: OK")
