"""Meta / coordination skills.

  • ask_user(question)     — request clarification rather than guess
  • help_me()              — capability overview

Note: `delegate` is defined in python_jaeger.main (not here) because it
needs access to the active client + _pipeline state for recursion.
"""

from __future__ import annotations

from typing import Any


def ask_user(question: str) -> dict[str, Any]:
    """Ask the user a clarifying question instead of guessing.

    Call whenever the request is ambiguous — missing names, unclear
    pronouns, missing destinations, two plausible interpretations.
    The voice loop will speak the question; the user's next phrase is
    the next turn's input."""
    clean = (question or "").strip()
    if not clean:
        return {"asked": False, "error": "empty question"}
    return {"asked": True, "question": clean}


CAPABILITY_SUMMARY = (
    "Jaeger built-in tools:\n"
    "  • Time / math / status — get_time, calculate, system_status\n"
    "  • Files (skills/ sandbox) — file_write, file_read, list_skill_dir\n"
    "  • Memory — remember, recall, list_facts, forget, search_memory\n"
    "  • Schedules — schedule_prompt, list_schedules, cancel_schedule\n"
    "  • Web — web_search, get_weather\n"
    "  • Code — run_python (sandboxed subprocess, 10 s timeout)\n"
    "  • Speak (Kokoro TTS) — speak, speak_file\n"
    "  • Vision / image gen — look_at, generate_image\n"
    "  • macOS host control — launch_url, open_file, open_app\n"
    "  • Credentials — get_credential, list_credentials (never echo values)\n"
    "  • Sub-agents — delegate(subtask) for parallel/independent work\n"
    "  • Skill management — reload_skills (call after writing new skill files)\n"
    "  • Clarify — ask_user\n"
    "Plus every skill registered from core skills/ and your instance's skills/.\n"
    "Author new skills by writing folders under skills/<name>_v<N>/ with\n"
    "SKILL.md + a module exposing register(agent) + tests/smoke_test.py."
)


def help_me() -> dict[str, Any]:
    """Capability summary — call when the user asks 'what can you do?'."""
    return {"summary": CAPABILITY_SUMMARY}
