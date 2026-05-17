"""Skill discovery and resolution.

A *skill* is a self-contained directory:

    skills/<name>_v<N>/
        SKILL.md            # When + how to use this skill
        <python module>     # Implementation
        tests/
            smoke_test.py   # Decides whether the skill is safe to register

The loader scans two zones:

  1. Core base skills   — python_jaeger/base_skills/ (read-only, shipped)
  2. Instance skills    — <instance_dir>/skills/    (agent-writable)

Resolution rules:

  - On name collision, **instance wins over core**.
  - Within a zone, the highest `_v<N>` suffix wins.
  - A skill whose smoke test fails is *skipped*, not registered, and the
    failure goes into logs/audit.log so the human can see why.

Skill modules are imported via importlib and are expected to expose a
top-level callable named `register(agent)` that registers one or more
PydanticAI tools onto the agent. The loader never imports a `.py` from
outside the two zones — the path is computed from the discovered folder.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from .instance import InstanceLayout


CORE_BASE_SKILLS_DIR = Path(__file__).resolve().parent / "base_skills"


_SKILL_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_]*)_v(?P<v>\d+)$")


@dataclass(frozen=True)
class DiscoveredSkill:
    name: str
    version: int
    zone: str            # "core" or "instance"
    folder: Path
    module_path: Path    # the .py file we'll import
    has_smoke: bool


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def _scan_zone(root: Path, zone: str) -> list[DiscoveredSkill]:
    found: list[DiscoveredSkill] = []
    if not root.exists():
        return found
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        m = _SKILL_RE.match(child.name)
        if not m:
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            # A folder that looks like a skill but is missing SKILL.md is a
            # half-finished thing — skip silently.
            continue
        module = _pick_module_file(child)
        if module is None:
            continue
        found.append(DiscoveredSkill(
            name=m.group("name"),
            version=int(m.group("v")),
            zone=zone,
            folder=child,
            module_path=module,
            has_smoke=(child / "tests" / "smoke_test.py").exists(),
        ))
    return found


def _pick_module_file(folder: Path) -> Path | None:
    """A skill folder may contain multiple files; the import target is
    one of (in order): <name without version>.py, skill.py, __init__.py.
    If none exist, the skill isn't importable and is skipped."""
    base = _SKILL_RE.match(folder.name)
    candidates: list[Path] = []
    if base:
        candidates.append(folder / f"{base.group('name')}.py")
    candidates.append(folder / "skill.py")
    candidates.append(folder / "__init__.py")
    for c in candidates:
        if c.exists():
            return c
    return None


def discover_skills(layout: InstanceLayout) -> list[DiscoveredSkill]:
    """Return the resolved skill set: highest-version-per-name, instance
    winning over core on name collision."""
    core = _scan_zone(CORE_BASE_SKILLS_DIR, "core")
    instance = _scan_zone(layout.skills_dir, "instance")

    # Pick highest version per (zone, name) first.
    def best_in(seq: Iterable[DiscoveredSkill]) -> dict[str, DiscoveredSkill]:
        out: dict[str, DiscoveredSkill] = {}
        for s in seq:
            cur = out.get(s.name)
            if cur is None or s.version > cur.version:
                out[s.name] = s
        return out

    core_best = best_in(core)
    instance_best = best_in(instance)
    # Instance wins on collision.
    merged = {**core_best, **instance_best}
    return sorted(merged.values(), key=lambda s: (s.zone != "instance", s.name))


# ---------------------------------------------------------------------------
# Smoke test gating
# ---------------------------------------------------------------------------
def _run_smoke(skill: DiscoveredSkill, timeout_s: float = 10.0) -> tuple[bool, str]:
    test = skill.folder / "tests" / "smoke_test.py"
    if not test.exists():
        return True, ""  # no test → trust by default (M2 will require trusted tests)
    try:
        proc = subprocess.run(
            [sys.executable, str(test)],
            capture_output=True, text=True, timeout=timeout_s,
            cwd=str(skill.folder),
        )
    except subprocess.TimeoutExpired:
        return False, f"smoke test timed out after {timeout_s}s"
    except Exception as exc:
        return False, f"smoke test couldn't run: {exc}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        return False, f"smoke test exit={proc.returncode}\n{tail}"
    return True, ""


# ---------------------------------------------------------------------------
# Import + registration
# ---------------------------------------------------------------------------
def _import_skill(skill: DiscoveredSkill) -> Any:
    mod_name = f"_jaeger_skill_{skill.zone}_{skill.name}_v{skill.version}"
    spec = importlib.util.spec_from_file_location(mod_name, skill.module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not build import spec for {skill.module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class SkillLoadReport:
    registered: list[DiscoveredSkill]
    skipped: list[tuple[DiscoveredSkill, str]]


_REGISTERED_KEYS: set[tuple[str, int, str]] = set()


def reset_registered() -> None:
    """Drop the loader's idempotency cache. Used by tests that bind/unbind
    an instance several times without restarting the process."""
    _REGISTERED_KEYS.clear()


def load_and_register(
    agent: Any,
    layout: InstanceLayout,
    *,
    run_smoke_tests: bool = True,
    enabled_allowlist: list[str] | None = None,
    audit: Callable[[str, dict[str, Any]], None] | None = None,
) -> SkillLoadReport:
    """Discover skills, gate on smoke tests, register passers onto the agent.

    `enabled_allowlist` (from config.skills.enabled_base_skills) filters
    *core* skills only — instance skills are always considered. Empty list
    or None disables the filter.
    `audit` is the audit-log callback (so skips are visible in logs/audit.log).
    """
    registered: list[DiscoveredSkill] = []
    skipped: list[tuple[DiscoveredSkill, str]] = []

    for skill in discover_skills(layout):
        key = (skill.name, skill.version, skill.zone)
        if key in _REGISTERED_KEYS:
            # Already wired during a prior call — skipping is the correct
            # behavior for hot-reload (pydantic-ai's @tool_plain raises if
            # we try to register the same name twice).
            continue

        if (
            skill.zone == "core"
            and enabled_allowlist
            and skill.name not in enabled_allowlist
        ):
            skipped.append((skill, "disabled by config"))
            if audit:
                audit("skill_skip", {"skill": skill.name, "version": skill.version,
                                     "zone": skill.zone, "reason": "disabled_by_config"})
            continue

        if run_smoke_tests and skill.has_smoke:
            ok, msg = _run_smoke(skill)
            if not ok:
                skipped.append((skill, msg))
                if audit:
                    audit("skill_smoke_fail", {"skill": skill.name, "version": skill.version,
                                                "zone": skill.zone, "error": msg[:500]})
                print(f"[jaeger-skills] {skill.name}_v{skill.version} ({skill.zone}) skipped: smoke test failed.",
                      flush=True)
                continue

        try:
            module = _import_skill(skill)
            register = getattr(module, "register", None)
            if register is None:
                skipped.append((skill, "no register(agent) callable"))
                continue
            register(agent)
        except Exception as exc:
            tb = traceback.format_exc(limit=4)
            skipped.append((skill, f"import/register failed: {exc}\n{tb}"))
            if audit:
                audit("skill_register_fail", {"skill": skill.name, "version": skill.version,
                                              "zone": skill.zone, "error": str(exc)})
            print(f"[jaeger-skills] {skill.name}_v{skill.version} ({skill.zone}) skipped: {exc}",
                  flush=True)
            continue

        registered.append(skill)
        _REGISTERED_KEYS.add(key)
        if audit:
            audit("skill_registered", {"skill": skill.name, "version": skill.version,
                                        "zone": skill.zone})

    if registered:
        names = ", ".join(f"{s.name}_v{s.version}({s.zone})" for s in registered)
        print(f"[jaeger-skills] registered {len(registered)} skill(s): {names}", flush=True)
    return SkillLoadReport(registered=registered, skipped=skipped)
