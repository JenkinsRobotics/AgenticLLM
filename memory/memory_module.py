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

import contextlib
import fcntl
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
FACTS_LOCK_PATH = ROOT / ".facts.lock"
EPISODIC_PATH = ROOT / "episodic.jsonl"

# Schema version for facts.json. Bump when the on-disk shape changes; old
# files are migrated transparently in `_read_facts` so existing installs
# never need a manual fix-up step.
SCHEMA_VERSION = 1


# In-process lock around facts.json writes. Cross-process safety is
# provided by `_facts_file_lock()` (fcntl flock), which serializes any
# process touching the same file regardless of how many threads each has.
_facts_lock = threading.Lock()


@contextlib.contextmanager
def _facts_file_lock(exclusive: bool = True) -> Any:
    """fcntl-backed advisory lock keyed on a dedicated lockfile.

    We don't lock facts.json itself because we rewrite it via atomic
    rename — the inode flips out from under any reader. A separate
    lockfile stays put across renames, so two writers from different
    processes serialize cleanly.
    """
    FACTS_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    flag = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    with open(FACTS_LOCK_PATH, "a+", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), flag)
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def load_identity() -> str:
    if not IDENTITY_PATH.exists():
        return ""
    return IDENTITY_PATH.read_text(encoding="utf-8").strip()


def _migrate_facts_shape(data: Any) -> dict[str, str]:
    """Accept any historical or current shape; return the facts dict.

    v0: flat {"key": "value", ...}
    v1: {"schema_version": 1, "facts": {"key": "value", ...}}
    """
    if not isinstance(data, dict):
        return {}
    if "schema_version" in data and isinstance(data.get("facts"), dict):
        return {k: v for k, v in data["facts"].items() if isinstance(k, str)}
    # v0 — flat shape. Treat every key as a fact, but drop reserved/private
    # keys that look like metadata so a future v2 doesn't collide.
    return {k: v for k, v in data.items() if isinstance(k, str) and not k.startswith("_")}


def _read_facts_locked() -> dict[str, str]:
    """Read facts.json without taking the flock (caller already holds it)."""
    if not FACTS_PATH.exists():
        return {}
    try:
        data = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return _migrate_facts_shape(data)


def _read_facts() -> dict[str, str]:
    if not FACTS_PATH.exists():
        return {}
    with _facts_file_lock(exclusive=False):
        return _read_facts_locked()


def _write_facts_atomic(facts: dict[str, str]) -> None:
    FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "facts": dict(facts)}
    fd, tmp_path = tempfile.mkstemp(
        dir=FACTS_PATH.parent, prefix=".facts.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=True, sort_keys=True)
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
    with _facts_lock, _facts_file_lock(exclusive=True):
        facts = _read_facts_locked()
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
    with _facts_lock, _facts_file_lock(exclusive=True):
        facts = _read_facts_locked()
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


# ----------------------------------------------------------------------------
# Semantic search over episodic.jsonl. Lazy-loaded sentence-transformers
# index; rebuilt automatically when the jsonl line-count drifts from the
# cached embeddings. Zero perf cost when never called.
# ----------------------------------------------------------------------------
EMBED_PATH = ROOT / "episodic.embeddings.npz"
EMBED_MODEL_ID = os.environ.get("SEMANTIC_MEMORY_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

_semantic_state: dict[str, Any] = {
    "model": None,
    "model_id": None,
    "vectors": None,        # (N, dim) float32 numpy array
    "entries": None,        # list of (user, answer, timestamp) tuples, len N
    "indexed_lines": 0,     # how many jsonl lines we've indexed
}


def _ensure_semantic_model() -> Any:
    if _semantic_state["model"] is not None and _semantic_state["model_id"] == EMBED_MODEL_ID:
        return _semantic_state["model"]
    from sentence_transformers import SentenceTransformer

    import time as _t

    # Pin to CPU. The all-MiniLM model is tiny and CPU-fast (a few ms per
    # query); putting it on Apple Metal collides with llama-cpp's Metal
    # context and corrupts subsequent LLM decodes. CPU avoids the fight.
    started = _t.perf_counter()
    model = SentenceTransformer(EMBED_MODEL_ID, device="cpu")
    print(f"[semantic-memory] {EMBED_MODEL_ID} loaded on CPU in {_t.perf_counter() - started:.1f}s", flush=True)
    _semantic_state["model"] = model
    _semantic_state["model_id"] = EMBED_MODEL_ID
    return model


def _episodic_lines() -> int:
    if not EPISODIC_PATH.exists():
        return 0
    with EPISODIC_PATH.open("rb") as fh:
        return sum(1 for _ in fh)


def _load_or_build_index() -> tuple[Any, list[tuple[str, str, str]]]:
    """Return (vectors_ndarray, entries_list). Rebuild if cache is stale."""
    import numpy as np

    target_lines = _episodic_lines()
    cached_lines = _semantic_state.get("indexed_lines", 0)
    if (
        _semantic_state["vectors"] is not None
        and _semantic_state["entries"] is not None
        and cached_lines == target_lines
    ):
        return _semantic_state["vectors"], _semantic_state["entries"]

    # Try the on-disk cache first
    if EMBED_PATH.exists():
        try:
            data = np.load(EMBED_PATH, allow_pickle=True)
            if int(data["lines"]) == target_lines:
                _semantic_state["vectors"] = data["vectors"]
                _semantic_state["entries"] = list(data["entries"].tolist())
                _semantic_state["indexed_lines"] = target_lines
                return _semantic_state["vectors"], _semantic_state["entries"]
        except Exception:
            pass

    # Rebuild from scratch
    entries: list[tuple[str, str, str]] = []
    texts: list[str] = []
    if EPISODIC_PATH.exists():
        with EPISODIC_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                user = (e.get("user") or "").strip()
                answer = (e.get("answer") or "").strip()
                ts = (e.get("timestamp") or "").strip()
                if not user and not answer:
                    continue
                entries.append((user, answer, ts))
                texts.append(f"USER: {user}\nASSISTANT: {answer}".strip())

    if not entries:
        _semantic_state["vectors"] = None
        _semantic_state["entries"] = []
        _semantic_state["indexed_lines"] = target_lines
        return None, []

    model = _ensure_semantic_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    vectors = np.asarray(vectors, dtype="float32")
    _semantic_state["vectors"] = vectors
    _semantic_state["entries"] = entries
    _semantic_state["indexed_lines"] = target_lines

    try:
        np.savez(
            EMBED_PATH,
            vectors=vectors,
            entries=np.array(entries, dtype=object),
            lines=np.int64(target_lines),
        )
    except Exception:
        pass  # cache is best-effort
    return vectors, entries


def search_memory(query: str, k: int = 5) -> list[dict[str, Any]]:
    """Return up to k semantically-closest episodic entries for `query`.

    Each result has user / answer / timestamp / score (cosine, 0-1). The
    index is built lazily on first call from episodic.jsonl and cached on
    disk; subsequent calls reuse the cache until the jsonl line-count
    changes, at which point a rebuild is triggered transparently.
    """
    import numpy as np

    clean = (query or "").strip()
    if not clean:
        return []
    vectors, entries = _load_or_build_index()
    if vectors is None or not entries:
        return []

    model = _ensure_semantic_model()
    q_vec = np.asarray(
        model.encode([clean], normalize_embeddings=True, show_progress_bar=False),
        dtype="float32",
    )[0]
    scores = vectors @ q_vec  # cosine sim because all rows are unit-normed
    top_idx = scores.argsort()[::-1][: max(1, k)]
    out: list[dict[str, Any]] = []
    for i in top_idx:
        user, answer, ts = entries[int(i)]
        out.append({
            "user": user,
            "answer": answer,
            "timestamp": ts,
            "score": float(scores[int(i)]),
        })
    return out


# ----------------------------------------------------------------------------
# Cron-style scheduling for prompts the agent runs unattended.
# Storage = memory/schedules.jsonl (append-only); we mark a row as cancelled
# instead of mutating it so the log stays linear and auditable.
# ----------------------------------------------------------------------------
SCHEDULES_PATH = ROOT / "schedules.jsonl"
SCHEDULES_LOCK_PATH = ROOT / ".schedules.lock"


@contextlib.contextmanager
def _schedules_file_lock() -> Any:
    SCHEDULES_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEDULES_LOCK_PATH, "a+", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _read_schedules_raw() -> list[dict[str, Any]]:
    if not SCHEDULES_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    with SCHEDULES_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _live_schedules(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Reduce the append-only log to a name → latest-active-row map. A row
    with `cancelled=True` removes that name from the active set."""
    by_name: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.get("name")
        if not name:
            continue
        if row.get("cancelled"):
            by_name.pop(name, None)
        else:
            by_name[name] = row
    return by_name


def add_schedule(cron_expr: str, prompt: str, name: str | None = None) -> dict[str, Any]:
    """Schedule a prompt for unattended execution on a cron expression.

    `cron_expr` is standard 5-field cron ("0 7 * * *" for 7am daily).
    Returns the persisted row including a `next_run_at` derived from now.
    """
    from datetime import datetime, timezone

    from croniter import croniter

    cron_expr = (cron_expr or "").strip()
    prompt = (prompt or "").strip()
    if not cron_expr or not prompt:
        raise ValueError("cron_expr and prompt are required")
    if not croniter.is_valid(cron_expr):
        raise ValueError(f"invalid cron expression: {cron_expr!r}")

    now = datetime.now(timezone.utc)
    nxt = croniter(cron_expr, now).get_next(datetime)
    name = (name or f"sched_{int(now.timestamp())}").strip()

    row = {
        "name": name,
        "cron": cron_expr,
        "prompt": prompt,
        "created_at": now.isoformat(timespec="seconds"),
        "next_run_at": nxt.isoformat(timespec="seconds"),
        "last_run_at": None,
        "cancelled": False,
    }
    SCHEDULES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _schedules_file_lock(), SCHEDULES_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=True) + "\n")
    return row


def list_schedules() -> list[dict[str, Any]]:
    return list(_live_schedules(_read_schedules_raw()).values())


def cancel_schedule(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    with _schedules_file_lock():
        live = _live_schedules(_read_schedules_raw())
        if name not in live:
            return False
        from datetime import datetime, timezone
        row = {
            "name": name,
            "cancelled": True,
            "cancelled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with SCHEDULES_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")
    return True


def due_schedules(now: Any = None) -> list[dict[str, Any]]:
    """Return live schedules whose `next_run_at` has passed.

    Read-only; safe to call from any context. The CronRunner uses
    `claim_due_schedules` instead so two runners can coexist without
    double-firing the same schedule.
    """
    from datetime import datetime, timezone

    now = now or datetime.now(timezone.utc)
    if hasattr(now, "isoformat"):
        cutoff = now.isoformat(timespec="seconds")
    else:
        cutoff = str(now)
    return [
        row for row in _live_schedules(_read_schedules_raw()).values()
        if (row.get("next_run_at") or "") <= cutoff
    ]


def claim_due_schedules(now: Any = None) -> list[dict[str, Any]]:
    """Find every due schedule and atomically mark it as fired.

    Under the file lock we read the current live state, identify due rows,
    write the next-run-at update for each one (which makes it not-due for
    the next reader), then release the lock. Returned rows are the
    *original* row the caller should fire. Two CronRunners calling this
    concurrently will not both claim the same fire window — the second
    one sees the first one's update and finds zero due schedules.

    If the caller crashes after claim but before firing, that fire is
    silently lost. Acceptable for cron (better to miss a tick than
    double-send a "hey, check the weather" Discord message).
    """
    from datetime import datetime, timezone

    from croniter import croniter

    now = now or datetime.now(timezone.utc)
    cutoff = now.isoformat(timespec="seconds") if hasattr(now, "isoformat") else str(now)

    with _schedules_file_lock():
        live = _live_schedules(_read_schedules_raw())
        claimed: list[dict[str, Any]] = []
        if not live:
            return []
        with SCHEDULES_PATH.open("a", encoding="utf-8") as fh:
            for name, sched in live.items():
                if (sched.get("next_run_at") or "") > cutoff:
                    continue
                claimed.append(dict(sched))
                # Update row makes this schedule not-due until the next cron tick.
                try:
                    nxt = croniter(sched["cron"], now).get_next(datetime)
                except Exception:
                    continue
                update = {
                    "name": name,
                    "cron": sched["cron"],
                    "prompt": sched["prompt"],
                    "created_at": sched["created_at"],
                    "next_run_at": nxt.isoformat(timespec="seconds"),
                    "last_run_at": now.isoformat(timespec="seconds"),
                    "cancelled": False,
                }
                fh.write(json.dumps(update, ensure_ascii=True) + "\n")
        return claimed


def mark_schedule_ran(name: str) -> None:
    """Record that `name` ran just now and recompute its next_run_at."""
    from datetime import datetime, timezone

    from croniter import croniter

    with _schedules_file_lock():
        live = _live_schedules(_read_schedules_raw())
        sched = live.get(name)
        if not sched:
            return
        now = datetime.now(timezone.utc)
        nxt = croniter(sched["cron"], now).get_next(datetime)
        update = {
            "name": name,
            "cron": sched["cron"],
            "prompt": sched["prompt"],
            "created_at": sched["created_at"],
            "next_run_at": nxt.isoformat(timespec="seconds"),
            "last_run_at": now.isoformat(timespec="seconds"),
            "cancelled": False,
        }
        with SCHEDULES_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(update, ensure_ascii=True) + "\n")


def load_recent_turns(n: int = 5, session_key: str | None = None) -> list[dict[str, str]]:
    """Return the last N turns as a flat chat-history list.

    Output shape is OpenAI-style messages — pairs of {"role":"user", ...} and
    {"role":"assistant", ...}. The assistant content is the framework's raw
    decision (the JSON or <tool_call> the model emitted). That's enough for
    the model to see what keys/args it used in prior turns, which fixes the
    key-consistency issue without much prefill cost.

    When `session_key` is provided, only turns logged with that key are
    returned — used by the per-channel rolling-history feature so a
    Telegram chat doesn't see CLI turns when the gateway restarts.
    """
    if not EPISODIC_PATH.exists() or n <= 0:
        return []
    entries: list[dict[str, Any]] = []
    with EPISODIC_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if session_key is not None and entry.get("session_key") != session_key:
                continue
            entries.append(entry)
    messages: list[dict[str, str]] = []
    for entry in entries[-n:]:
        user = entry.get("user")
        decision_raw = entry.get("decision_raw")
        if user and decision_raw:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": decision_raw})
    return messages
