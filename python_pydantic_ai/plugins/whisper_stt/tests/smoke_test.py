"""Smoke test for the whisper_stt plugin.

Confirms importability without pywhispercpp / webrtcvad / sounddevice
installed AND without invoking microphone hardware. Both algorithmic
modes (two_pass + continuous) are checked.
"""

from __future__ import annotations


def test_default_alias_is_two_pass() -> None:
    from python_pydantic_ai.plugins.whisper_stt import WhisperSTT, WhisperSTTTwoPass
    assert WhisperSTT is WhisperSTTTwoPass


def test_both_modes_importable() -> None:
    """Both algorithm classes must import even when the heavy audio
    libraries aren't installed — SDK imports are deferred to __init__."""
    from python_pydantic_ai.plugins.whisper_stt import (
        WhisperSTTTwoPass, WhisperSTTContinuous,
    )
    assert WhisperSTTTwoPass is not None
    assert WhisperSTTContinuous is not None


def test_shared_helpers() -> None:
    """_base.py exports the shared utilities both modes use."""
    from python_pydantic_ai.plugins.whisper_stt._base import (
        DEFAULT_WAKE_PHRASES, _normalize, _find_wake_in_text, _MicStream,
    )
    assert "hey jaeger" in DEFAULT_WAKE_PHRASES
    assert "ok jaeger" in DEFAULT_WAKE_PHRASES
    assert any("yeager" in p or "yager" in p for p in DEFAULT_WAKE_PHRASES)
    assert "hey" in _normalize("Hey, Jaeger!")
    assert "jaeger" in _normalize("Hey, Jaeger!")
    matched, remainder = _find_wake_in_text(
        "hey jaeger what time is it",
        ("hey jaeger",),
        wake_match_threshold=0.78,
    )
    assert matched is True
    assert remainder == "what time is it"


if __name__ == "__main__":
    test_default_alias_is_two_pass()
    test_both_modes_importable()
    test_shared_helpers()
    print("whisper_stt plugin smoke: OK")
