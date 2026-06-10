"""v3 skill registry — discovery + smoke-test gating + registration.

Re-exports skill_loader's public surface so consumers can do
``from python_jaeger.agent.skill_registry import load_and_register``.
"""
from .skill_loader import *  # noqa: F401,F403
from .skill_loader import (  # noqa: F401
    discover_skills,
    load_and_register,
)
