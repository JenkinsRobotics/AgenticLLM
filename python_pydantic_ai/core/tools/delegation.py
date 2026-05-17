"""Meta / coordination skills.

  • ask_user(question)  — request clarification rather than guess
  • help_me()           — capability overview the agent can hand back

Note: `delegate(subtask)` lives in main.py (not here) because it
recursively invokes the same agent loop and needs the client reference
threaded through `_pipeline`.
"""

from __future__ import annotations

from typing import Any


CAPABILITY_SUMMARY = (
    "Capability overview (call `help_me` for the full list with examples):\n"
    "  • Time, math, system status — get_time, calculate, system_status\n"
    "  • Files (sandboxed workspace) — create_file, append_file, read_file,\n"
    "    list_directory, delete_file, open_file\n"
    "  • Web — web_search, get_weather, launch_url\n"
    "  • Memory — remember, recall, list_facts, forget, search_memory\n"
    "  • Voice (Kokoro TTS) — speak, speak_file\n"
    "  • Vision / image gen — look_at, generate_image\n"
    "  • Code — run_python (sandboxed subprocess, 10 s timeout)\n"
    "  • macOS — open_app, open_file, launch_url\n"
    "  • Scheduling — schedule_prompt, list_schedules, cancel_schedule\n"
    "  • Messaging — send_message (telegram / discord / imessage bridges)\n"
    "  • Sub-agents — delegate(subtask) for parallel/independent work\n"
    "  • Clarify — ask_user(question) when intent is ambiguous\n"
)


def ask_user(question: str) -> dict[str, Any]:
    """Ask the user a clarifying question instead of guessing.

    The agent should call this whenever it's about to guess at the user's
    intent — ambiguous pronouns, missing destination, "the file" with no
    name, "open it" with no antecedent. The voice loop will speak the
    question; the next phrase from the mic becomes the user's answer.
    Returns a marker so the harness knows this turn ended on a question
    rather than a normal answer.
    """
    clean = (question or "").strip()
    if not clean:
        return {"asked": False, "error": "empty question"}
    return {"asked": True, "question": clean}


def help_me() -> dict[str, Any]:
    """Return a structured capability list and CLI command summary.

    The agent should call this when the user asks "what can you do?",
    "help", "what tools do you have?", etc. — the result is a clean,
    short summary that the agent should relay (verbatim) rather than
    inventing its own list of capabilities.
    """
    return {
        "summary": CAPABILITY_SUMMARY,
        "cli_commands": [
            "/help — show commands",
            "/latency [on|off] — toggle latency report",
            "/tools [on|off] — toggle tool-activity lines",
            "/setup — re-run the setup wizard",
            "/multi — multi-line input mode",
            "/quit — exit",
        ],
        "tip": (
            "Just describe what you want in plain English. The agent picks the "
            "right tool; you don't need to know the function names."
        ),
    }
