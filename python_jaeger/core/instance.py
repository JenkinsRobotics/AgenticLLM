"""Instance directory: path resolution, layout, lockfile, manifest.

An *instance* is a writable per-robot directory that holds identity, config,
memory, logs, skills, and (M2) credentials. Resolution order:

  1. JAEGER_INSTANCE_DIR env var, if set
  2. /var/lib/jaeger/<instance>/   if running as a system service (uid 0)
  3. ~/.jaeger/<instance>/         user mode (default)

`<instance>` defaults to "default" and can be overridden with
JAEGER_INSTANCE_NAME or via the wizard.

Locking uses fcntl on `.lock` so two Jaeger processes can never share an
instance dir; stale locks are detected via the PID written into the file.
"""

from __future__ import annotations

import contextlib
import errno
import fcntl
import os
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import (
    CORE_VERSION,
    Config,
    Identity,
    Manifest,
    dump_json,
    dump_yaml,
    load_json,
    load_yaml,
)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
#   1. JAEGER_INSTANCE_DIR env var       — explicit override (always wins)
#   2. /var/lib/jaeger/<name>/           — system service mode (uid 0)
#   3. python_jaeger/instance/<name>/    — DEFAULT (dev / single-user) — visible
#                                          in the source tree, symmetric with
#                                          pydantic_ai/workspace/. The framework
#                                          dir is read-only TO THE AGENT (v2
#                                          contract enforces writes only to
#                                          <instance>/skills/), so co-locating
#                                          is safe.
#   4. ~/.jaeger/<name>/                 — legacy fallback when the bundled
#                                          instance dir isn't writable (e.g.
#                                          pip-installed inside a system
#                                          site-packages tree).
SYSTEM_ROOT = Path("/var/lib/jaeger")
USER_ROOT = Path("~/.jaeger").expanduser()
# python_jaeger/core/instance.py → .parent.parent = python_jaeger/
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_INSTANCE_ROOT = PACKAGE_ROOT / "instance"


def default_instance_name() -> str:
    return os.environ.get("JAEGER_INSTANCE_NAME", "default")


def resolve_instance_dir(name: str | None = None) -> Path:
    """Pick the on-disk path for this instance, honoring env overrides.

    See module-level path-resolution comment for the priority order.
    """
    override = os.environ.get("JAEGER_INSTANCE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    inst = name or default_instance_name()

    # System service: use /var/lib/jaeger when running as root.
    if os.geteuid() == 0 and SYSTEM_ROOT.parent.exists():
        return (SYSTEM_ROOT / inst).resolve()

    # Default: bundled instance dir inside the package, visible in the source
    # tree. Falls back to ~/.jaeger/ if the package dir isn't writable
    # (uncommon — happens for system-wide pip installs).
    try:
        BUNDLED_INSTANCE_ROOT.mkdir(parents=True, exist_ok=True)
        return (BUNDLED_INSTANCE_ROOT / inst).resolve()
    except (OSError, PermissionError):
        return (USER_ROOT / inst).resolve()


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class InstanceLayout:
    """Centralized knowledge of where each piece of instance state lives.

    Every other Jaeger module asks the layout for paths — no hard-coded
    strings sprinkled across the codebase. If we ever change a directory
    name (e.g. memory/ → state/), it's a one-line change here.

    Invariant: `root` is always a fully-resolved (symlink-canonicalized)
    path. On macOS `/var` is a symlink to `/private/var`, so without
    canonicalization a `target.relative_to(root)` comparison would fail
    even when `target` is plainly inside `root`. We normalize in
    `__post_init__` so every downstream caller gets the same shape.
    """
    root: Path

    def __post_init__(self) -> None:
        resolved = self.root.expanduser().resolve()
        if resolved != self.root:
            object.__setattr__(self, "root", resolved)

    @property
    def identity_path(self) -> Path:        return self.root / "identity.yaml"
    @property
    def config_path(self) -> Path:          return self.root / "config.yaml"
    @property
    def manifest_path(self) -> Path:        return self.root / "manifest.json"
    @property
    def credentials_dir(self) -> Path:      return self.root / "credentials"
    @property
    def skills_dir(self) -> Path:           return self.root / "skills"
    @property
    def memory_dir(self) -> Path:           return self.root / "memory"
    @property
    def logs_dir(self) -> Path:             return self.root / "logs"
    @property
    def lock_path(self) -> Path:            return self.root / ".lock"
    @property
    def audit_log_path(self) -> Path:       return self.logs_dir / "audit.log"
    @property
    def latency_log_path(self) -> Path:     return self.logs_dir / "latency.jsonl"

    def exists(self) -> bool:
        return self.identity_path.exists() and self.config_path.exists() and self.manifest_path.exists()

    def ensure_dirs(self) -> None:
        for d in (self.credentials_dir, self.skills_dir, self.memory_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)
        # 0700 on credentials/ so an OS-level snoop sees an empty dir at best.
        try:
            os.chmod(self.credentials_dir, 0o700)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Lockfile
# ---------------------------------------------------------------------------
class InstanceLock:
    """Exclusive flock on the instance .lock file.

    Holds an open file handle (kept alive for the process lifetime) and
    writes the holding PID into the file for debug visibility. Stale
    locks from a crashed prior run are detected by a PID-alive check.
    """

    def __init__(self, layout: InstanceLayout) -> None:
        self._path = layout.lock_path
        self._fh: Any = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fh = self._path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EWOULDBLOCK, errno.EACCES):
                fh.close()
                raise
            fh.seek(0)
            old = (fh.read() or "").strip()
            fh.close()
            holder = _pid_alive(old)
            if holder is not None:
                raise RuntimeError(
                    f"instance {self._path.parent.name!r} is locked by pid {holder} (still running). "
                    "Refusing to start a second copy."
                ) from exc
            # Stale: caller can remove + retry.
            raise RuntimeError(
                f"stale lock at {self._path} (pid {old or '?'} is gone). "
                f"Remove the file manually if you're sure nothing else is running."
            ) from exc

        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        self._fh = fh

    def release(self) -> None:
        if self._fh is None:
            return
        with contextlib.suppress(OSError):
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        with contextlib.suppress(OSError):
            self._fh.close()
        self._fh = None
        with contextlib.suppress(OSError):
            self._path.unlink()


def _pid_alive(pid_str: str) -> int | None:
    try:
        pid = int(pid_str)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    try:
        os.kill(pid, 0)
        return pid
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return None
        # EPERM means the process exists but is owned by another user.
        return pid


# ---------------------------------------------------------------------------
# Manifest version check
# ---------------------------------------------------------------------------
class CoreVersionMismatch(RuntimeError):
    """Raised when the installed core version differs from the one the
    instance was created against. M2 will add a migration runner; for
    M1 we refuse-to-start and surface a clear instruction."""


def check_manifest(layout: InstanceLayout) -> Manifest:
    manifest = load_json(layout.manifest_path, Manifest)
    if manifest.core_version != CORE_VERSION:
        raise CoreVersionMismatch(
            f"instance {manifest.instance_name!r} was created against core "
            f"{manifest.core_version!r}, but installed core is {CORE_VERSION!r}. "
            "Run `python main.py python_jaeger --migrate` to apply pending "
            "migrations, or back up the instance and re-run the wizard."
        )
    return manifest


def touch_manifest_started(layout: InstanceLayout, manifest: Manifest) -> None:
    dump_json(layout.manifest_path, manifest.with_started_now())


# ---------------------------------------------------------------------------
# Backup-rename (used by the wizard for re-run safety)
# ---------------------------------------------------------------------------
def backup_instance_dir(layout: InstanceLayout) -> Path:
    """Rename the existing instance dir aside so the wizard can rebuild
    cleanly without ever destroying state. Returns the backup path."""
    if not layout.root.exists():
        return layout.root  # nothing to back up
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = layout.root.with_name(f"{layout.root.name}.bak.{ts}")
    shutil.move(str(layout.root), str(backup))
    print(f"[jaeger] backed up existing instance to {backup}", file=sys.stderr, flush=True)
    return backup


# ---------------------------------------------------------------------------
# Convenience: load all three files in one shot (raises if missing/invalid)
# ---------------------------------------------------------------------------
def load_instance(layout: InstanceLayout) -> tuple[Identity, Config, Manifest]:
    identity = load_yaml(layout.identity_path, Identity)
    config = load_yaml(layout.config_path, Config)
    manifest = check_manifest(layout)
    return identity, config, manifest
