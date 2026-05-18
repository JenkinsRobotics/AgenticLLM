# Vocabulary Contract

**The locked-down naming convention for AgenticLLM.** Read this first when designing new components. When in doubt about what to call something or where to put it, follow the decision tree at the bottom.

This document supersedes any earlier vocabulary draft. It is the single source of truth for component categories, trust zones, and the upgrade paths between them.

---

## Why vocabulary matters

Three things compound when a project's component vocabulary is sloppy:

1. **File locations drift.** "Plugin" means three different things in three different directories, code search becomes archaeology.
2. **Trust boundaries blur.** Without crisp categories, framework-shipped code and agent-authored code mix freely — and the safety guarantees of the v2 self-improvement contract evaporate.
3. **Upgrade paths get blocked.** When you can't tell whether something is "really a plugin" or "really a skill," you can't reason about how to replace it cleanly.

This contract gives every component exactly one category and exactly one home directory.

---

## The categories

### Agent-callable surface

Three things the LLM reasons about and calls into:

**Tool** — atomic LLM-callable function.
- Lives in core, in a plugin, or in a skill (any of the three can register tools)
- Has a stable signature the model is prompted to call
- Examples: `get_time`, `remember`, `file_write`, `speak`, `send_message`

**Skill** — composite capability bundle.
- Folder with `SKILL.md` + module + `tests/smoke_test.py`
- Versioned (`foo_v1/`, `foo_v2/`)
- Smoke-test gated before activation
- Authored by humans, by the agent at runtime, learned from experience, or NN-trained
- Registers one or more tools when loaded
- Examples: `example_v1/`, future `play_tic_tac_toe_v1/`, future `classify_object_v1/`

**Plugin** — drop-in module adding an *external integration*.
- Has a `plugin.yaml` manifest declaring deps + tools registered
- Bridges the agent to a specific external service or capability (Discord API, MCP server, Kokoro TTS, Whisper STT, RealSense camera, etc.)
- In-process Python today; can promote to a separate-process daemon for robot deployment
- Registers tools that show up on the agent's surface
- Examples: `discord/`, `telegram/`, `imessage/`, `mcp/`, future `kokoro_tts/`, `whisper_stt/`

### Framework-internal

One thing the agent does NOT call into:

**Runner** — framework-owned background loop.
- Not callable by the agent (no tool wrapper)
- Not an external integration (no `plugin.yaml`)
- Pure framework infrastructure that just runs
- Examples: `thinking_runner` (background CoT), `cron_runner` (scheduled prompts)

### Infrastructure layers

Four supporting layers that everything sits on top of:

**Library** — importable Python package.
- Examples: `pydantic_ai`, `llama_cpp`, `discord.py`, `torch`, `whisper`, `kokoro-tts`

**Model / Artifact** — data file used at runtime.
- Examples: `gemma-4-26B-A4B.gguf`, Kokoro voice files, Whisper weights, YOLO checkpoints, fine-tuned LoRA adapters

**Transport / Protocol** — wire format or messaging substrate.
- Not callable in itself
- Examples: MCP-over-stdio, ZMQ, HTTP, WebSocket

**Hardware** — physical device.
- Accessed by a plugin or skill
- Examples: microphone, speaker, RealSense D435, Jetson GPU, servos

---

## The four skill flavors

Every skill has a `kind:` field in its `SKILL.md` frontmatter declaring how it was created. Different flavors get different trust profiles.

| Kind | Source | Trust zone | Gating |
|---|---|---|---|
| `human_authored` | shipped by framework developer | framework (`python_jaeger/skills/`) | read-only at runtime; trusted by definition |
| `agent_authored` | agent wrote code via `file_write` + `reload_skills` | instance (`<instance>/skills/`) | smoke test must pass; append-only versioning; prior versions locked |
| `learned` | agent observed trajectories and distilled into skill | instance (`<instance>/skills/`) | smoke test + trajectory-replay validation |
| `nn_trained` | offline ERL / fine-tune pipeline produced weights | instance (`<instance>/skills/`) | smoke test + declared deps must resolve (weights, GPU, etc.) |

All four use the same folder pattern (`SKILL.md` + module + tests). The `kind:` field is what lets the skill loader apply the right gating policy.

**Why one container for four flavors?** Same shape, same loader, same override mechanism. The LLM's tool surface looks the same regardless of how the skill was created — only the trust boundaries differ underneath.

### Example SKILL.md

```yaml
---
name: classify_object
version: 1
kind: nn_trained
authored_at: 2026-05-17
description: Identifies objects in workspace images using a fine-tuned YOLOv8 model.
requires:
  libraries: [torch, opencv-python, ultralytics]
  models: [yolov8n_finetuned.pt]
  hardware: [gpu]
registers_tools:
  - classify(image_path) -> {labels, confidence}
---

# classify_object_v1

Trained by the ERL pipeline on the household-objects dataset.
Weights bundled at `weights/yolov8n_finetuned.pt`.
```

---

## Trust zones

Two zones for skills, one for plugins. Each has explicit permissions.

| Zone | Path | Agent permission | Notes |
|---|---|---|---|
| **Framework skills** | `python_jaeger/skills/` | **read-only at runtime** | Cannot be modified or shadowed in-place. Agent can author a higher version in instance zone to override. |
| **Instance skills** | `<instance>/skills/` | **append-only versioning** | Agent can write `foo_v2/` but cannot delete or modify `foo_v1/`. Prior versions stay as rollback paths. Each new version must pass smoke tests before activation. |
| **Plugins** | `python_jaeger/plugins/` | **read-only at runtime** | Plugins are framework-shipped or human-installed, never agent-authored. A plugin update is a code change, not an agent action. |

The instance zone is the ONLY agent-writable zone for capability code. Everything else is human/framework/installer territory.

### Override-via-versioning works across categories

If a plugin registers `speak()` at version 1, an instance skill named `kokoro_tts_v2` (or `expressive_speak_v1`) that ALSO registers `speak()` will shadow it. The skill loader registers higher-priority sources last; later registrations win on tool-name collision.

This is the upgrade path: **plugin → skill is a natural evolution.** A plugin provides the initial capability; over time, the agent or developer can author a skill that improves on it without modifying the plugin.

---

## How a capability swaps backends

The single most important property of this design: **the agent's tool calls don't change when we swap the implementation under the hood.** Four ways to swap:

**1. Plugin ↔ Plugin (config-driven).**
- Install `plugins/piper_tts/` alongside `plugins/kokoro_tts/`. Both register `speak()`.
- Config flag `tts.plugin: piper_tts` selects which one loads.
- Agent code unchanged. Agent prompts unchanged. Different voice.

**2. Plugin version bump (single plugin, multiple backends).**
- `plugins/kokoro_tts/plugin.yaml` declares `engine: piper`.
- Plugin's `tts.py` switches backends based on the engine field.
- Useful when staying in the same engine family.

**3. Plugin → Skill (agent learns a better way).**
- Plugin `kokoro_tts` registers `speak()` at version 1.
- Agent writes `<instance>/skills/expressive_speak_v1/` registering `speak()` with prosody preprocessing.
- Skill takes priority via override-via-versioning. Plugin's `speak` becomes the fallback the skill calls internally.

**4. Skill → NN-trained skill (ERL pipeline output).**
- Trained model bundled as `<instance>/skills/custom_tts_v1/` with `kind: nn_trained`.
- Weights inside the bundle; SKILL.md declares hardware/library deps.
- Registers `speak()` → shadows everything above.
- Plugin can be uninstalled; the trained skill stands on its own.

In all four cases, the LLM's view of `speak("hello")` stays identical. Stable tool name = swappable backend.

---

## Three operational caveats

Not blockers — just real considerations any plugin/skill system has:

1. **Tool signatures should stay stable across versions.** If `speak(text)` becomes `speak(text, voice=None)`, that's fine (optional kwarg). If `voice` becomes required, that's breaking — bump the major plugin/skill version and treat as a hard migration.
2. **Declare capabilities in manifests.** If one TTS supports SSML and another doesn't, the prompt-builder needs to know — a `capabilities: [ssml, emotion, voice_clone]` field in `plugin.yaml` handles this. Otherwise the agent's prompt references features the active backend can't honor.
3. **One active owner per hardware device.** Two TTS plugins can't both grab the speaker simultaneously. The loader enforces "only one plugin claims `hardware: [speaker]` at a time." Same for mic, camera, etc.

---

## Decision tree

When in doubt, apply in order and take the first match:

1. Is it a **physical device**? → **Hardware**. A plugin interfaces with it.
2. Is it a **data file** (weights, voices, datasets)? → **Model / Artifact**. A plugin or skill bundles or references it.
3. Is it a **wire format or messaging substrate**? → **Transport / Protocol**. Plugins ride on it.
4. Is it an **importable Python package**? → **Library**. Used by core, plugins, or skills.
5. Is it a **framework-owned background loop**, not called by the agent? → **Runner**.
6. Is it a **drop-in module bridging the agent to a specific external service/capability**? → **Plugin**.
7. Is it a **folder with `SKILL.md` containing a composite capability** (authored, learned, or trained)? → **Skill**.
8. Is it a **single function the LLM calls directly**? → **Tool**.

If nothing matches, the component doesn't belong in the framework — likely a design error.

---

## Directory layout

The vocabulary maps onto the source tree like this:

```
python_jaeger/
├── core/
│   ├── tools/                  ← framework atomic Tools (one file per category)
│   ├── runners/                ← framework Runners (background loops)
│   │   ├── thinking_runner.py
│   │   └── cron_runner.py (eventually)
│   └── ...                     ← schemas, instance, prompts, skill_loader, etc.
├── plugins/                    ← drop-in external integrations
│   ├── __init__.py             ← shared bridge registry
│   ├── README.md               ← how plugins work, how to add one
│   ├── discord/
│   │   ├── plugin.yaml
│   │   ├── bridge.py
│   │   └── tests/smoke_test.py
│   ├── telegram/
│   ├── imessage/
│   ├── mcp/
│   │   ├── plugin.yaml
│   │   ├── client.py
│   │   ├── mcp_config.json
│   │   └── tests/smoke_test.py
│   ├── (future) kokoro_tts/, whisper_stt/, realsense/, yolo/
│   └── messaging_gateway.py    ← daemon orchestrating all messaging plugins
├── skills/                     ← framework-shipped Skills (read-only zone)
│   └── example_v1/
│       ├── SKILL.md
│       ├── example.py
│       └── tests/smoke_test.py
└── prompts/                    ← system-prompt source files

<instance>/                     ← per-deployment instance dir (~/.jaeger/<name>/)
├── skills/                     ← instance Skills (agent-writable, append-only)
├── memory/                     ← per-instance facts + episodic
├── logs/                       ← per-instance latency + audit
├── credentials/                ← per-instance secrets
└── ...
```

---

## Where models and assets live on disk

The **Model / Artifact** category covers a wide size range (KBs to tens of GBs) and several different ownership patterns. There's no single "models/" directory because the right home depends on size, source, and who owns the file. Four locations, each with a clear purpose:

| Kind | Example | Typical size | Location | Committed? |
|---|---|---|---|---|
| **Heavy LLM weights** | Gemma 4 26B Q4_K_M GGUF | 10–30 GB | External cache: `~/.lmstudio/models/...` (default) or `~/.cache/agenticllm/models/`. Resolved via config (`<instance>/config.yaml` `model.model_path`) or the `HERMES_LLM_MODEL` env var. | **No** — too large; users download once and reuse across all five frameworks |
| **Per-plugin model files** | Kokoro voice files, Whisper weights, MoonDream2 VLM | 10 MB – 2 GB | If small and the plugin ships with them: inside the plugin (`plugins/kokoro_tts/voices/af_heart.pt`). If user-supplied or large: external, with the path declared in `plugin.yaml` under `requires.models`. | Small ones yes, large ones no — case by case |
| **Static repo assets** | logos, banners, demo audio bundled with docs, smoke-test fixtures | tens of KB | `python_jaeger/assets/` (per-framework, framework zone). Not agent-writable, not large. | **Yes** — small enough to live in git |
| **NN-trained skill weights** | fine-tuned YOLO checkpoint, custom TTS adapter | 100 MB – 5 GB | Inside the skill bundle: `<instance>/skills/classify_object_v1/weights/yolov8n_finetuned.pt`. The skill *is* the weights + inference code together — they ship as one unit. | Depends on deployment — for robot ship, yes (committed alongside the skill); for local dev with frequent retraining, gitignored |

### The Gemma weights case (today's reality)

All five frameworks default to:

```
~/.lmstudio/models/lmstudio-community/gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf
```

Override with `HERMES_LLM_MODEL=/your/path.gguf` (env var name is legacy — predates the multi-framework split, will rename to `AGENTICLLM_MODEL_PATH` in a cleanup pass). The path is duplicated in:

- `agent_doctor.py` (preflight check)
- `plugins/voice_loop.py` (resolves via the framework's main.py)
- `benchmark/bench_worker.py` (subprocess bench)
- `python_jaeger/instance/<name>/config.yaml` (per-instance config — preferred read path going forward)

Jaeger's per-instance config is the cleanest source of truth: `<instance>/config.yaml` `model.model_path` resolves the path at startup, with the LM Studio default if unset. Other frameworks haven't migrated to that pattern yet.

### Plugin-declared models

When a plugin needs a specific model file (Whisper weights, Kokoro voices, etc.), it declares the requirement in its `plugin.yaml`:

```yaml
# plugins/whisper_stt/plugin.yaml
name: whisper_stt
version: 1
requires:
  libraries: [whisper]
  models:
    - name: whisper-base.en
      path_env: WHISPER_MODEL_PATH
      default_path: ~/.cache/whisper/base.en.pt
      size_mb: 142
      url: https://openaipublic.azureedge.net/main/whisper/models/...
```

The plugin loader checks each required model exists before activating the plugin. If `default_path` is missing and the user hasn't set `path_env`, the loader can either skip the plugin (with an audit log) or trigger an auto-download via the `url`. Auto-download is opt-in (per-plugin or framework-wide) so we never surprise the user with a 2 GB download.

### Skill-bundled weights

For `nn_trained` skills, weights live inside the skill folder:

```
<instance>/skills/classify_object_v1/
├── SKILL.md              ← declares kind: nn_trained, hardware reqs
├── classify.py           ← inference code
├── weights/
│   ├── yolov8n_finetuned.pt    ← the model
│   └── class_names.json        ← label map
└── tests/
    └── smoke_test.py     ← checks weights load + dummy inference works
```

The skill is the unit of versioning — `classify_object_v2/` would bundle a different (potentially retrained) checkpoint. The `<instance>/skills/` zone is agent-writable, so an offline ERL pipeline can drop a new version in place and `reload_skills()` picks it up. Smoke tests gate activation.

### Why this layout

The split is dictated by three properties of the file:

1. **Size** — anything >100 MB shouldn't be committed; anything <1 MB should be
2. **Ownership** — framework ships it (assets/), plugin needs it (plugins/<name>/), or the skill IS it (skills/<name>_vN/weights/)
3. **Reuse** — Gemma is shared by all 5 frameworks and 10+ users on the team → external cache; YOLO weights are specific to one skill → bundled with it

When in doubt: small + framework-shipped → `assets/`; small + plugin-specific → `plugins/<name>/`; large + external default → declared in `plugin.yaml` with path/env-var; trained-model-IS-the-skill → `<instance>/skills/<name>_vN/weights/`.

---

## Common misclassifications

- **"ZMQ is a plugin."** No. ZMQ is the Transport. A node speaking ZMQ is a Plugin; ZMQ itself isn't.
- **"Kokoro TTS is a skill."** No. Kokoro the library is a Library. Voice files are Models. The `kokoro_tts` integration is a Plugin. `speak()` is the Tool the agent calls. If the agent later writes a wrapper to add prosody, THAT wrapper is a Skill.
- **"PyTorch is a tool."** No. PyTorch is a Library. A Tool or Skill might internally use PyTorch.
- **"thinking_runner is a plugin."** No. It's a Runner — framework-internal background work, no external integration. Lives in `core/runners/`.
- **"MCP is a plugin."** No. MCP is the Transport. MCP *servers* (GitHub MCP, Filesystem MCP, etc.) are plugins. Our `plugins/mcp/client.py` is the *plugin that connects to them*.
- **"Discord is a skill."** No. Discord is an external service. The integration to it is a Plugin (`plugins/discord/`). The agent uses `send_message` (Tool) which the plugin registered.
- **"whisper.cpp is a tool."** No. whisper.cpp is a Library. The `whisper_stt` Plugin uses the library. The Plugin registers `listen()` and `transcribe_audio()` Tools.

---

## Comparison to hermes-agent

For reference, since hermes-agent is a public production framework using related but different vocabulary:

| Concept | hermes-agent | AgenticLLM (this contract) |
|---|---|---|
| **Tool** | 70+ atomic capabilities | identical concept |
| **Toolset** | grouping of related tools | implicit — we file tools one-per-category (`core/tools/files.py` etc.) |
| **Channel** | 20+ messaging platforms (Discord, Telegram, Slack, …) | a Plugin with a messaging bridge |
| **Backend** | 6 execution environments (local, Docker, SSH, Modal, …) | not yet a first-class category; will add when we ship robot deployment |
| **Skill** | procedural memory learned from experience | one of our four skill kinds (`learned`) — our Skill is the umbrella |
| **Memory** | FTS5 cross-session store + Honcho user modeling | per-instance `facts.json` + `episodic.jsonl` + embeddings |

Key difference: **our Skill is the superset.** Hermes only has the learned-trajectory flavor. We support four flavors (`human_authored`, `agent_authored`, `learned`, `nn_trained`) under one container. The `kind:` field disambiguates.

---

## Quick reference

When in doubt about a component, ask in order:

1. **Is it physical?** Hardware.
2. **Is it a file of data or weights?** Model.
3. **Is it a wire format?** Transport.
4. **Is it `pip install`-able?** Library.
5. **Is it a background loop that runs without the agent calling it?** Runner.
6. **Does it bridge to a specific external service?** Plugin.
7. **Is it a folder with `SKILL.md`?** Skill.
8. **Is it a function the LLM calls?** Tool.

Eight categories total. Three are agent-callable. One is internal background. Four are infrastructure. The agent sees only the three callable; everything else exists to make the three possible.

---

## Related docs

- [PYTHON_JAEGER.md](PYTHON_JAEGER.md) — concrete application of this vocabulary to the flagship framework
- [AGENTIC_CODING_PRACTICE.md](AGENTIC_CODING_PRACTICE.md) — the v2 self-improvement contract (skill versioning rules, rollback paths, smoke-test gating)
- [FRAMEWORKS.md](FRAMEWORKS.md) — how the five frameworks relate
