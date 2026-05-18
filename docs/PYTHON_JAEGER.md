# python_jaeger

**Self-improving local agent with multi-instance isolation, versioned skill authoring, sandboxed file ops, credential store, and a plugin system for MCP / messaging / voice / background thinking.**

Jaeger is the flagship framework in this repo. It started as a fork of [`python_pydantic_ai`](PYTHON_PYDANTIC_AI.md) and inherited that framework's routing core (`agent.iter()` + skip-final intercept), then added the production guarantees needed to actually ship an agent: instance isolation, skill versioning with smoke-test gating, credential isolation, git auto-commit per agent-authored write, manifest + migration runner, full voice loop with optional AEC-based barge-in, and a plugin system mirroring pydantic_ai's.

**Benchmark status:** 23/23 on the routing bench, tied with `python_pydantic_ai`.

---

## Entry points

```bash
# Interactive chat (auto-enables --with-memory)
python -m python_jaeger
python -m python_jaeger --instance work

# One-shot
python -m python_jaeger "what time is it"
python -m python_jaeger --with-mcp "list the files on my Desktop"

# Voice loop — STT → agent → TTS, with optional wake-word and barge-in
python -m python_jaeger --voice
python -m python_jaeger --voice --require-wake-word --barge-in
python -m python_jaeger --voice --stt-mode continuous
python -m python_jaeger --voice --help                  # see all voice flags

# Instance management (admin commands; exit without launching chat)
python -m python_jaeger --list-instances
python -m python_jaeger --create-instance work
python -m python_jaeger --clear-instance default        # wipes memory + logs only
python -m python_jaeger --delete-instance temp          # nukes the dir
python -m python_jaeger --setup                         # interactive wizard (re)setup

# Smoke test (no LLM load)
python -m python_jaeger --self-test

# Credential management
python -m python_jaeger --set-credential OPENWEATHER_API_KEY   # value from stdin
python -m python_jaeger --list-credentials
python -m python_jaeger --delete-credential OPENWEATHER_API_KEY

# Messaging gateway (Discord + Telegram + iMessage)
python -m python_jaeger.plugins.messaging_gateway
```

| Flag | Effect |
|---|---|
| `--instance NAME` | Pick which instance dir to load (default: `JAEGER_INSTANCE_NAME` or `default`) |
| `--voice` | Launch the voice loop daemon instead of CLI chat (subsequent flags pass through to voice_loop) |
| `--with-memory` | Carry conversation across turns (auto-on in interactive) |
| `--with-mcp` | Connect to MCP servers from `plugins/mcp/mcp_config.json` |
| `--think` | Run a background chain-of-thought after each turn |
| `--no-warmup` | Skip the cold-cache prewarm at startup |
| `--no-cron` | Don't start the cron runner |
| `--migrate` | Apply pending core migrations to the instance |
| `--list-instances` | Print every instance under the root and exit |
| `--create-instance NAME` | Non-interactively create with default identity / config |
| `--clear-instance NAME` | Wipe memory + logs but keep identity / config / credentials / skills |
| `--delete-instance NAME` | Remove the entire instance dir (prompts unless `--force`) |
| `--force` | Skip confirmation on mutating instance commands |

---

## Instance dir layout

Every jaeger run is bound to one instance directory. Default is `python_jaeger/instance/default/` (pre-seeded for dev). Production deployments use `~/.jaeger/<name>/`.

```
<instance>/
├── identity.yaml          ← name, role, personality, voice_tone — the human writes this
├── config.yaml            ← model path, ctx, display flags, skills config
├── manifest.json          ← core_version pin, created_at, instance_name
├── memory/
│   ├── facts.json         ← k/v store, fcntl-locked
│   ├── episodic.jsonl     ← append-only cross-session turn log (only written when --with-memory)
│   └── episodic.embeddings.npz   ← sentence-transformers index for search_memory
├── logs/
│   ├── latency.jsonl      ← per-turn latency, structured
│   ├── audit.log          ← every sandbox-relevant op (file_write, credential_get, etc.)
│   └── thinking.jsonl     ← background CoT (when --think is on)
├── credentials/           ← per-credential files, ONLY readable via get_credential()
├── skills/                ← agent-writable skill folders (see skill loader below)
└── .lock                  ← fcntl exclusive lock; prevents two jaeger processes per instance
```

The instance dir is **not** committed to the framework repo. The pre-seeded `python_jaeger/instance/default/` is included so you can run jaeger immediately without going through the wizard.

---

## Instance management

Multiple instances are supported out of the box. Each is identified by name; the active one comes from `JAEGER_INSTANCE_NAME` (env var) or defaults to `default`.

### CLI commands (admin operations — never enter the chat loop)

```bash
# List every instance under the root, marking the active one with *
python -m python_jaeger --list-instances

# Create a fresh instance non-interactively (defaults — edit identity.yaml after)
python -m python_jaeger --create-instance work

# Clear an instance: wipe memory + logs, KEEP identity / config / credentials / skills
python -m python_jaeger --clear-instance work          # prompts y/N
python -m python_jaeger --clear-instance work --force  # skip prompt

# Delete an instance entirely. Prompts for confirmation (type the name to confirm).
# Refuses to delete the currently-active instance without --force.
python -m python_jaeger --delete-instance temp
python -m python_jaeger --delete-instance temp --force
```

The clear / delete commands refuse non-interactive runs (piped stdin) unless `--force` is passed — protects against accidental destruction from shell scripts.

### In-chat slash commands (read-only)

While in the chat loop, mutation requires a restart (the instance dir is held under an exclusive `fcntl` lock). Read-only inspection works:

```
/instances        list every instance, mark the active one
/whoami           show current instance + identity (name / role)
```

To switch instances, exit the chat (`/quit`) and re-launch with `--instance NAME`.

### Trust zones (from the v2 contract)

| Zone | Path | Who can write |
|---|---|---|
| Framework skills | `python_jaeger/skills/` | framework developer only — read-only at runtime |
| Instance skills | `<instance>/skills/` | the agent (via `file_write`); append-only versioning |
| Instance config | `<instance>/{identity,config,manifest}.yaml/json` | the human (wizard or hand-edit) — read-only to the agent |
| Instance credentials | `<instance>/credentials/` | the human (via `--set-credential`) — agent reads via `get_credential`, never directly |
| Plugins | `python_jaeger/plugins/` | framework developer only — read-only at runtime |

The agent CANNOT delete or overwrite a prior skill version even in the instance zone; the loader treats each `<name>_v<N>/` folder as immutable once smoke-tested. To deprecate, the agent writes a new `<name>_v<N+1>/` with the changed behavior.

---

## Tool surface

33 built-in tools across 14 categories, plus dynamically-registered skills and MCP tools.

| Category | Tools | Notes |
|---|---|---|
| Memory (k/v) | `remember`, `recall`, `forget`, `list_facts`, `search_memory` | facts.json + semantic episodic search |
| Files | `file_write`, `append_file`, `delete_file`, `file_read`, `list_skill_dir` | sandboxed to `<instance>/skills/` |
| Time / math | `get_time`, `calculate`, `system_status` | `calculate` supports sqrt/log/sin/cos/etc. |
| Web | `web_search`, `get_weather` | DuckDuckGo + wttr.in (no API key) |
| Speech | `speak`, `speak_file` | Kokoro TTS |
| Vision | `look_at`, `generate_image` | Moondream2 VLM + SDXL-Turbo |
| Host control | `launch_url`, `open_file`, `open_app` | macOS only |
| Scheduling | `schedule_prompt`, `list_schedules`, `cancel_schedule` | fired by CronRunner |
| Code | `run_python` | sandboxed subprocess, 10s timeout |
| Credentials | `get_credential`, `list_credentials` | values never echoed back |
| Coordination | `delegate`, `ask_user`, `help_me` | sub-agent + clarification |
| Messaging | `send_message` | proactive Discord/Telegram/iMessage push |
| Skill authoring | `reload_skills` | re-scan + register newly authored skills |

Every tool's source lives in `python_jaeger/core/tools/<category>.py` — one file per category. Tools are re-exported from `core/tools/__init__.py`. Wrappers in `main.py:_register_builtins` attach them to the agent with prompt-friendly docstrings.

---

## Skill loader and versioning

Skills (`<instance>/skills/<name>_v<N>/`) are the writable, hot-reloadable surface. The agent can author, version, and load its own skills at runtime.

A valid skill folder contains:

```
skills/example_v1/
├── SKILL.md             ← human-readable description + when to call
├── example.py           ← module with `register(agent)` that calls @agent.tool_plain
└── tests/
    └── smoke_test.py    ← must pass before the skill is registered
```

**Override via versioning.** Both `<core>/skills/` and `<instance>/skills/` are scanned. If both have `say_hello`, the highest version wins; instance beats core on ties. So patching a built-in is "drop a `say_hello_v2/` into the instance dir."

**Smoke tests gate activation.** The loader (`core/skill_loader.py`) runs each skill's `tests/smoke_test.py` before registering it. Failure → the skill is skipped with an audit log entry, the agent must fix and call `reload_skills()` again.

**`reload_skills` tool.** After the agent authors a new skill, it calls `reload_skills()` to discover and register the new code without restarting the process.

---

## v2 self-improvement contract

The contract that defines "how a self-modifying agent should behave" — skill versioning rules, rollback paths, smoke-test requirements, what's never editable — lives at `python_jaeger/prompts/agent_system_prompt.md` (115 lines, ~900 words).

It used to load into the system prompt unconditionally. That was costing 3/23 on the routing bench because the extra prompt mass diluted the MANDATORY rules near the top. So it's now **gated behind `skills.include_self_improvement_contract: true` in config.yaml** — opt-in when the agent is actively authoring skills.

```yaml
# config.yaml
skills:
  include_self_improvement_contract: true   # turn on when skill-authoring
```

The lean default keeps jaeger at parity with `python_pydantic_ai` on routing benchmarks; the rich mode unlocks the full safety contract.

---

## Routing loop

Mirrors `python_pydantic_ai` exactly: `agent.iter()` async drive loop with skip-final intercept.

1. User prompt arrives in `run_command(client, user_text, session_key)`.
2. Agent iterates: each `CallToolsNode` exposes the first tool call.
3. If the tool is in `SKIP_FINAL_TOOLS` (24 tools — get_time, calculate, remember, file_write, send_message, etc.) AND it's the only call, we intercept on the next `ModelRequestNode` to grab the tool result, format it via `_format_tool_result_as_answer`, and exit early — bypassing the would-be "final-answer" LLM call. Saves ~280 ms.
4. Otherwise pydantic-ai's normal flow completes the turn.
5. Post-turn: optionally accumulate history (`with_memory`), optionally queue background CoT (`thinking_runner`).

The `_get_agent` cache rebuilds when the MCP fingerprint changes, so adding an MCP server takes effect on the next prompt without a restart.

---

## Memory model

By default, jaeger runs **fresh-context per prompt** — no episodic load, no in-process accumulation. This mirrors `python_pydantic_ai` and is what keeps the routing benchmark at 23/23.

When `--with-memory` is on (auto-enabled in interactive chat, set explicitly by gateway):

- Last 5 episodic turns load from `<instance>/memory/episodic.jsonl` at first prompt per `session_key`.
- New turns accumulate in the in-process history (capped at `_MAX_HISTORY_MESSAGES = 20`).
- Each turn is appended to the on-disk episodic log via `_record_episodic`.
- `search_memory(query, k)` does semantic search via sentence-transformers over the same log.

`session_key` lets the messaging gateway keep per-channel histories isolated (`telegram:12345` doesn't see `discord:67890`).

---

## Plugin system

Plugins live in `python_jaeger/plugins/` — each is a drop-in external
integration with its own `plugin.yaml` manifest and smoke test. See
[VOCABULARY.md](VOCABULARY.md) for the strict definition.

### `plugins/mcp/` — Model Context Protocol

Connects to MCP server processes listed in `plugins/mcp/mcp_config.json`.
Each server's advertised JSON Schema becomes a pydantic-ai `Tool`
dynamically — no code change to add a new server.

```bash
python -m python_jaeger --with-mcp  # or JAEGER_WITH_MCP=1
```

Tools register on first agent build after MCP comes online; the `_get_agent`
cache rebuilds when the MCP fingerprint changes.

### `plugins/discord/`, `plugins/telegram/`, `plugins/imessage/` — messaging

Per-integration plugins; each registers a bridge in the shared registry
(`plugins/__init__.py`) so the `send_message(channel, recipient, text)`
agent tool can push proactive messages.

| Plugin | Activates when | Needs |
|---|---|---|
| `discord/` | `DISCORD_BOT_TOKEN` is set | `discord.py` |
| `telegram/` | `TELEGRAM_BOT_TOKEN` is set | `python-telegram-bot` |
| `imessage/` | `IMESSAGE_ALLOWED_HANDLES` set + macOS + Full Disk Access | — |

Run all three behind one daemon via the gateway:

```bash
python -m python_jaeger.plugins.messaging_gateway
```

The gateway daemon (`plugins/messaging_gateway.py`) loads jaeger once and
starts every plugin with valid credentials. It's NOT a plugin itself —
it's the orchestrator daemon. Each bridge runs in its own thread and
shares the LLM lock so two channels can't decode concurrently.

### `plugins/kokoro_tts/` — text-to-speech

Synthesizes the agent's reply via the Kokoro KPipeline and plays through
the default audio output. Two playback modes:

- `speak(text)` — synchronous; blocks until playback finishes. Used by
  the `speak`/`speak_file` agent tools.
- `play_async(text)` — chunked, non-blocking. Starts playing as the first
  Kokoro chunk renders so the user can interrupt with barge-in. Used by
  the voice loop in `--barge-in` mode.

Both apply `clean_for_tts()` to the input — strips markdown so Kokoro
doesn't read asterisks / code fences / link syntax literally.

### `plugins/whisper_stt/` — speech-to-text

Microphone capture + transcription. Two algorithms with the same public
API (`start`, `stop`, `next_phrase`, `set_paused`, `open_followup`,
`set_on_speech_detected`, `drain_pending`):

- `two_pass` (default) — VAD-segmented; fast base.en model gates the
  accurate medium.en model. Robust to noisy backgrounds.
- `continuous` — energy-segmented with rolling re-transcription. Lower
  commit latency, lighter memory footprint.

Both support wake-word gating (`require_wake_word=True`, default phrases
include `hey jaeger / yeager / yager / jager` to cover Whisper mishears),
follow-up windows, and optional AEC integration.

### `plugins/voice_loop.py` — voice daemon

Wires STT → agent → TTS into one synchronous loop with optional barge-in.
Not a plugin itself (no external integration) — it's the orchestrator
that owns the audio devices. Same role as `messaging_gateway.py`.

```bash
python -m python_jaeger --voice                                       # CLI entry
python -m python_jaeger --voice --require-wake-word --barge-in        # robot mode
python -m python_jaeger --voice --stt-mode continuous --no-aec        # tuned
```

Voice-loop flags (forwarded after `--voice`):

| Flag | Effect |
|---|---|
| `--stt-mode {two_pass,continuous}` | pick the STT algorithm (default: two_pass) |
| `--require-wake-word` | every utterance must start with a wake phrase |
| `--barge-in` | user can interrupt the AI mid-speech (non-blocking TTS) |
| `--no-aec` | force AEC passthrough even if speexdsp is installed |
| `--no-chimes` | disable wake / follow-up earcons |
| `--no-cron` | skip the cron runner |
| `--fast-model NAME` | Whisper fast/continuous model (default: base.en) |
| `--accurate-model NAME` | Whisper accurate model — two_pass only (default: medium.en) |

Barge-in works in two modes:
- **With speexdsp installed** — full AEC: the TTS audio gets pushed to a
  ReferenceBuffer at 16 kHz, and the mic-capture callback cancels it out
  of the captured frame before VAD sees it. Sub-50 ms latency interrupts
  via a VAD-thread callback (no main-loop polling).
- **Without speexdsp** — AEC is passthrough; the open mic will hear TTS
  bleed-through and the wake-word matcher may misfire. Acceptable for
  bench / demo; install `speexdsp` for production.

### `core/audio/` — voice infrastructure (not plugins)

Library-layer helpers used by the voice plugins:

| File | Role |
|---|---|
| `aec.py` | `AECWrapper` — speexdsp facade with passthrough fallback |
| `reference_buffer.py` | thread-safe ring buffer for AEC far-end audio |
| `chimes.py` | pre-synthesized wake (A5) + follow-up (E5→B5) earcons |

### Runners (not plugins)

The framework also has internal background loops that aren't plugins:

- `core/runners/thinking_runner.py` — fires a CoT call after each user
  turn on a single-worker pool. Logs to `<instance>/logs/thinking.jsonl`.
  Enable with `--think` or `JAEGER_WITH_THINKING=1`.
- `core/cron_runner.py` — fires scheduled prompts at their cron times.
  Started automatically at boot unless `--no-cron`.

---

## Sandbox guarantees

Every write goes through `_resolve_under(layout.skills_dir, path)`:

- Absolute paths rejected
- `..` rejected
- Symlinks escaping the sandbox rejected
- A leading `<root.name>/` is stripped so `skills/foo.txt` and `foo.txt` both resolve correctly (a Gemma 4 quirk; without this, the agent's natural `skills/...` paths produced `skills/skills/...`)

**Off-limits to writes:** identity.yaml, config.yaml, manifest.json, memory/, logs/, credentials/, the framework's own `core/` files. Reads are allowed everywhere under `<instance>` except `credentials/`.

**Credentials.** `<instance>/credentials/` is the only directory the file tools refuse to read. The agent must use `get_credential(name)` — and is system-prompted to never echo the returned value back to the user.

**Git auto-commit.** Every successful `file_write` / `append_file` / `delete_file` triggers a `git add` + `git commit` inside the instance repo, authored as `jaeger-agent <agent@local>`. So every skill-authoring action lands as a real commit you can revert, blame, or audit.

---

## Configuration files

### `identity.yaml`
```yaml
name: Lilith
role: fast local AI tool router
personality: |
  Concise and direct. Match tool calls to the user's intent — never
  free-text when a tool exists for the request.
voice_tone: warm but terse
```

### `config.yaml`
```yaml
instance_name: default
model:
  model_path: ~/.lmstudio/models/.../gemma-4-26B-A4B-it-Q4_K_M.gguf
  ctx: 8192
  gpu_layers: -1
  n_batch: 512
  flash_attn: true
display:
  show_latency: false
  show_tool_activity: true
  show_help_on_start: true
skills:
  enabled_base_skills: []        # empty = enable all
  run_smoke_tests: true
  include_self_improvement_contract: false   # opt-in for skill authoring
retention:
  rotate_logs_at_bytes: 10485760
  prune_log_older_than_days: 30
```

### `manifest.json`
```json
{
  "instance_name": "default",
  "core_version": "1.3.0",
  "created_at": "2026-05-13T18:24:00Z"
}
```

If `core_version` falls behind the framework version, jaeger refuses to start until you run `--migrate` (or the migration runner auto-applies pending core migrations on startup).

---

## Key files

| Path | Purpose |
|---|---|
| `main.py` | CLI, agent build, `run_command`, `run_for_voice`, `init_extensions`, `shutdown_extensions` |
| `core/prompts.py` | `build_system_prompt(layout)` — identity + MANDATORY rules + optional v2 contract |
| `core/instance.py` | `InstanceLayout`, `default_instance_name`, `resolve_instance_dir` |
| `core/schemas.py` | Pydantic schemas for identity / config / manifest |
| `core/memory.py` | facts.json read/write, episodic append, fcntl lock |
| `core/credentials.py` | `get_credential`, `list_credentials`, encrypted store |
| `core/skill_loader.py` | Discover + smoke-test + register skills |
| `core/migrations/` | Pending-migration runner |
| `core/cron_runner.py` | Background thread for `schedule_prompt` |
| `core/tools/*.py` | One file per tool category |
| `prompts/agent_system_prompt.md` | The v2 self-improvement contract (opt-in) |
| `plugins/__init__.py` | shared bridge registry (register_bridge / get_bridge / list_bridges) |
| `plugins/mcp/client.py` | MCP server registry + tool routing |
| `plugins/discord/`, `plugins/telegram/`, `plugins/imessage/` | per-integration messaging bridges |
| `plugins/messaging_gateway.py` | top-level daemon orchestrating the messaging plugins |
| `core/runners/thinking_runner.py` | background CoT runner (NOT a plugin — framework-internal) |
| `core/cron_runner.py` | scheduled-prompt runner (NOT a plugin) |

---

## Benchmark dispatch

Jaeger is benchmarked via subprocess (`benchmark/bench_worker.py`) — its own Python process gets a fresh Metal context every run, isolating it from the in-process trio.

The bench uses **soft validation** for jaeger: "any tool fired when one was expected" passes, rather than strict tool-name matching. Why: jaeger's tools have different names than the other three (`file_write` vs `create_file`, `list_skill_dir` vs `list_directory`) but the *semantics* match.

```bash
python benchmark/bench.py --only python_jaeger --with-jaeger
```

---

## Related docs

- [VOCABULARY.md](VOCABULARY.md) — locked-down definitions of Tool / Skill / Plugin / Runner + infrastructure layers
- [PYTHON_PYDANTIC_AI.md](PYTHON_PYDANTIC_AI.md) — the parity reference jaeger forked from
- [FRAMEWORKS.md](FRAMEWORKS.md) — side-by-side comparison of all five
- [AGENTIC_CODING_PRACTICE.md](AGENTIC_CODING_PRACTICE.md) — the v2 contract written as guidance for AI agent developers
- [ARCHITECTURE.md](ARCHITECTURE.md) — request pipeline + framework differences
