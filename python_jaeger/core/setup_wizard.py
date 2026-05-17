"""First-run setup wizard.

Triggered by main.py when the resolved instance dir doesn't have a valid
identity/config/manifest trio yet. Writes the three files, initializes the
directory layout, and (where available) initializes a git repo so the
agent's skill-folder changes are versioned.

Re-runnable: if the instance dir already exists with state in it, the
wizard renames it aside (`<dir>.bak.<timestamp>`) before rebuilding,
so re-running never destroys prior work.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .instance import (
    InstanceLayout,
    backup_instance_dir,
    default_instance_name,
    resolve_instance_dir,
)
from .schemas import (
    CORE_VERSION,
    Config,
    DisplayConfig,
    Identity,
    Manifest,
    ModelConfig,
    RetentionConfig,
    SkillsConfig,
    dump_json,
    dump_yaml,
)


# Sane fallback model path matching the rest of the project's defaults.
DEFAULT_MODEL_PATH = Path(
    "/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/"
    "gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf"
)


def _ask(label: str, default: str = "", *, secret: bool = False) -> str:
    suffix = f" [{default}]" if default and not secret else ""
    if secret:
        try:
            v = getpass.getpass(f"{label}{suffix}: ").strip()
        except Exception:
            v = input(f"{label}{suffix}: ").strip()
    else:
        v = input(f"{label}{suffix}: ").strip()
    return v or default


def _ask_int(label: str, default: int) -> int:
    while True:
        raw = _ask(label, str(default))
        try:
            return int(raw)
        except ValueError:
            print(f"  (expected an integer, got {raw!r})")


def _ask_yn(label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"{label} ({hint}): ").strip().lower()
    if not raw:
        return default
    return raw[0] == "y"


def run_wizard(*, force: bool = False, instance_name: str | None = None) -> InstanceLayout:
    """Drive the wizard end-to-end. Returns the layout of the new instance."""
    name = instance_name or default_instance_name()
    root = resolve_instance_dir(name)
    layout = InstanceLayout(root=root)

    print()
    print("─────────────────────────────────────────────")
    print("  Jaeger Agent — first-time instance setup")
    print("─────────────────────────────────────────────")
    print(f"  Instance dir: {root}")
    print()

    if layout.exists():
        if not force:
            print("This instance already exists. Re-running the wizard will back it up")
            print("aside (.bak.<timestamp>) and create a fresh one.")
            if not _ask_yn("  Re-run wizard?", False):
                print("Aborted.")
                sys.exit(0)
        backup_instance_dir(layout)

    # 1. Instance name -------------------------------------------------------
    print("[1/4] Instance name")
    chosen_instance = _ask("  Instance name (path-safe, no spaces)", name)
    if chosen_instance != name:
        # Re-resolve in case the user picked a different name
        layout = InstanceLayout(root=resolve_instance_dir(chosen_instance))
        if layout.exists():
            backup_instance_dir(layout)
    print()

    # 2. Agent identity ------------------------------------------------------
    print("[2/4] Agent identity")
    agent_name = _ask("  Agent name", "Lilith")
    role = _ask("  Role / what does this agent do?", "local AI tool router")
    personality = _ask(
        "  Personality / voice (one sentence)",
        "Concise and direct. No filler. Confident on facts; honest about uncertainty.",
    )
    voice_tone = _ask("  Voice tone tag", "neutral")
    identity = Identity(name=agent_name, role=role, personality=personality, voice_tone=voice_tone)
    print()

    # 3. Model ---------------------------------------------------------------
    print("[3/4] Model")
    model_path_raw = _ask("  Path to GGUF weights", str(DEFAULT_MODEL_PATH))
    model_path = Path(model_path_raw).expanduser()
    if not model_path.exists():
        print(f"  ⚠  warning: {model_path} doesn't exist yet — wizard will save anyway.")
    ctx = _ask_int("  Context window", 8192)
    gpu_layers = _ask_int("  GPU layers (-1 = all)", -1)
    print()

    # 4. Display preferences -------------------------------------------------
    print("[4/4] Display preferences")
    show_latency = _ask_yn("  Show per-turn latency breakdown?", False)
    show_tools = _ask_yn("  Show tool-activity lines?", True)
    show_help = _ask_yn("  Show the help banner on startup?", True)
    print()

    config = Config(
        instance_name=chosen_instance,
        model=ModelConfig(model_path=model_path, ctx=ctx, gpu_layers=gpu_layers),
        display=DisplayConfig(
            show_latency=show_latency,
            show_tool_activity=show_tools,
            show_help_on_start=show_help,
        ),
        skills=SkillsConfig(),
        retention=RetentionConfig(),
    )
    manifest = Manifest(instance_name=chosen_instance, core_version=CORE_VERSION)

    # Write everything atomically.
    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, identity)
    dump_yaml(layout.config_path, config)
    dump_json(layout.manifest_path, manifest)

    # Initialize a git repo inside the instance dir so skill-folder changes
    # are versioned. Best-effort — if git isn't installed, we skip.
    _git_init(layout.root)

    print(f"✓ Instance created at {layout.root}")
    print(f"  identity:  {layout.identity_path.name}")
    print(f"  config:    {layout.config_path.name}")
    print(f"  manifest:  {layout.manifest_path.name}")
    print(f"  skills/    (agent's writable scratchpad)")
    print()
    return layout


def _git_init(root: Path) -> None:
    if not _has_git():
        return
    try:
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(root)],
            check=True, capture_output=True, timeout=10,
        )
        gitignore = root / ".gitignore"
        gitignore.write_text(
            "# Auto-generated by the Jaeger wizard.\n"
            ".lock\n"
            "credentials/\n"
            "logs/\n"
            "memory/episodic.embeddings.npz\n",
            encoding="utf-8",
        )
        subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            check=True, capture_output=True, timeout=10,
        )
        subprocess.run(
            ["git", "-C", str(root), "-c", "user.email=jaeger@local",
             "-c", "user.name=jaeger-setup",
             "commit", "-q", "-m", "jaeger: initial instance"],
            check=False, capture_output=True, timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"[jaeger] git init skipped: {exc}", file=sys.stderr, flush=True)


def _has_git() -> bool:
    try:
        from shutil import which
        return which("git") is not None
    except Exception:
        return False
