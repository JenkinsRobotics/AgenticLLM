"""System-prompt assembly — re-exports prompts.py for back-compat."""
from .prompts import *  # noqa: F401,F403
from .prompts import build_system_prompt  # noqa: F401
