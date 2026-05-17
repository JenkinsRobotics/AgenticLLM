"""Jaeger built-in tools.

Self-contained: no imports from project-root `memory/`, `messaging/`, or
any other framework dir. All state lives under `<instance_dir>/`, accessed
through `python_jaeger.memory` and the `InstanceLayout` we bind at startup.

The sandboxed file tools (`file_write` / `file_read`) enforce the v2
contract:
  - Writes restricted to `<instance_dir>/skills/`, no path escapes.
  - Reads allowed anywhere under `<instance_dir>` EXCEPT `credentials/`.
  - Every write hits `logs/audit.log` so the human can see what the agent
    has authored.

Tools that depend on external services (web_search, weather) are kept;
tools that depended on the project-root messaging/memory infrastructure
are dropped from this M1 cut.
"""

from __future__ import annotations

import ast
import contextlib
import datetime as dt
import json
import operator as op
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import memory as mem
from .instance import InstanceLayout


# ---------------------------------------------------------------------------
# Module-level binding: which instance does this process serve?
# ---------------------------------------------------------------------------
_layout: InstanceLayout | None = None


def bind(layout: InstanceLayout) -> None:
    """Wire all tool I/O to a specific instance dir. Called once at startup."""
    global _layout
    _layout = layout
    mem.bind(layout)


def _require_layout() -> InstanceLayout:
    if _layout is None:
        raise RuntimeError("tools not bound — call python_jaeger.tools.bind(layout) first")
    return _layout


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def _audit(event: str, payload: dict[str, Any]) -> None:
    layout = _require_layout()
    layout.logs_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
        **payload,
    }
    with layout.audit_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True, default=str) + "\n")


# ---------------------------------------------------------------------------
# Sandboxed file tools — the heart of the v2 safety contract
# ---------------------------------------------------------------------------
class SandboxError(ValueError):
    """Raised when a path argument escapes the allowed zone."""


def _resolve_under(root: Path, path: str) -> Path:
    """Resolve `path` relative to `root` and verify the result lives inside
    `root`. Rejects absolute paths, `..` escapes, and symlinks that point
    outside the sandbox."""
    if not path:
        raise SandboxError("path must be non-empty")
    p = Path(path)
    if p.is_absolute():
        raise SandboxError("absolute paths are not allowed")
    if any(part == ".." for part in p.parts):
        raise SandboxError("'..' is not allowed in paths")

    full = (root / p).resolve()
    try:
        full.relative_to(root.resolve())
    except ValueError as exc:
        raise SandboxError(f"path escapes the sandbox: {path!r}") from exc
    return full


def file_write(path: str, content: str) -> dict[str, Any]:
    """Write a text file inside the instance's skills/ directory.

    Path is relative to <instance>/skills/. Refuses absolute paths, `..`
    escapes, symlinks that escape the sandbox, and any attempt to touch
    identity.yaml / config.yaml / manifest.json / credentials / memory /
    logs. Every write is recorded in logs/audit.log AND auto-committed
    to the instance's git repo (best-effort) so the agent's authorship
    history is a real audit trail.
    """
    layout = _require_layout()
    try:
        target = _resolve_under(layout.skills_dir, path)
    except SandboxError as exc:
        _audit("file_write_denied", {"path": path, "reason": str(exc)})
        return {"written": False, "error": str(exc)}

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    rel = str(target.relative_to(layout.root))
    bytes_written = len(content.encode("utf-8"))
    _audit("file_write", {"path": rel, "bytes": bytes_written})

    commit_sha = _git_autocommit(layout, rel, f"agent: write {rel}")
    result: dict[str, Any] = {"written": True, "path": rel, "bytes": bytes_written}
    if commit_sha:
        result["commit"] = commit_sha
    return result


def _git_autocommit(layout: InstanceLayout, rel_path: str, message: str) -> str | None:
    """Add + commit the agent-written file inside the instance's git repo.

    Best-effort: if git isn't available, or the repo wasn't initialized,
    or the staged content is unchanged, we silently return None. We never
    want a git hiccup to fail the agent's write — the on-disk content is
    the source of truth; git is the audit trail.
    """
    git_dir = layout.root / ".git"
    if not git_dir.exists() or shutil.which("git") is None:
        return None
    try:
        env = {
            "GIT_AUTHOR_NAME": "jaeger-agent",
            "GIT_AUTHOR_EMAIL": "agent@local",
            "GIT_COMMITTER_NAME": "jaeger-agent",
            "GIT_COMMITTER_EMAIL": "agent@local",
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(layout.root),
        }
        subprocess.run(
            ["git", "-C", str(layout.root), "add", rel_path],
            check=True, capture_output=True, timeout=5, env=env,
        )
        # `git commit` exits non-zero when there's nothing to commit
        # (file content unchanged). Treat that as a non-error: just no
        # new commit this turn.
        result = subprocess.run(
            ["git", "-C", str(layout.root), "commit", "-m", message],
            capture_output=True, timeout=5, env=env, text=True,
        )
        if result.returncode != 0:
            if "nothing to commit" in (result.stdout + result.stderr):
                return None
            _audit("git_commit_failed", {"path": rel_path, "stderr": result.stderr[:200]})
            return None
        sha = subprocess.run(
            ["git", "-C", str(layout.root), "rev-parse", "HEAD"],
            check=True, capture_output=True, timeout=5, text=True, env=env,
        ).stdout.strip()
        return sha[:12]
    except (subprocess.SubprocessError, OSError) as exc:
        _audit("git_commit_failed", {"path": rel_path, "error": str(exc)})
        return None


def file_read(path: str) -> dict[str, Any]:
    """Read a text file from anywhere under the instance dir EXCEPT
    credentials/.

    Use this to inspect identity/config/manifest, prior skills, and the
    contents of skills/. Reads of credentials/ are rejected with a hint
    pointing at `get_credential()` (which arrives in core v1.1, M2)."""
    layout = _require_layout()
    try:
        target = _resolve_under(layout.root, path)
    except SandboxError as exc:
        _audit("file_read_denied", {"path": path, "reason": str(exc)})
        return {"read": False, "error": str(exc)}

    try:
        target.relative_to(layout.credentials_dir.resolve())
        _audit("file_read_denied", {"path": path, "reason": "credentials are off-limits"})
        return {
            "read": False,
            "error": ("credentials/ is off-limits to direct reads. "
                      "Use get_credential(name) once the credential tool "
                      "lands in core v1.1."),
        }
    except ValueError:
        pass

    if not target.exists():
        return {"read": False, "error": "not found", "path": path}
    if target.is_dir():
        return {"read": False, "error": "is a directory", "path": path}
    content = target.read_text(encoding="utf-8")
    return {
        "read": True,
        "path": str(target.relative_to(layout.root)),
        "content": content,
        "bytes": len(content.encode("utf-8")),
    }


def list_skill_dir(path: str = ".") -> dict[str, Any]:
    """List files under skills/. Use this to discover existing skills
    before adding a new version (so the agent picks the right _vN suffix)."""
    layout = _require_layout()
    try:
        target = _resolve_under(layout.skills_dir, path) if path != "." else layout.skills_dir
    except SandboxError as exc:
        return {"listed": False, "error": str(exc)}
    if not target.exists():
        return {"listed": True, "path": path, "entries": []}
    if not target.is_dir():
        return {"listed": False, "error": "not a directory", "path": path}

    entries = []
    for child in sorted(target.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
        entries.append({
            "name": child.name,
            "type": "directory" if child.is_dir() else "file",
            "bytes": child.stat().st_size if child.is_file() else None,
        })
    return {"listed": True, "path": str(target.relative_to(layout.root)), "entries": entries}


# ---------------------------------------------------------------------------
# Boring helpers: time, math, system status
# ---------------------------------------------------------------------------
def get_time(timezone: str | None = None) -> dict[str, Any]:
    """Current local date/time, or in a specific IANA timezone if provided."""
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


_CALC_OPS: dict[type, Any] = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
    ast.Div: op.truediv, ast.Pow: op.pow, ast.Mod: op.mod,
    ast.FloorDiv: op.floordiv, ast.USub: op.neg, ast.UAdd: op.pos,
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
    """Evaluate a safe arithmetic expression (+ - * / ** % //)."""
    tree = ast.parse(expression, mode="eval")
    result = _calc_eval(tree.body)
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return {"expression": expression, "result": result}


def system_status() -> dict[str, Any]:
    layout = _require_layout()
    total, used, free = shutil.disk_usage(layout.root)
    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else None
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "load_average": load_avg,
        "instance": str(layout.root),
        "disk": {
            "total_gb": round(total / 1024**3, 2),
            "used_gb": round(used / 1024**3, 2),
            "free_gb": round(free / 1024**3, 2),
        },
    }


# ---------------------------------------------------------------------------
# Memory tools — instance-scoped
# ---------------------------------------------------------------------------
def remember(key: str, value: str) -> dict[str, Any]:
    mem.remember(key, value)
    return {"remembered": True, "key": key, "value": value}


def recall(key: str) -> dict[str, Any]:
    value = mem.recall(key)
    if value is None:
        return {"found": False, "key": key}
    return {"found": True, "key": key, "value": value}


def forget(key: str) -> dict[str, Any]:
    existed = mem.forget(key)
    return {"forgotten": existed, "key": key}


def list_facts() -> dict[str, Any]:
    return {"facts": mem.list_facts()}


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------
def schedule_prompt(cron_expr: str, prompt: str, name: str | None = None) -> dict[str, Any]:
    try:
        row = mem.add_schedule(cron_expr=cron_expr, prompt=prompt, name=name)
    except Exception as exc:
        return {"scheduled": False, "error": str(exc)}
    return {"scheduled": True, **row}


def list_schedules() -> dict[str, Any]:
    rows = mem.list_schedules()
    return {"count": len(rows), "schedules": rows}


def cancel_schedule(name: str) -> dict[str, Any]:
    ok = mem.cancel_schedule(name)
    return {"cancelled": ok, "name": name}


# ---------------------------------------------------------------------------
# Web / weather
# ---------------------------------------------------------------------------
def web_search(query: str, max_results: int = 5) -> dict[str, Any]:
    try:
        from ddgs import DDGS
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
    return {
        "query": cleaned,
        "results": [
            {
                "title": r.get("title"),
                "url": r.get("href") or r.get("url"),
                "snippet": r.get("body") or r.get("snippet"),
            }
            for r in raw
        ],
    }


def get_weather(location: str) -> dict[str, Any]:
    clean = location.strip()
    if not clean:
        return {"error": "empty location"}
    try:
        import certifi
        import requests
    except ImportError as exc:
        return {"error": f"requests/certifi missing: {exc}", "location": clean}
    fmt = "%C+%t+(feels+%f),+humidity+%h,+wind+%w"
    try:
        response = requests.get(
            f"https://wttr.in/{clean}",
            params={"format": fmt},
            headers={"User-Agent": "Jaeger/1.0"},
            timeout=10,
            verify=certifi.where(),
        )
        text = response.text.strip()
    except Exception as exc:
        return {"error": str(exc), "location": clean}
    if not text or text.lower().startswith("unknown location") or "<html" in text.lower():
        return {"error": "unknown location", "location": clean}
    pretty = re.sub(r"\s+", " ", text.replace("+", " ")).strip()
    return {"location": clean, "weather": pretty}


# ---------------------------------------------------------------------------
# Code execution — sandboxed subprocess
# ---------------------------------------------------------------------------
def run_python(code: str, timeout_s: float = 10.0) -> dict[str, Any]:
    """Execute a snippet of Python in an isolated subprocess.

    Fresh interpreter, fresh tempdir as cwd, 10s default timeout, 200KB
    stdout/stderr cap. The subprocess boundary keeps the agent from
    poking at the parent's state."""
    import tempfile

    cleaned = (code or "").strip()
    if not cleaned:
        return {"ok": False, "error": "empty code"}
    MAX = 200_000
    started = time.perf_counter()
    timed_out = False
    with tempfile.TemporaryDirectory(prefix="jaeger_run_") as scratch:
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-c", cleaned],
                capture_output=True, text=True, timeout=timeout_s,
                cwd=scratch,
                env={"PATH": os.environ.get("PATH", ""), "HOME": scratch},
            )
            stdout, stderr, exit_code = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = -1
            stdout = (exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")) or ""
            stderr = (exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")) or ""
    elapsed = time.perf_counter() - started
    return {
        "ok": exit_code == 0 and not timed_out,
        "exit_code": exit_code,
        "stdout": stdout[:MAX],
        "stderr": stderr[:MAX],
        "elapsed_s": round(elapsed, 3),
        "timed_out": timed_out,
    }


# ---------------------------------------------------------------------------
# Clarification + help
# ---------------------------------------------------------------------------
def ask_user(question: str) -> dict[str, Any]:
    clean = (question or "").strip()
    if not clean:
        return {"asked": False, "error": "empty question"}
    return {"asked": True, "question": clean}


CAPABILITY_SUMMARY = (
    "Jaeger built-in tools:\n"
    "  • Time / math / status — get_time, calculate, system_status\n"
    "  • Files (skills/ sandbox) — file_write, file_read, list_skill_dir\n"
    "  • Memory — remember, recall, list_facts, forget\n"
    "  • Schedules — schedule_prompt, list_schedules, cancel_schedule\n"
    "  • Web — web_search, get_weather\n"
    "  • Code — run_python (sandboxed subprocess, 10 s timeout)\n"
    "  • Credentials — get_credential, list_credentials (never echo values)\n"
    "  • Skill management — reload_skills (call after writing new skill files)\n"
    "  • Clarify — ask_user\n"
    "Plus every skill registered from base_skills/ and your instance's skills/.\n"
    "Author new skills by writing folders under skills/<name>_v<N>/ with\n"
    "SKILL.md + a module exposing register(agent) + tests/smoke_test.py."
)


def help_me() -> dict[str, Any]:
    """Capability summary — call when the user asks 'what can you do?'."""
    return {"summary": CAPABILITY_SUMMARY}
