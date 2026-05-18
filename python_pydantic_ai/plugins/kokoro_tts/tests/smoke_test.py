"""Smoke test for the kokoro_tts plugin.

Confirms importability without kokoro installed AND without invoking
hardware. Actual TTS synthesis is NOT tested here.
"""

from __future__ import annotations


def test_node_class_importable() -> None:
    from python_pydantic_ai.plugins.kokoro_tts import KokoroTTS

    assert KokoroTTS is not None
    tts = KokoroTTS()
    assert tts.voice == "af_heart"
    assert tts.lang == "a"
    assert tts._pipeline is None  # lazy


def test_constants_exported() -> None:
    from python_pydantic_ai.plugins.kokoro_tts import (
        KOKORO_VOICE, KOKORO_LANG, KOKORO_SAMPLE_RATE,
    )
    assert KOKORO_VOICE == "af_heart"
    assert KOKORO_LANG == "a"
    assert KOKORO_SAMPLE_RATE == 24000


if __name__ == "__main__":
    test_node_class_importable()
    test_constants_exported()
    print("kokoro_tts plugin smoke: OK")
