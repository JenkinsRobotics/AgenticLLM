"""Safe local tools for the agent test."""

from __future__ import annotations

import datetime as dt
import os
import platform
import shutil
from pathlib import Path
from typing import Any


WORKSPACE = Path(__file__).resolve().parent / "workspace"


def ensure_workspace() -> None:
    WORKSPACE.mkdir(parents=True, exist_ok=True)


def workspace_path(path: str) -> Path:
    ensure_workspace()
    target = (WORKSPACE / path).resolve()
    if not target.is_relative_to(WORKSPACE):
        raise ValueError("path must stay inside agent_test/workspace")
    return target


def get_time() -> dict[str, Any]:
    now = dt.datetime.now().astimezone()
    return {
        "datetime": now.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
        "iso": now.isoformat(timespec="seconds"),
    }


def create_file(path: str, content: str) -> dict[str, Any]:
    target = workspace_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {
        "created": True,
        "path": str(target.relative_to(WORKSPACE)),
        "bytes": len(content.encode("utf-8")),
    }


def read_file(path: str) -> dict[str, Any]:
    target = workspace_path(path)
    return {
        "path": str(target.relative_to(WORKSPACE)),
        "content": target.read_text(encoding="utf-8"),
    }


def list_directory(path: str = ".") -> dict[str, Any]:
    target = workspace_path(path)
    if not target.exists():
        raise FileNotFoundError(str(target.relative_to(WORKSPACE)))
    if not target.is_dir():
        raise NotADirectoryError(str(target.relative_to(WORKSPACE)))

    entries = []
    for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        entries.append(
            {
                "name": child.name,
                "type": "directory" if child.is_dir() else "file",
                "bytes": child.stat().st_size if child.is_file() else None,
            }
        )
    return {"path": str(target.relative_to(WORKSPACE)), "entries": entries}


def system_status() -> dict[str, Any]:
    total, used, free = shutil.disk_usage(WORKSPACE)
    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "load_average": load_avg,
        "workspace": str(WORKSPACE),
        "disk": {
            "total_gb": round(total / 1024**3, 2),
            "used_gb": round(used / 1024**3, 2),
            "free_gb": round(free / 1024**3, 2),
        },
    }
