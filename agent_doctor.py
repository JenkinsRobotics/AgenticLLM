#!/usr/bin/env python3
"""Pre-flight check for the agent + voice loop.

Run before any deploy / before letting the robot loose. Each check returns
(status, summary). Exit code is 0 iff every check passes; otherwise 1.

    .venv/bin/python agent_doctor.py
    .venv/bin/python agent_doctor.py --verbose

Designed so a robot's systemd unit can gate startup on `agent_doctor.py`
exiting 0 — "won't boot if memory is corrupt / model missing / disk full".
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parent
from model_resolver import resolve_model_path
DEFAULT_MODEL_PATH = resolve_model_path()

OK, WARN, FAIL = "OK", "WARN", "FAIL"


def _fmt(status: str, name: str, msg: str) -> str:
    pad = "✓" if status == OK else ("⚠" if status == WARN else "✗")
    return f"  [{pad}] {name:<28} {msg}"


# ----------------------------------------------------------------------------
# Individual checks. Each returns (status, summary). Status FAIL flips exit
# code; WARN is reported but non-blocking.
# ----------------------------------------------------------------------------
def check_python() -> tuple[str, str]:
    v = sys.version_info
    if v < (3, 10) or v >= (3, 13):
        return FAIL, f"Python {v.major}.{v.minor} — need 3.10–3.12"
    return OK, f"Python {v.major}.{v.minor}.{v.micro}"


def check_platform() -> tuple[str, str]:
    p = platform.platform()
    machine = platform.machine()
    if "arm64" in machine or "aarch64" in machine:
        return OK, p
    return WARN, f"{p} (we target arm64 Apple Silicon)"


def check_model_file() -> tuple[str, str]:
    if not DEFAULT_MODEL_PATH.exists():
        return FAIL, f"missing {DEFAULT_MODEL_PATH}"
    size_gb = DEFAULT_MODEL_PATH.stat().st_size / 1024**3
    return OK, f"{DEFAULT_MODEL_PATH.name} ({size_gb:.1f} GB)"


def check_disk_free() -> tuple[str, str]:
    total, used, free = shutil.disk_usage(PROJECT_ROOT)
    free_gb = free / 1024**3
    if free_gb < 2:
        return FAIL, f"only {free_gb:.1f} GB free — need ≥ 2 GB"
    if free_gb < 10:
        return WARN, f"{free_gb:.1f} GB free — tight headroom"
    return OK, f"{free_gb:.1f} GB free"


def check_deps() -> tuple[str, str]:
    """Core deps (FAIL if missing) + optional deps (just note them)."""
    required = ["llama_cpp", "pydantic_ai", "kokoro", "sounddevice", "webrtcvad", "scipy", "numpy"]
    optional = {
        "sentence_transformers": "semantic memory search",
        "transformers": "look_at (vision)",
        "diffusers": "generate_image",
        "discord": "Discord messaging bridge",
        "pywhispercpp": "whisper_stt plugin (voice loop)",
        "speexdsp": "AEC for barge-in (passthrough without it)",
    }
    missing: list[str] = []
    for mod in required:
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(mod)
    if missing:
        return FAIL, f"missing required: {', '.join(missing)}"
    opt_present = [
        f"{name} ({purpose})" for name, purpose in optional.items()
        if importlib.util.find_spec(name) is not None
    ]
    detail = f"all {len(required)} core deps OK"
    if opt_present:
        detail += f"; optional: {len(opt_present)} present"
    return OK, detail


def check_memory_files() -> tuple[str, str]:
    from python_pydantic_ai.memory.memory_module import FACTS_PATH, IDENTITY_PATH, EPISODIC_PATH, _read_facts

    facts = _read_facts()
    fact_count = len(facts)
    epi = EPISODIC_PATH.stat().st_size if EPISODIC_PATH.exists() else 0
    if not IDENTITY_PATH.exists():
        return WARN, "identity.md missing — agent will run with default persona"
    return OK, (
        f"identity.md present, facts={fact_count}, "
        f"episodic.jsonl={epi / 1024:.1f} KB"
    )


def check_memory_schema() -> tuple[str, str]:
    from python_pydantic_ai.memory.memory_module import FACTS_PATH, SCHEMA_VERSION

    if not FACTS_PATH.exists():
        return OK, "facts.json absent (fresh install)"
    try:
        raw = json.loads(FACTS_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        return FAIL, f"facts.json unreadable: {exc}"
    if not isinstance(raw, dict):
        return FAIL, "facts.json is not a JSON object"
    version = raw.get("schema_version")
    if version is None:
        return WARN, "facts.json on legacy v0 shape — will migrate on next write"
    if version != SCHEMA_VERSION:
        return WARN, f"facts.json schema_version={version}, code expects {SCHEMA_VERSION}"
    return OK, f"schema_version={version}, current"


def check_log_sizes() -> tuple[str, str]:
    from python_pydantic_ai.memory.maintenance import LATENCY_LOG_PATHS, DEFAULT_MAX_BYTES

    over: list[str] = []
    sizes: list[str] = []
    for p in LATENCY_LOG_PATHS:
        if not p.exists():
            continue
        s = p.stat().st_size
        sizes.append(f"{p.parent.parent.name}={s / 1024:.0f}K")
        if s >= DEFAULT_MAX_BYTES:
            over.append(p.name)
    if over:
        return WARN, f"over rotation threshold: {', '.join(over)} — run `python -m memory.maintenance --rotate-logs`"
    return OK, ", ".join(sizes) if sizes else "no logs yet"


def check_mcp_config() -> tuple[str, str]:
    # After the per-framework split, mcp_config.json lives inside each
    # framework that uses MCP. The doctor checks pydantic_ai's copy (the
    # recommended framework) as the canonical view.
    cfg = PROJECT_ROOT / "python_pydantic_ai" / "mcp_config.json"
    if not cfg.exists():
        return OK, "mcp_config.json absent (MCP off)"
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except Exception as exc:
        return FAIL, f"mcp_config.json invalid JSON: {exc}"
    servers = data.get("servers") or []
    return OK, f"{len(servers)} MCP server(s) configured"


def check_audio_devices() -> tuple[str, str]:
    try:
        import sounddevice as sd
    except ImportError:
        return WARN, "sounddevice not installed — voice loop disabled"
    try:
        in_dev = sd.query_devices(kind="input")
        out_dev = sd.query_devices(kind="output")
    except Exception as exc:
        return WARN, f"no default audio device: {exc}"
    in_name = in_dev.get("name", "?") if isinstance(in_dev, dict) else "?"
    out_name = out_dev.get("name", "?") if isinstance(out_dev, dict) else "?"
    return OK, f"in={in_name[:30]}, out={out_name[:30]}"


def check_schedules() -> tuple[str, str]:
    from python_pydantic_ai.memory.memory_module import list_schedules, SCHEDULES_PATH

    if not SCHEDULES_PATH.exists():
        return OK, "schedules.jsonl absent (no cron jobs scheduled)"
    live = list_schedules()
    if not live:
        return OK, "schedules.jsonl present, 0 live entries"
    return OK, f"{len(live)} live schedule(s): {', '.join(s.get('name','?') for s in live[:3])}"


def check_embed_cache() -> tuple[str, str]:
    from python_pydantic_ai.memory.memory_module import EMBED_PATH, EPISODIC_PATH

    if not EPISODIC_PATH.exists():
        return OK, "episodic.jsonl absent (no semantic-search index needed yet)"
    if not EMBED_PATH.exists():
        return OK, "no embedding cache yet (built on first `search_memory` call)"
    return OK, f"embedding cache: {EMBED_PATH.stat().st_size / 1024:.0f} KB"


def check_workspace() -> tuple[str, str]:
    ws = PROJECT_ROOT / "python_pydantic_ai" / "workspace"
    if not ws.exists():
        return WARN, "python_pydantic_ai/workspace/ absent — will be created on first tool call"
    files = sum(1 for _ in ws.iterdir())
    return OK, f"{files} entries in python_pydantic_ai/workspace/"


def check_env_vars() -> tuple[str, str]:
    interesting = ["DESTRUCTIVE_OPS_REQUIRE_CONFIRM", "VOICE_FRAMEWORK", "VISION_MODEL_ID", "IMAGE_GEN_MODEL_ID"]
    set_vars = [v for v in interesting if os.environ.get(v)]
    if not set_vars:
        return OK, "no agent env vars set (bench/dev defaults)"
    return OK, ", ".join(f"{v}={os.environ[v][:30]!r}" for v in set_vars)


# ----------------------------------------------------------------------------
# Runner
# ----------------------------------------------------------------------------
CHECKS: list[tuple[str, Callable[[], tuple[str, str]]]] = [
    ("python", check_python),
    ("platform", check_platform),
    ("model file", check_model_file),
    ("disk free", check_disk_free),
    ("python deps", check_deps),
    ("memory files", check_memory_files),
    ("memory schema", check_memory_schema),
    ("schedules", check_schedules),
    ("embedding cache", check_embed_cache),
    ("log sizes", check_log_sizes),
    ("MCP config", check_mcp_config),
    ("audio devices", check_audio_devices),
    ("workspace", check_workspace),
    ("env vars", check_env_vars),
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--verbose", action="store_true", help="Print Python tracebacks for any check that crashes.")
    args = p.parse_args()

    print("agent doctor — pre-flight check")
    print("=" * 40)
    counts = {OK: 0, WARN: 0, FAIL: 0}
    for name, fn in CHECKS:
        try:
            status, msg = fn()
        except Exception as exc:
            status, msg = FAIL, f"check crashed: {type(exc).__name__}: {exc}"
            if args.verbose:
                import traceback
                traceback.print_exc()
        counts[status] += 1
        print(_fmt(status, name, msg))

    print("=" * 40)
    print(f"  {counts[OK]} OK / {counts[WARN]} WARN / {counts[FAIL]} FAIL")
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    raise SystemExit(main())
