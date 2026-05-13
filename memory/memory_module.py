"""Shared persistent memory.

Three layers (only the first two are wired into tools today):

  1. identity.md   — stable persona, prepended to every framework's system
                     prompt at startup. Read-only during operation; edit the
                     file directly to change persona.
  2. facts.json    — key/value facts the agent curates via remember/recall.
                     Atomic writes via temp + rename so concurrent readers
                     never see a half-written file.
  3. episodic.jsonl — (future) append-only per-turn log across interfaces.

All paths live under memory/ at the project root so every framework and
future interface (voice, Discord, etc.) sees the same memory.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
IDENTITY_PATH = ROOT / "identity.md"
FACTS_PATH = ROOT / "facts.json"
EPISODIC_PATH = ROOT / "episodic.jsonl"


# In-process lock around facts.json writes. Cross-process writes are still
# safe via atomic rename; the lock just prevents one Python process from
# racing with itself if two threads call remember() concurrently.
_facts_lock = threading.Lock()


def load_identity() -> str:
    if not IDENTITY_PATH.exists():
        return ""
    return IDENTITY_PATH.read_text(encoding="utf-8").strip()


def _read_facts() -> dict[str, Any]:
    if not FACTS_PATH.exists():
        return {}
    try:
        data = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_facts_atomic(facts: dict[str, Any]) -> None:
    FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=FACTS_PATH.parent, prefix=".facts.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(facts, handle, indent=2, ensure_ascii=True, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, FACTS_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def remember(key: str, value: str) -> None:
    with _facts_lock:
        facts = _read_facts()
        facts[key] = value
        _write_facts_atomic(facts)


_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"my", "the", "a", "an", "is", "of", "do", "i", "what", "this", "that"}


def recall(key: str) -> str | None:
    """Retrieve a fact by key.

    Three matching strategies, tried in order:
      1. Exact match (case-sensitive).
      2. Case-insensitive substring match — `recall("video length")` finds
         a stored key `preferred_youtube_video_length`.
      3. Word-overlap match — `recall("my preferred video length")` still
         finds the same key by picking the stored key with the most
         significant-word overlap with the query.

    Returns None only when nothing meaningful matches. Stopwords
    (my, the, a, etc.) are excluded from word-overlap scoring.
    """
    facts = _read_facts()
    if not facts:
        return None

    # 1. Exact match
    if key in facts:
        return facts[key]

    # 2. Substring match (both directions of separator normalization)
    needle = key.lower().strip()
    needle_alt = needle.replace(" ", "_")
    for stored_key, stored_val in facts.items():
        normalized = stored_key.lower().replace("_", " ")
        if needle in normalized or needle_alt in stored_key.lower():
            return stored_val

    # 3. Word-overlap match
    needle_words = {w for w in _WORD_RE.findall(needle) if w not in _STOPWORDS}
    if not needle_words:
        return None
    best_key: str | None = None
    best_score = 0
    for stored_key in facts:
        stored_words = {
            w for w in _WORD_RE.findall(stored_key.lower().replace("_", " ")) if w not in _STOPWORDS
        }
        overlap = len(needle_words & stored_words)
        if overlap > best_score:
            best_score = overlap
            best_key = stored_key
    if best_key and best_score >= 1:
        return facts[best_key]
    return None


def forget(key: str) -> bool:
    with _facts_lock:
        facts = _read_facts()
        if key not in facts:
            return False
        del facts[key]
        _write_facts_atomic(facts)
    return True


def list_facts() -> dict[str, str]:
    return _read_facts()


def append_episodic(entry: dict[str, Any]) -> None:
    """Append a turn to the cross-interface episodic log.

    Append-only; concurrent appends from multiple processes are safe because
    each line is written in a single .write() call on a separate file handle.
    """
    EPISODIC_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EPISODIC_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def load_recent_turns(n: int = 5) -> list[dict[str, str]]:
    """Return the last N turns as a flat chat-history list.

    Output shape is OpenAI-style messages — pairs of {"role":"user", ...} and
    {"role":"assistant", ...}. The assistant content is the framework's raw
    decision (the JSON or <tool_call> the model emitted). That's enough for
    the model to see what keys/args it used in prior turns, which fixes the
    key-consistency issue without much prefill cost.
    """
    if not EPISODIC_PATH.exists() or n <= 0:
        return []
    entries: list[dict[str, Any]] = []
    with EPISODIC_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    messages: list[dict[str, str]] = []
    for entry in entries[-n:]:
        user = entry.get("user")
        decision_raw = entry.get("decision_raw")
        if user and decision_raw:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": decision_raw})
    return messages
