"""Reference skill — `say_hello`. Imported by the Jaeger skill loader at
startup. Use this as a template when writing new skills.

Every skill module exposes a top-level `register(agent)` function that
attaches one or more tools to the passed PydanticAI agent. Keep skills
self-contained — no reaching into other skills' internals.
"""

from __future__ import annotations

from typing import Any


def say_hello(name: str = "world") -> dict[str, Any]:
    """Return a friendly greeting. Reference skill — not for production use."""
    clean = (name or "world").strip() or "world"
    return {"greeting": f"Hello, {clean}!", "skill": "hello_v1"}


def register(agent: Any) -> None:
    """Wire `say_hello` onto the agent as a plain tool.

    Pydantic AI infers the schema from the function signature + docstring;
    no extra wiring needed. Skills that want richer types can import their
    own Pydantic models here.
    """
    @agent.tool_plain
    def hello(name: str = "world") -> dict[str, Any]:
        """Return a friendly greeting. Reference / demo skill only."""
        return say_hello(name=name)
