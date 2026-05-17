"""Pydantic v2 schemas for the on-disk files an instance owns.

Three files live at the root of every instance directory and are validated
against these models on every read. Hand-edits to the YAML are welcome —
the schemas exist so a typo doesn't silently corrupt runtime state.

  identity.yaml   → Identity   (name, role, personality, voice tone)
  config.yaml     → Config     (model endpoint, runtime knobs)
  manifest.json   → Manifest   (core_version pin, instance_name, created_at)

The setup wizard writes all three; the agent loop reads them; the agent
itself is forbidden from editing identity/config/manifest by the
sandboxed file tools.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Bumped whenever the on-disk shape of identity.yaml / config.yaml changes
# in a way that needs a migration. Stored in manifest.json on instance
# creation; mismatch with the installed core triggers refuse-to-start at
# runtime (full migration system is M2 work).
CORE_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# identity.yaml
# ---------------------------------------------------------------------------
class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=64, description="Agent's display name")
    role: str = Field(..., min_length=1, max_length=256, description="One-line role description")
    personality: str = Field(..., min_length=1, max_length=2048)
    voice_tone: str = Field("neutral", max_length=64)

    @field_validator("name")
    @classmethod
    def _no_path_chars(cls, v: str) -> str:
        if any(c in v for c in "/\\:*?\"<>|"):
            raise ValueError("name must not contain path-illegal characters")
        return v


# ---------------------------------------------------------------------------
# config.yaml
# ---------------------------------------------------------------------------
class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # In-process llama-cpp-python is the only adapter Jaeger M1 supports.
    # M2 may add OpenAI-compatible HTTP endpoints; the discriminator stays here
    # so we don't have to migrate config files later.
    backend: Literal["llama_cpp_python"] = "llama_cpp_python"
    model_path: Path = Field(..., description="Absolute path to the GGUF weights")
    ctx: int = Field(8192, ge=512, le=131_072)
    gpu_layers: int = Field(-1, description="-1 = offload all, 0 = CPU-only")
    n_batch: int = 512
    n_ubatch: int = 512
    flash_attn: bool = True
    threads: int | None = None


class DisplayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    show_latency: bool = False
    show_tool_activity: bool = True
    show_help_on_start: bool = True


class RetentionConfig(BaseModel):
    """M3 will wire log rotation + memory cap to these; M1 just persists them."""
    model_config = ConfigDict(extra="forbid")
    logs_keep_days: int = Field(30, ge=1)
    logs_max_total_mb: int = Field(1024, ge=16)
    memory_max_mb: int = Field(1024, ge=16)


class SkillsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled_base_skills: list[str] = Field(default_factory=list,
        description="Empty = enable all; otherwise allowlist by skill folder name.")
    hot_reload: bool = False
    run_smoke_tests: bool = True
    include_self_improvement_contract: bool = Field(
        default=False,
        description=(
            "Inject the full v2 self-improvement contract (skill versioning, "
            "smoke tests, rollback rules) into the system prompt. Off by "
            "default — adds ~900 words and only matters when the agent is "
            "actively authoring new skills. Routing benchmarks run leaner "
            "without it."
        ),
    )


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance_name: str = Field(..., min_length=1, max_length=64)
    model: ModelConfig
    display: DisplayConfig = Field(default_factory=DisplayConfig)
    skills: SkillsConfig = Field(default_factory=SkillsConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)

    @field_validator("instance_name")
    @classmethod
    def _safe_instance_name(cls, v: str) -> str:
        if any(c in v for c in "/\\:*?\"<>|. "):
            raise ValueError("instance_name must be path-safe (no /, \\, spaces, dots, etc.)")
        return v


# ---------------------------------------------------------------------------
# manifest.json
# ---------------------------------------------------------------------------
class Manifest(BaseModel):
    """Per-instance metadata. Pins the core version that owns this instance
    so a future core upgrade can decide whether to migrate or refuse."""
    model_config = ConfigDict(extra="forbid")

    instance_name: str
    core_version: str = CORE_VERSION
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    last_started_at: str | None = None

    def with_started_now(self) -> "Manifest":
        return self.model_copy(update={"last_started_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})


# ---------------------------------------------------------------------------
# Generic helpers — write+read with validation
# ---------------------------------------------------------------------------
def _atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    import os
    os.replace(tmp, path)


def dump_yaml(path: Path, model: BaseModel) -> None:
    import yaml
    data = model.model_dump(mode="json")
    _atomic_write(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def load_yaml(path: Path, model_cls: type[BaseModel]) -> Any:
    import yaml
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return model_cls.model_validate(raw)


def dump_json(path: Path, model: BaseModel) -> None:
    _atomic_write(path, model.model_dump_json(indent=2))


def load_json(path: Path, model_cls: type[BaseModel]) -> Any:
    import json
    with path.open("r", encoding="utf-8") as fh:
        return model_cls.model_validate(json.load(fh))
