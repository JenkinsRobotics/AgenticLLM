"""Memory skills — k/v store + semantic search.

  • remember / recall / forget / list_facts  — atomic k/v in facts.json
  • search_memory(query, k)                  — semantic search over episodic.jsonl

The k/v ops are jaeger-native (instance-scoped facts.json). search_memory
is new in this parity port — uses the same shape as pydantic_ai's
search_memory, backed by the per-instance episodic log.
"""

from __future__ import annotations

from typing import Any

from .. import memory as mem


# ---------------------------------------------------------------------------
# K/V memory
# ---------------------------------------------------------------------------
def remember(key: str, value: str) -> dict[str, Any]:
    """Store a fact in the instance's persistent memory.

    Call proactively when the user shares a preference, identity fact,
    plan, or anything they might recall later. Acknowledging in free-text
    without calling this is forbidden — it lies."""
    mem.remember(key, value)
    return {"remembered": True, "key": key, "value": value}


def recall(key: str) -> dict[str, Any]:
    """Retrieve a fact previously stored via remember().

    Call BEFORE answering questions about what the user said earlier.
    The persisted store is the source of truth across sessions; short-
    term context is not. Fuzzy matching is supported."""
    value = mem.recall(key)
    if value is None:
        return {"found": False, "key": key}
    return {"found": True, "key": key, "value": value}


def forget(key: str) -> dict[str, Any]:
    """Remove a stored fact by key."""
    existed = mem.forget(key)
    return {"forgotten": existed, "key": key}


def list_facts() -> dict[str, Any]:
    """List every fact currently in instance memory."""
    return {"facts": mem.list_facts()}


# ---------------------------------------------------------------------------
# Semantic search over the episodic log
# ---------------------------------------------------------------------------
def search_memory(query: str, k: int = 5) -> dict[str, Any]:
    """Semantic search over the instance's episodic conversation log.

    Use when `recall` misses — natural questions like "what did we talk
    about yesterday?" or "what's that thing I mentioned about the
    printer?". Returns up to k past turns with cosine-similarity scores.

    Index is built lazily on first call from episodic.jsonl and cached
    on disk; subsequent calls reuse the cache until the log changes."""
    clean = (query or "").strip()
    if not clean:
        return {"found": 0, "results": []}
    try:
        hits = mem.search_memory(clean, k=k)
    except AttributeError:
        # Older memory module without semantic search — graceful fall-through.
        return {"found": 0, "results": [], "error": "search_memory not available in this build"}
    return {"found": len(hits), "query": clean, "results": hits}
