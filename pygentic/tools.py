"""Safe local tools for the agent test."""

from __future__ import annotations

import ast
import datetime as dt
import operator as op
import os
import platform
import shutil
import time
from pathlib import Path
from typing import Any


WORKSPACE = Path(__file__).resolve().parent / "workspace"

# Kokoro is loaded lazily on first speak() call so startup stays fast.
KOKORO_VOICE = "af_heart"
KOKORO_LANG = "a"
KOKORO_SAMPLE_RATE = 24000
_kokoro_pipeline: Any = None


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


def append_file(path: str, content: str) -> dict[str, Any]:
    target = workspace_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(content)
    return {
        "appended": True,
        "path": str(target.relative_to(WORKSPACE)),
        "bytes": len(content.encode("utf-8")),
    }


def delete_file(path: str) -> dict[str, Any]:
    target = workspace_path(path)
    if not target.exists():
        return {"deleted": False, "reason": "not found", "path": path}
    if target.is_dir():
        return {"deleted": False, "reason": "is a directory", "path": path}
    target.unlink()
    return {"deleted": True, "path": str(target.relative_to(WORKSPACE))}


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


_CALC_OPS: dict[type, Any] = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
}


def _calc_eval(node: Any) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_calc_eval(node.left), _calc_eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _CALC_OPS:
        return _CALC_OPS[type(node.op)](_calc_eval(node.operand))
    raise ValueError(f"unsupported expression: {ast.dump(node)}")


def calculate(expression: str) -> dict[str, Any]:
    tree = ast.parse(expression, mode="eval")
    result = _calc_eval(tree.body)
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return {"expression": expression, "result": result}


def _ensure_kokoro() -> Any:
    global _kokoro_pipeline
    if _kokoro_pipeline is None:
        from kokoro import KPipeline

        _kokoro_pipeline = KPipeline(lang_code=KOKORO_LANG)
    return _kokoro_pipeline


def speak(text: str) -> dict[str, Any]:
    """Synthesize speech with Kokoro and play it through the default output."""
    import numpy as np
    import sounddevice as sd

    cleaned = text.strip()
    if not cleaned:
        return {"spoken": False, "reason": "empty text"}

    pipe = _ensure_kokoro()
    started = time.perf_counter()
    chunks: list[Any] = []
    for r in pipe(cleaned, voice=KOKORO_VOICE):
        if r.audio is not None:
            chunks.append(np.asarray(r.audio, dtype=np.float32))
    if not chunks:
        return {"spoken": False, "reason": "no audio generated"}

    audio = np.concatenate(chunks)
    sd.play(audio, samplerate=KOKORO_SAMPLE_RATE)
    sd.wait()
    return {
        "spoken": True,
        "chars": len(cleaned),
        "seconds": round(time.perf_counter() - started, 3),
    }


def speak_file(path: str) -> dict[str, Any]:
    """Read a workspace file and speak its contents through Kokoro."""
    target = workspace_path(path)
    if not target.exists() or not target.is_file():
        return {"spoken": False, "reason": "file not found", "path": path}
    text = target.read_text(encoding="utf-8")
    result = speak(text)
    result["from_file"] = str(target.relative_to(WORKSPACE))
    return result


def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """DuckDuckGo HTML search. No API key required."""
    try:
        from ddgs import DDGS  # newer package name
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return {"error": "duckduckgo-search not installed", "query": query}

    cleaned = query.strip()
    if not cleaned:
        return {"error": "empty query"}

    try:
        with DDGS() as ddgs:
            raw = list(ddgs.text(cleaned, max_results=max_results))
    except Exception as exc:
        return {"error": str(exc), "query": cleaned}

    results = [
        {
            "title": item.get("title"),
            "url": item.get("href") or item.get("url"),
            "snippet": item.get("body") or item.get("snippet"),
        }
        for item in raw
    ]
    return {"query": cleaned, "results": results}


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
