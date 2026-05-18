"""Repo-wide GGUF path resolution.

Single source of truth for "which GGUF file should this process load?" so
agent_doctor, plugins.voice_loop, bench harness, and ad-hoc scripts all
agree without duplicating the LM Studio path five times.

Resolution order (first hit wins):
  1. AGENTICLLM_MODEL_PATH env var (canonical, framework-agnostic name)
  2. HERMES_LLM_MODEL env var (legacy — predates the multi-framework split)
  3. <repo>/models/gemma-4-26B-A4B-it-Q4_K_M.gguf (the local symlink target)
  4. LM Studio default path

The per-framework `main.py` files duplicate this chain inline rather than
importing from here, because the user explicitly wanted each framework
isolated from the others and from the repo root. This module is for the
standalone scripts (agent_doctor, bench_worker) that already sit at repo
root and have no framework-isolation constraint.

If you need to add a new resolver entry, change this list AND update the
inline copy in each framework's `_resolve_model_path()`.
"""

from __future__ import annotations

import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
LOCAL_DEFAULT = REPO_ROOT / "models" / "gemma-4-26B-A4B-it-Q4_K_M.gguf"
LM_STUDIO_DEFAULT = Path(
    "/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/"
    "gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf"
)


def resolve_model_path() -> Path:
    """Return the GGUF path the framework should load. See module docstring
    for resolution order."""
    for env_var in ("AGENTICLLM_MODEL_PATH", "HERMES_LLM_MODEL"):
        value = os.environ.get(env_var)
        if value:
            return Path(value).expanduser()
    if LOCAL_DEFAULT.exists():
        return LOCAL_DEFAULT
    return LM_STUDIO_DEFAULT


if __name__ == "__main__":
    # Tiny self-check: print the resolved path and which source it came from.
    path = resolve_model_path()
    if os.environ.get("AGENTICLLM_MODEL_PATH"):
        source = "AGENTICLLM_MODEL_PATH env var"
    elif os.environ.get("HERMES_LLM_MODEL"):
        source = "HERMES_LLM_MODEL env var (legacy)"
    elif LOCAL_DEFAULT.exists():
        source = "<repo>/models/ symlink"
    else:
        source = "LM Studio default"
    print(f"{path}")
    print(f"source: {source}")
    print(f"exists: {path.exists()}")
