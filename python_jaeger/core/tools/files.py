"""Sandboxed file tools — the heart of the v2 safety contract.

  • file_write(path, content)  — write/replace inside <instance>/skills/
  • append_file(path, content) — append inside <instance>/skills/
  • delete_file(path)          — delete inside <instance>/skills/
  • file_read(path)            — read anywhere except <instance>/credentials/
  • list_skill_dir(path)       — list under <instance>/skills/

ALL writes/appends/deletes are sandbox-resolved under <instance>/skills/.
The framework dir (core/, prompts/, etc.) is read-only to the agent.

Every successful write/append/delete lands as a git commit inside the
instance dir, giving the human a real authorship audit trail.
"""

from __future__ import annotations

from typing import Any

from ._common import (
    SandboxError,
    _audit,
    _require_layout,
    _resolve_under,
    git_autocommit,
)


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

    commit_sha = git_autocommit(layout, rel, f"agent: write {rel}")
    result: dict[str, Any] = {"written": True, "path": rel, "bytes": bytes_written}
    if commit_sha:
        result["commit"] = commit_sha
    return result


def append_file(path: str, content: str) -> dict[str, Any]:
    """Append text to an existing file under <instance>/skills/.

    Same sandbox enforcement as file_write — path must resolve inside
    skills/. If the file doesn't exist yet, this creates it (same as
    file_write would). Every append is audited + git-committed."""
    layout = _require_layout()
    try:
        target = _resolve_under(layout.skills_dir, path)
    except SandboxError as exc:
        _audit("append_file_denied", {"path": path, "reason": str(exc)})
        return {"appended": False, "error": str(exc)}

    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(content)
    rel = str(target.relative_to(layout.root))
    bytes_appended = len(content.encode("utf-8"))
    _audit("append_file", {"path": rel, "bytes": bytes_appended})
    commit_sha = git_autocommit(layout, rel, f"agent: append {rel}")
    result: dict[str, Any] = {"appended": True, "path": rel, "bytes": bytes_appended}
    if commit_sha:
        result["commit"] = commit_sha
    return result


def delete_file(path: str) -> dict[str, Any]:
    """Delete a file under <instance>/skills/.

    Same sandbox enforcement as file_write. Refuses to delete:
      • anything outside skills/
      • directories (use rmdir-style ops manually if you really need)
      • non-existent files (returns deleted=False with reason)

    Every delete is audited + git-committed. The v2 contract's "preserve
    rollback paths" rule is satisfied by the git history: even after a
    delete, the file lives in the commit log inside the instance repo."""
    layout = _require_layout()
    try:
        target = _resolve_under(layout.skills_dir, path)
    except SandboxError as exc:
        _audit("delete_file_denied", {"path": path, "reason": str(exc)})
        return {"deleted": False, "error": str(exc)}

    if not target.exists():
        return {"deleted": False, "reason": "not found", "path": path}
    if target.is_dir():
        return {"deleted": False, "reason": "is a directory", "path": path}

    rel = str(target.relative_to(layout.root))
    target.unlink()
    _audit("delete_file", {"path": rel})
    commit_sha = git_autocommit(layout, rel, f"agent: delete {rel}")
    result: dict[str, Any] = {"deleted": True, "path": rel}
    if commit_sha:
        result["commit"] = commit_sha
    return result


def file_read(path: str) -> dict[str, Any]:
    """Read a text file from anywhere under the instance dir EXCEPT credentials/.

    Use this to inspect identity/config/manifest, prior skills, and the
    contents of skills/. Reads of credentials/ are rejected with a hint
    pointing at `get_credential()`.
    """
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
                      "Use get_credential(name) instead."),
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
