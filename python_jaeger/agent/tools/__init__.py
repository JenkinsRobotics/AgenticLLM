"""Built-in tools for Jaeger — one file per category.

Mirrors python_pydantic_ai/core/tools/ for cross-framework structural
parity. Use either form:

    from python_jaeger.core import tools             # then tools.get_time(...)
    from python_jaeger.agent.tools import get_time    # direct import

Categories:

  • _common.py        — bind() + audit log + sandbox resolver + git autocommit
  • files.py          — file_write, file_read, list_skill_dir  (sandboxed)
  • time_and_math.py  — get_time, calculate, system_status
  • memory.py         — remember, recall, forget, list_facts, search_memory
  • scheduling.py     — schedule_prompt, list_schedules, cancel_schedule
  • web.py            — web_search, get_weather
  • code.py           — run_python
  • speak.py          — speak, speak_file, warm_kokoro (Kokoro TTS)
  • vision.py         — look_at, generate_image (Moondream2 + SDXL-Turbo)
  • host.py           — launch_url, open_file, open_app (macOS)
  • credentials.py    — get_credential, list_credentials
  • delegation.py     — ask_user, help_me, delegate
"""

from __future__ import annotations

# Framework wiring (call bind() once at startup)
from ._common import (
    SandboxError,
    _audit,
    _require_layout,
    _resolve_under,
    bind,
    get_layout,
    git_autocommit,
)

# File ops (all sandboxed to <instance>/skills/)
from .files import append_file, delete_file, file_read, file_write, list_skill_dir

# Time / math / status
from .time_and_math import calculate, get_time, system_status

# Memory
from .memory import forget, list_facts, recall, remember, search_memory

# Scheduling
from .scheduling import cancel_schedule, list_schedules, schedule_prompt

# Web
from .web import get_weather, web_search

# Code execution
from .code import run_python

# Speak (TTS)
from .speak import (
    KOKORO_LANG,
    KOKORO_SAMPLE_RATE,
    KOKORO_VOICE,
    speak,
    speak_file,
    warm_kokoro,
)

# Vision
from .vision import generate_image, look_at

# macOS host control
from .host import launch_url, open_app, open_file

# Credentials
from .credentials import get_credential, list_credentials

# Coordination / meta
from .delegation import CAPABILITY_SUMMARY, ask_user, help_me


__all__ = [
    # framework wiring
    "bind", "get_layout",
    "SandboxError", "_audit", "_require_layout", "_resolve_under", "git_autocommit",
    # files
    "file_write", "file_read", "list_skill_dir", "append_file", "delete_file",
    # time_and_math
    "get_time", "calculate", "system_status",
    # memory
    "remember", "recall", "forget", "list_facts", "search_memory",
    # scheduling
    "schedule_prompt", "list_schedules", "cancel_schedule",
    # web
    "web_search", "get_weather",
    # code
    "run_python",
    # speak
    "speak", "speak_file", "warm_kokoro",
    "KOKORO_VOICE", "KOKORO_LANG", "KOKORO_SAMPLE_RATE",
    # vision
    "look_at", "generate_image",
    # host
    "launch_url", "open_file", "open_app",
    # credentials
    "get_credential", "list_credentials",
    # delegation
    "ask_user", "help_me", "CAPABILITY_SUMMARY",
]
