"""Operational maintenance for our growing log files.

Two concerns:
  1. `python_*/logs/latency.jsonl` accumulates one row per bench/chat turn.
     Solved with simple file-size rotation (`latency.jsonl` → `.1` → `.2`).
  2. `memory/episodic.jsonl` accumulates one row per cross-session turn.
     Old entries are moved to `memory/archive/episodic.YYYY-MM.jsonl` and a
     compact pointer is appended to `memory/summaries.jsonl`.

Neither runs automatically on hot paths — call this module explicitly:
    python -m memory.maintenance --rotate-logs
    python -m memory.maintenance --consolidate-episodic --keep-days 30
    python -m memory.maintenance --all              # both, default thresholds
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


# After the M3 split, memory/ now lives inside each framework's package
# (e.g. python_pydantic_ai/memory/maintenance.py). The project root is
# three parents up — agent/ → pydantic_ai/ → repo root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MEMORY_ROOT = Path(__file__).resolve().parent
EPISODIC_PATH = MEMORY_ROOT / "episodic.jsonl"
SUMMARIES_PATH = MEMORY_ROOT / "summaries.jsonl"
ARCHIVE_DIR = MEMORY_ROOT / "archive"

DEFAULT_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
DEFAULT_KEEP_ROTATIONS = 5
DEFAULT_KEEP_DAYS = 30

LATENCY_LOG_PATHS = [
    PROJECT_ROOT / "python_custom_json" / "logs" / "latency.jsonl",
    PROJECT_ROOT / "python_hermes_xml" / "logs" / "latency.jsonl",
    PROJECT_ROOT / "python_pydantic_ai" / "logs" / "latency.jsonl",
]


# ----------------------------------------------------------------------------
# Log rotation
# ----------------------------------------------------------------------------
def rotate_log(path: Path, max_bytes: int = DEFAULT_MAX_BYTES, keep: int = DEFAULT_KEEP_ROTATIONS) -> bool:
    """Rotate `path` if it exceeds max_bytes. Returns True iff rotation happened."""
    if not path.exists() or path.stat().st_size < max_bytes:
        return False

    # Shift existing rotations: .N-1 → .N, dropping the oldest if full.
    oldest = path.with_suffix(path.suffix + f".{keep}")
    if oldest.exists():
        oldest.unlink()
    for i in range(keep - 1, 0, -1):
        src = path.with_suffix(path.suffix + f".{i}")
        dst = path.with_suffix(path.suffix + f".{i+1}")
        if src.exists():
            src.rename(dst)
    path.rename(path.with_suffix(path.suffix + ".1"))
    return True


def rotate_known_logs(max_bytes: int = DEFAULT_MAX_BYTES) -> list[dict[str, Any]]:
    """Rotate every project log we know about."""
    out: list[dict[str, Any]] = []
    for p in LATENCY_LOG_PATHS:
        rotated = rotate_log(p, max_bytes=max_bytes)
        if p.exists():
            out.append({
                "path": str(p.relative_to(PROJECT_ROOT)),
                "rotated": rotated,
                "size_bytes": p.stat().st_size,
            })
    return out


# ----------------------------------------------------------------------------
# Episodic consolidation
# ----------------------------------------------------------------------------
def _parse_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def consolidate_episodic(keep_days: int = DEFAULT_KEEP_DAYS) -> dict[str, Any]:
    """Move episodic entries older than `keep_days` into a dated archive.

    Returns a summary dict: how many entries were archived, archive paths,
    and the date range covered.
    """
    if not EPISODIC_PATH.exists():
        return {"archived": 0, "kept": 0, "archives": []}

    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    kept: list[dict[str, Any]] = []
    by_month: dict[str, list[dict[str, Any]]] = defaultdict(list)
    earliest: datetime | None = None
    latest: datetime | None = None

    with EPISODIC_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = _parse_ts(entry.get("timestamp"))
            if ts is None or ts >= cutoff:
                kept.append(entry)
                continue
            bucket = ts.strftime("%Y-%m")
            by_month[bucket].append(entry)
            if earliest is None or ts < earliest:
                earliest = ts
            if latest is None or ts > latest:
                latest = ts

    if not by_month:
        return {"archived": 0, "kept": len(kept), "archives": []}

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archives: list[dict[str, Any]] = []
    archived_total = 0
    for bucket, rows in sorted(by_month.items()):
        archive_path = ARCHIVE_DIR / f"episodic.{bucket}.jsonl"
        with archive_path.open("a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=True) + "\n")
        archives.append({"path": str(archive_path.relative_to(MEMORY_ROOT)), "added": len(rows)})
        archived_total += len(rows)

    # Rewrite the live episodic with only the kept entries (atomic).
    tmp = EPISODIC_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in kept:
            fh.write(json.dumps(row, ensure_ascii=True) + "\n")
    tmp.replace(EPISODIC_PATH)

    # Drop a pointer into summaries.jsonl so future tooling can find the archive.
    summary_entry = {
        "kind": "episodic_archive",
        "consolidated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "earliest": earliest.isoformat() if earliest else None,
        "latest": latest.isoformat() if latest else None,
        "archived_entries": archived_total,
        "archives": archives,
        "keep_days": keep_days,
    }
    with SUMMARIES_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary_entry, ensure_ascii=True) + "\n")

    return {
        "archived": archived_total,
        "kept": len(kept),
        "archives": archives,
        "earliest": earliest.isoformat() if earliest else None,
        "latest": latest.isoformat() if latest else None,
    }


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rotate-logs", action="store_true", help="Rotate over-sized latency logs.")
    p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES, help="Rotation threshold.")
    p.add_argument("--consolidate-episodic", action="store_true", help="Archive old episodic turns.")
    p.add_argument("--keep-days", type=int, default=DEFAULT_KEEP_DAYS, help="Keep episodic entries newer than this.")
    p.add_argument("--all", action="store_true", help="Run both --rotate-logs and --consolidate-episodic.")
    args = p.parse_args()

    did_anything = False
    if args.rotate_logs or args.all:
        report = rotate_known_logs(max_bytes=args.max_bytes)
        rotated = [r for r in report if r["rotated"]]
        print(f"[maintenance] log rotation: {len(rotated)} rotated, {len(report) - len(rotated)} under threshold")
        for r in report:
            print(f"  {r['path']}: {r['size_bytes']:,} bytes  rotated={r['rotated']}")
        did_anything = True
    if args.consolidate_episodic or args.all:
        report = consolidate_episodic(keep_days=args.keep_days)
        print(f"[maintenance] episodic consolidation: archived {report['archived']} entries, kept {report['kept']}")
        for arc in report["archives"]:
            print(f"  → {arc['path']} (+{arc['added']})")
        did_anything = True

    if not did_anything:
        p.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
