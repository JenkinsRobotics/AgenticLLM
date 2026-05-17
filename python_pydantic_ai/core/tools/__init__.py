"""Skills package — tools the agent can call.

One file per category, all re-exported here as a flat surface. Use either
form:

    from python_pydantic_ai import skills            # then skills.get_time(...)
    from python_pydantic_ai.skills import get_time   # direct import

Categories (see each file for details):

  • _common.py        — workspace path resolution, destructive-op gate
  • time_and_math.py  — get_time, calculate, system_status
  • files.py          — create_file, append_file, delete_file, read_file,
                        list_directory, launch_url, open_file, open_app
  • memory.py         — remember, recall, forget, list_facts, search_memory
  • speak.py          — speak, speak_file, warm_kokoro
  • web.py            — web_search, get_weather
  • code.py           — run_python
  • vision.py         — look_at, generate_image
  • scheduling.py     — schedule_prompt, list_schedules, cancel_schedule
  • messaging.py      — send_message (sender side; bridges live in plugins/)
  • delegation.py     — ask_user, help_me (delegate is in main.py)
"""

from __future__ import annotations

# Shared helpers
from ._common import (
    WORKSPACE,
    destructive_confirm_required,
    ensure_workspace,
    workspace_path,
)

# Time, math, status
from .time_and_math import calculate, get_time, system_status

# Files + macOS host control
from .files import (
    append_file,
    create_file,
    delete_file,
    launch_url,
    list_directory,
    open_app,
    open_file,
    read_file,
)

# Memory (k/v + semantic)
from .memory import forget, list_facts, recall, remember, search_memory

# TTS
from .speak import (
    KOKORO_LANG,
    KOKORO_SAMPLE_RATE,
    KOKORO_VOICE,
    speak,
    speak_file,
    warm_kokoro,
)

# Web
from .web import get_weather, web_search

# Code execution
from .code import run_python

# Vision
from .vision import generate_image, look_at

# Scheduling
from .scheduling import cancel_schedule, list_schedules, schedule_prompt

# Messaging (sender side)
from .messaging import send_message

# Coordination / meta
from .delegation import CAPABILITY_SUMMARY, ask_user, help_me


__all__ = [
    # _common
    "WORKSPACE", "ensure_workspace", "workspace_path", "destructive_confirm_required",
    # time_and_math
    "get_time", "calculate", "system_status",
    # files
    "create_file", "append_file", "delete_file", "read_file", "list_directory",
    "launch_url", "open_file", "open_app",
    # memory
    "remember", "recall", "forget", "list_facts", "search_memory",
    # speak
    "speak", "speak_file", "warm_kokoro",
    "KOKORO_VOICE", "KOKORO_LANG", "KOKORO_SAMPLE_RATE",
    # web
    "web_search", "get_weather",
    # code
    "run_python",
    # vision
    "look_at", "generate_image",
    # scheduling
    "schedule_prompt", "list_schedules", "cancel_schedule",
    # messaging
    "send_message",
    # delegation
    "ask_user", "help_me", "CAPABILITY_SUMMARY",
]
