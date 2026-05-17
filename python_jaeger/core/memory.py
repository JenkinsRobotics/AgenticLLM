"""Instance-scoped persistent memory.

Everything lives under <instance>/memory/:
  facts.json       — key/value facts curated via remember()/recall()
  episodic.jsonl   — per-turn append-only log
  schedules.jsonl  — cron-style scheduled prompts (append + cancel rows)

No cross-imports from the project root — Jaeger owns its memory store.
The shapes mirror memory/memory_module.py at the project root, but the
files live inside each instance dir so two Jaeger instances on one host
never share state.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Per-process state — bound to one InstanceLayout at startup
# ---------------------------------------------------------------------------
_state: dict[str, Any] = {
    "facts_path": None,
    "episodic_path": None,
    "schedules_path": None,
    "facts_lock_path": None,
    "schedules_lock_path": None,
    "embed_path": None,           # semantic-search embedding cache
}


def bind(layout: Any) -> None:
    """Wire memory paths to a specific instance layout. Called once at
    startup by the agent loop; subsequent calls re-bind cleanly."""
    mem = layout.memory_dir
    mem.mkdir(parents=True, exist_ok=True)
    _state["facts_path"] = mem / "facts.json"
    _state["episodic_path"] = mem / "episodic.jsonl"
    _state["schedules_path"] = mem / "schedules.jsonl"
    _state["facts_lock_path"] = mem / ".facts.lock"
    _state["schedules_lock_path"] = mem / ".schedules.lock"
    _state["embed_path"] = mem / "episodic.embeddings.npz"


def _require(path_key: str) -> Path:
    p = _state.get(path_key)
    if p is None:
        raise RuntimeError("memory not bound — call python_jaeger.memory.bind(layout) first")
    return p


# ---------------------------------------------------------------------------
# fcntl-backed cross-process advisory locking
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _file_lock(lock_key: str, *, exclusive: bool = True):
    path = _require(lock_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    flag = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    with open(path, "a+", encoding="utf-8") as fh:
        try:
            fcntl.flock(fh.fileno(), flag)
            yield
        finally:
            with contextlib.suppress(OSError):
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


# ---------------------------------------------------------------------------
# facts.json
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 1


def _read_facts_raw() -> dict[str, str]:
    path = _require("facts_path")
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    if "schema_version" in data and isinstance(data.get("facts"), dict):
        return {k: v for k, v in data["facts"].items() if isinstance(k, str)}
    return {k: v for k, v in data.items() if isinstance(k, str) and not k.startswith("_")}


def _write_facts_atomic(facts: dict[str, str]) -> None:
    path = _require("facts_path")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "facts": dict(facts)}
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".facts.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=True, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_name)
        raise


def remember(key: str, value: str) -> None:
    with _lock, _file_lock("facts_lock_path"):
        facts = _read_facts_raw()
        facts[key] = value
        _write_facts_atomic(facts)


_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"my", "the", "a", "an", "is", "of", "do", "i", "what", "this", "that"}


def recall(key: str) -> str | None:
    with _file_lock("facts_lock_path", exclusive=False):
        facts = _read_facts_raw()
    if not facts:
        return None
    if key in facts:
        return facts[key]
    needle = key.lower().strip()
    needle_alt = needle.replace(" ", "_")
    for stored_key, stored_val in facts.items():
        normalized = stored_key.lower().replace("_", " ")
        if needle in normalized or needle_alt in stored_key.lower():
            return stored_val
    needle_words = {w for w in _WORD_RE.findall(needle) if w not in _STOPWORDS}
    if not needle_words:
        return None
    best_key, best = None, 0
    for stored_key in facts:
        stored_words = {
            w for w in _WORD_RE.findall(stored_key.lower().replace("_", " ")) if w not in _STOPWORDS
        }
        overlap = len(needle_words & stored_words)
        if overlap > best:
            best, best_key = overlap, stored_key
    return facts[best_key] if best_key and best >= 1 else None


def forget(key: str) -> bool:
    with _lock, _file_lock("facts_lock_path"):
        facts = _read_facts_raw()
        if key not in facts:
            return False
        del facts[key]
        _write_facts_atomic(facts)
    return True


def list_facts() -> dict[str, str]:
    with _file_lock("facts_lock_path", exclusive=False):
        return _read_facts_raw()


# ---------------------------------------------------------------------------
# episodic.jsonl
# ---------------------------------------------------------------------------
def append_episodic(entry: dict[str, Any]) -> None:
    path = _require("episodic_path")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True) + "\n")


def load_recent_turns(n: int = 5, session_key: str | None = None) -> list[dict[str, str]]:
    path = _require("episodic_path")
    if not path.exists() or n <= 0:
        return []
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if session_key is not None and e.get("session_key") != session_key:
                continue
            entries.append(e)
    messages: list[dict[str, str]] = []
    for e in entries[-n:]:
        user = e.get("user")
        decision_raw = e.get("decision_raw")
        if user and decision_raw:
            messages.append({"role": "user", "content": user})
            messages.append({"role": "assistant", "content": decision_raw})
    return messages


# ---------------------------------------------------------------------------
# Semantic search over episodic.jsonl
# ---------------------------------------------------------------------------
# Lazy-loaded sentence-transformers index; rebuilt automatically when the
# jsonl line-count drifts from the cached embeddings. Zero perf cost when
# never called. Ported from python_pydantic_ai.memory.memory_module so the
# two frameworks have the same shape.
EMBED_MODEL_ID = os.environ.get("SEMANTIC_MEMORY_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

_semantic_state: dict[str, Any] = {
    "model": None,
    "model_id": None,
    "vectors": None,        # (N, dim) float32 numpy array
    "entries": None,        # list of (user, answer, timestamp) tuples
    "indexed_lines": 0,     # how many jsonl lines we've indexed
}


def _ensure_semantic_model() -> Any:
    if _semantic_state["model"] is not None and _semantic_state["model_id"] == EMBED_MODEL_ID:
        return _semantic_state["model"]
    from sentence_transformers import SentenceTransformer

    import time as _t
    # Pin to CPU. The all-MiniLM model is tiny and CPU-fast (a few ms per
    # query); putting it on Apple Metal collides with llama-cpp's Metal
    # context and corrupts subsequent LLM decodes.
    started = _t.perf_counter()
    model = SentenceTransformer(EMBED_MODEL_ID, device="cpu")
    print(f"[semantic-memory] {EMBED_MODEL_ID} loaded on CPU in {_t.perf_counter() - started:.1f}s", flush=True)
    _semantic_state["model"] = model
    _semantic_state["model_id"] = EMBED_MODEL_ID
    return model


def _episodic_line_count() -> int:
    path = _require("episodic_path")
    if not path.exists():
        return 0
    with path.open("rb") as fh:
        return sum(1 for _ in fh)


def _load_or_build_index() -> tuple[Any, list[tuple[str, str, str]]]:
    """Return (vectors_ndarray, entries_list). Rebuild if cache is stale."""
    import numpy as np

    embed_path = _require("embed_path")
    episodic_path = _require("episodic_path")
    target_lines = _episodic_line_count()
    cached_lines = _semantic_state.get("indexed_lines", 0)
    if (
        _semantic_state["vectors"] is not None
        and _semantic_state["entries"] is not None
        and cached_lines == target_lines
    ):
        return _semantic_state["vectors"], _semantic_state["entries"]

    if embed_path.exists():
        try:
            data = np.load(embed_path, allow_pickle=True)
            if int(data["lines"]) == target_lines:
                _semantic_state["vectors"] = data["vectors"]
                _semantic_state["entries"] = list(data["entries"].tolist())
                _semantic_state["indexed_lines"] = target_lines
                return _semantic_state["vectors"], _semantic_state["entries"]
        except Exception:
            pass

    entries: list[tuple[str, str, str]] = []
    texts: list[str] = []
    if episodic_path.exists():
        with episodic_path.open("r", encoding="utf-8") as fh:
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
            embed_path, vectors=vectors,
            entries=np.array(entries, dtype=object),
            lines=np.int64(target_lines),
        )
    except Exception:
        pass  # cache is best-effort
    return vectors, entries


def search_memory(query: str, k: int = 5) -> list[dict[str, Any]]:
    """Return up to k semantically-closest episodic entries for `query`.

    Each result has user / answer / timestamp / score (cosine, 0-1).
    Index built lazily; cached on disk per-instance until the jsonl
    line-count changes.
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


# ---------------------------------------------------------------------------
# schedules.jsonl  (append + cancel + recompute next_run_at)
# ---------------------------------------------------------------------------
def _read_schedules_raw() -> list[dict[str, Any]]:
    path = _require("schedules_path")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _live_schedules(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
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
    path = _require("schedules_path")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock("schedules_lock_path"), path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=True) + "\n")
    return row


def list_schedules() -> list[dict[str, Any]]:
    return list(_live_schedules(_read_schedules_raw()).values())


def cancel_schedule(name: str) -> bool:
    name = (name or "").strip()
    if not name:
        return False
    path = _require("schedules_path")
    with _file_lock("schedules_lock_path"):
        live = _live_schedules(_read_schedules_raw())
        if name not in live:
            return False
        row = {
            "name": name,
            "cancelled": True,
            "cancelled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")
    return True


def claim_due_schedules(now: Any = None) -> list[dict[str, Any]]:
    """Atomically mark every due schedule as fired and return the originals.

    Same semantics as memory/memory_module.claim_due_schedules: two cron
    runners across processes won't double-fire because the update-row is
    written under the file lock.
    """
    from croniter import croniter

    now = now or datetime.now(timezone.utc)
    cutoff = now.isoformat(timespec="seconds") if hasattr(now, "isoformat") else str(now)
    path = _require("schedules_path")

    with _file_lock("schedules_lock_path"):
        live = _live_schedules(_read_schedules_raw())
        claimed: list[dict[str, Any]] = []
        if not live:
            return []
        with path.open("a", encoding="utf-8") as fh:
            for name, sched in live.items():
                if (sched.get("next_run_at") or "") > cutoff:
                    continue
                claimed.append(dict(sched))
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


# ---------------------------------------------------------------------------
# Identity (read-only here — wizard owns identity.yaml; the agent loop
# combines it with the v2 system prompt at startup, never via this module).
# ---------------------------------------------------------------------------
def load_identity_string(layout: Any) -> str:
    """Render identity.yaml into the prose blurb the agent sees in its
    system prompt: a few short lines naming the agent and its persona."""
    from .schemas import load_yaml, Identity

    if not layout.identity_path.exists():
        return ""
    try:
        ident: Identity = load_yaml(layout.identity_path, Identity)
    except Exception:
        return ""
    return (
        f"You are {ident.name}.\n"
        f"Role: {ident.role}\n"
        f"Voice: {ident.personality}"
    )
