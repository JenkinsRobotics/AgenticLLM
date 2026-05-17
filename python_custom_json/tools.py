"""Safe local tools for the agent test."""

from __future__ import annotations

import ast
import datetime as dt
import operator as op
import os
import platform
import re
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


def get_time(timezone: str | None = None) -> dict[str, Any]:
    """Current local date/time, or in a specific IANA timezone if provided.

    Examples: timezone="Asia/Shanghai", "America/New_York", "Europe/London".
    """
    if timezone:
        try:
            from zoneinfo import ZoneInfo

            now = dt.datetime.now(ZoneInfo(timezone))
        except Exception as exc:
            return {"error": f"unknown timezone: {timezone!r} ({exc})"}
    else:
        now = dt.datetime.now().astimezone()
    return {
        "datetime": now.strftime("%Y-%m-%d %I:%M:%S %p %Z"),
        "iso": now.isoformat(timespec="seconds"),
        "timezone": str(now.tzinfo),
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

        # Pass repo_id explicitly to suppress the "Defaulting repo_id..."
        # warning Kokoro emits on every fresh pipeline construction.
        _kokoro_pipeline = KPipeline(lang_code=KOKORO_LANG, repo_id="hexgrad/Kokoro-82M")
    return _kokoro_pipeline


def warm_kokoro() -> dict[str, Any]:
    """Pre-load Kokoro at process startup so the first user-facing speak()
    or speak_file() call doesn't pay the ~3-5 s weight-load tax."""
    started = time.perf_counter()
    try:
        pipe = _ensure_kokoro()
        # Iterate once to trigger any remaining lazy initialization inside
        # the pipeline. We don't actually play the audio.
        for _ in pipe(" ", voice=KOKORO_VOICE):
            break
    except Exception as exc:
        return {"warmed": False, "reason": str(exc)}
    return {"warmed": True, "seconds": round(time.perf_counter() - started, 3)}


# Minimal SSML-style markup supported by speak()/speak_file():
#   <speak>...</speak>            wrapper, stripped
#   <break time="200ms"/>          insert silence (ms or s units)
#   <breath/>                      short silent gap, mimics a breath
# Anything else falls through as plain text to Kokoro.
_SSML_SPEAK_TAG = re.compile(r"</?speak\s*>", re.IGNORECASE)
_SSML_TAG = re.compile(
    r'<break\s+time=["\'](\d+(?:\.\d+)?)\s*(ms|s)["\']\s*/?>|<breath\s*/?>',
    re.IGNORECASE,
)
_BREATH_GAP_MS = 220  # silent stand-in for a soft inhale


def _ssml_segments(text: str):
    """Yield ('text', str) | ('silence_ms', int) chunks. Pure parsing; no audio."""
    cleaned = _SSML_SPEAK_TAG.sub("", text)
    pos = 0
    for match in _SSML_TAG.finditer(cleaned):
        before = cleaned[pos:match.start()]
        if before.strip():
            yield ("text", before.strip())
        tag = match.group(0).lower()
        if tag.startswith("<break"):
            value = float(match.group(1))
            unit = match.group(2).lower()
            ms = int(value * 1000) if unit == "s" else int(value)
            yield ("silence_ms", ms)
        else:  # <breath/>
            yield ("silence_ms", _BREATH_GAP_MS)
        pos = match.end()
    tail = cleaned[pos:]
    if tail.strip():
        yield ("text", tail.strip())


def speak(text: str) -> dict[str, Any]:
    """Synthesize speech with Kokoro and play it through the default output.

    Supports minimal SSML: <speak>, <break time="Xms"/>, <breath/>. Plain text
    without tags takes the original fast path (single Kokoro call).
    """
    import numpy as np
    import sounddevice as sd

    cleaned = text.strip()
    if not cleaned:
        return {"spoken": False, "reason": "empty text"}

    pipe = _ensure_kokoro()
    started = time.perf_counter()
    chunks: list[Any] = []
    has_ssml = ("<break" in cleaned.lower()) or ("<breath" in cleaned.lower()) or ("<speak" in cleaned.lower())

    if has_ssml:
        for kind, value in _ssml_segments(cleaned):
            if kind == "text":
                for r in pipe(value, voice=KOKORO_VOICE):
                    if r.audio is not None:
                        chunks.append(np.asarray(r.audio, dtype=np.float32))
            else:  # silence_ms
                n = int(KOKORO_SAMPLE_RATE * value / 1000)
                if n > 0:
                    chunks.append(np.zeros(n, dtype=np.float32))
    else:
        for r in pipe(cleaned, voice=KOKORO_VOICE):
            if r.audio is not None:
                chunks.append(np.asarray(r.audio, dtype=np.float32))

    if not chunks:
        return {"spoken": False, "reason": "no audio generated"}

    audio = np.concatenate(chunks)
    device = _play_audio_with_live_device(sd, audio)
    if isinstance(device, dict):
        return {**device, "text": cleaned}
    return {
        "spoken": True,
        "text": cleaned,
        "chars": len(cleaned),
        "seconds": round(time.perf_counter() - started, 3),
        "ssml": has_ssml,
        "device": device,
    }


def _play_audio_with_live_device(sd, audio):
    """Play through the current system default output. Re-queries PortAudio
    each call so users can switch macOS audio output mid-session (AirPods
    ↔ Speakers) without restarting the chat. On failure, terminates and
    reinitializes PortAudio, then retries once."""
    device: int | None = None
    try:
        info = sd.query_devices(kind="output")
        if isinstance(info, dict) and "index" in info:
            device = int(info["index"])
    except Exception:
        device = None
    try:
        sd.play(audio, samplerate=KOKORO_SAMPLE_RATE, device=device)
        sd.wait()
        return device
    except Exception as first_exc:
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        try:
            info = sd.query_devices(kind="output")
            device = int(info["index"]) if isinstance(info, dict) and "index" in info else None
        except Exception:
            device = None
        try:
            sd.play(audio, samplerate=KOKORO_SAMPLE_RATE, device=device)
            sd.wait()
            return device
        except Exception as second_exc:
            return {
                "spoken": False,
                "reason": f"playback failed after reinit: {second_exc}",
                "first_error": str(first_exc),
                "device": device,
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


def remember(key: str, value: str) -> dict[str, Any]:
    """Store a fact in unified memory shared across all agent processes."""
    from .memory.memory_module import remember as _remember

    _remember(key, value)
    return {"remembered": True, "key": key, "value": value}


def recall(key: str) -> dict[str, Any]:
    """Retrieve a fact previously stored via remember()."""
    from .memory.memory_module import recall as _recall

    value = _recall(key)
    if value is None:
        return {"found": False, "key": key}
    return {"found": True, "key": key, "value": value}


def forget(key: str) -> dict[str, Any]:
    """Remove a stored fact. Returns whether it existed."""
    from .memory.memory_module import forget as _forget

    existed = _forget(key)
    return {"forgotten": existed, "key": key}


def list_facts() -> dict[str, Any]:
    """List every fact currently stored in unified memory."""
    from .memory.memory_module import list_facts as _list_facts

    return {"facts": _list_facts()}


def launch_url(url: str) -> dict[str, Any]:
    """Open a URL in the default web browser (macOS `open`)."""
    import subprocess

    clean = url.strip()
    if not (clean.startswith("http://") or clean.startswith("https://")):
        return {"error": "URL must start with http:// or https://", "url": clean}
    if platform.system() != "Darwin":
        return {"error": f"launch_url only supported on macOS (got {platform.system()})", "url": clean}
    try:
        result = subprocess.run(["open", clean], capture_output=True, timeout=5)
        if result.returncode != 0:
            return {"error": result.stderr.decode("utf-8", errors="replace")[:200], "url": clean}
    except Exception as exc:
        return {"error": str(exc), "url": clean}
    return {"opened": True, "url": clean}


def open_file(path: str) -> dict[str, Any]:
    """Open a workspace file in its default macOS app."""
    import subprocess

    target = workspace_path(path)
    if not target.exists():
        return {"error": "file not found", "path": path}
    if platform.system() != "Darwin":
        return {"error": f"open_file only supported on macOS (got {platform.system()})", "path": str(target)}
    try:
        result = subprocess.run(["open", str(target)], capture_output=True, timeout=5)
        if result.returncode != 0:
            return {"error": result.stderr.decode("utf-8", errors="replace")[:200], "path": str(target)}
    except Exception as exc:
        return {"error": str(exc), "path": str(target)}
    return {"opened": True, "path": str(target.relative_to(WORKSPACE))}


def open_app(app_name: str) -> dict[str, Any]:
    """Launch a macOS application by name (e.g. 'Safari', 'Notes', 'Terminal')."""
    import subprocess

    clean = app_name.strip()
    if not clean:
        return {"error": "empty app name"}
    if platform.system() != "Darwin":
        return {"error": f"open_app only supported on macOS (got {platform.system()})", "app": clean}
    try:
        result = subprocess.run(["open", "-a", clean], capture_output=True, timeout=5)
        if result.returncode != 0:
            return {"error": result.stderr.decode("utf-8", errors="replace")[:200], "app": clean}
    except Exception as exc:
        return {"error": str(exc), "app": clean}
    return {"opened": True, "app": clean}


def get_weather(location: str) -> dict[str, Any]:
    """Look up current weather at a location via wttr.in (no API key)."""
    clean = location.strip()
    if not clean:
        return {"error": "empty location"}
    try:
        import certifi
        import requests
    except ImportError as exc:
        return {"error": f"requests/certifi missing: {exc}", "location": clean}
    fmt = "%C+%t+(feels+%f),+humidity+%h,+wind+%w"
    url = f"https://wttr.in/{clean}"
    try:
        response = requests.get(
            url,
            params={"format": fmt},
            headers={"User-Agent": "AgenticLLM/0.1 (curl)"},
            timeout=10,
            verify=certifi.where(),
        )
        text = response.text.strip()
    except Exception as exc:
        return {"error": str(exc), "location": clean}
    if not text or text.lower().startswith("unknown location") or "<html" in text.lower():
        return {"error": "unknown location", "location": clean}
    # wttr.in's format string uses literal '+' as space; collapse runs.
    pretty = re.sub(r"\s+", " ", text.replace("+", " ")).strip()
    return {"location": clean, "weather": pretty}


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
