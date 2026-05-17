"""Memory skills — talk to the framework-local memory store.

  • remember / recall / forget / list_facts — atomic k/v in facts.json
  • search_memory — semantic search over episodic.jsonl

Imports through the .memory subpackage (the data layer), not directly
from the project root. forget is approval-gated when
DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1.
"""

from __future__ import annotations

from typing import Any

from ._common import destructive_confirm_required


def remember(key: str, value: str) -> dict[str, Any]:
    """Store a fact in unified memory shared across all agent processes."""
    from ...memory.memory_module import remember as _remember

    _remember(key, value)
    return {"remembered": True, "key": key, "value": value}


def recall(key: str) -> dict[str, Any]:
    """Retrieve a fact previously stored via remember()."""
    from ...memory.memory_module import recall as _recall

    value = _recall(key)
    if value is None:
        return {"found": False, "key": key}
    return {"found": True, "key": key, "value": value}


def forget(key: str, confirm: bool = False) -> dict[str, Any]:
    """Remove a stored fact. Returns whether it existed.

    Same approval-gate semantics as `delete_file`: when
    DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1, the first call previews and the
    agent must call `ask_user` + then call again with `confirm=True`.
    """
    from ...memory.memory_module import forget as _forget, recall as _recall

    if destructive_confirm_required() and not confirm:
        existing = _recall(key)
        if existing is None:
            return {"forgotten": False, "preview": True, "key": key, "reason": "no such key"}
        return {
            "forgotten": False,
            "preview": True,
            "key": key,
            "current_value": existing,
            "hint": "Ask the user to confirm, then call forget again with confirm=True.",
        }

    existed = _forget(key)
    return {"forgotten": existed, "key": key}


def list_facts() -> dict[str, Any]:
    """List every fact currently stored in unified memory."""
    from ...memory.memory_module import list_facts as _list_facts

    return {"facts": _list_facts()}


def search_memory(query: str, k: int = 5) -> dict[str, Any]:
    """Semantic search over our cross-session episodic log.

    Use this when the user asks about something past — "what did we talk
    about yesterday?", "did I tell you about my dog?", "what's that thing
    we were doing with the printer?" — and `recall` (exact-key) misses.

    Returns the top-k most relevant past turns with cosine scores.
    """
    from ...memory.memory_module import search_memory as _search

    clean = (query or "").strip()
    if not clean:
        return {"found": 0, "results": []}
    hits = _search(clean, k=k)
    return {"found": len(hits), "query": clean, "results": hits}
