# AgenticLLM

A fast local agentic LLM harness on macOS. **Five agents**, all running the same local Gemma 4 26B-A4B model over different agent architectures, so you can directly compare tool-calling latency and reliability across approaches.

| Agent | Approach | Tool surface | Loop |
|---|---|---|---|
| [`python_jaeger/`](docs/PYTHON_JAEGER.md) ⭐⭐ | **Production self-improving agent** — Pydantic AI core + skill versioning + instance isolation + plugin system + voice loop | core tools + versioned skills + MCP + messaging + voice | `agent.iter()` skip-final intercept |
| [`python_pydantic_ai/`](docs/PYTHON_PYDANTIC_AI.md) ⭐ | [Pydantic AI](https://github.com/pydantic/pydantic-ai) with custom in-process llama-cpp-python `Model` adapter | 30 typed tools + voice + messaging | `agent.iter()` skip-final intercept |
| [`python_hermes_xml/`](docs/PYTHON_HERMES_XML.md) | Hand-rolled Nous Function-Calling XML format | 19 tools | `decide → tool → finalize` |
| [`python_custom_json/`](docs/PYTHON_CUSTOM_JSON.md) | Hand-rolled JSON + GBNF-grammar-constrained decode | 19 tools | `decide → tool → finalize` |
| [`python_hermes_agent/`](docs/PYTHON_HERMES_AGENT.md) | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) wrapped behind a local llama-cpp-python OpenAI-compat server | hermes' **40+ tools** | hermes' self-improving agent loop |

The first four load the model in-process and answer to a strict per-prompt latency budget (warm-cache routing in 0.3–0.5 s). The fifth runs the model behind an HTTP boundary so the full Nous framework can drive it — same offline LLM, very different agent philosophy.

See [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md) for a side-by-side breakdown, [docs/VOCABULARY.md](docs/VOCABULARY.md) for the Tool / Skill / Plugin / Runner contract, and [benchmark/BENCHMARK.md](benchmark/BENCHMARK.md) for the live latency table.

## Quickstart

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Default model path (all five frameworks read this same GGUF):

```
~/.lmstudio/models/lmstudio-community/gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf
```

The easiest way to get it is [LM Studio](https://lmstudio.ai/) — search `gemma-4-26B-A4B-it-GGUF`, pick `Q4_K_M`. See [models/README.md](models/README.md) for the repo-local symlink convention.

## Single-command entry points

**Chat (CLI):**

```bash
python -m python_jaeger                                   # ⭐⭐ jaeger, default instance
python -m python_jaeger --instance work                   # different instance
python -m python_jaeger "what time is it"                 # one-shot prompt
python -m python_pydantic_ai                              # ⭐ pydantic_ai chat
python main.py python_hermes_xml                          # hand-rolled XML
python main.py python_custom_json                         # hand-rolled JSON + GBNF
```

**Voice (jaeger + pydantic_ai only):**

```bash
python -m python_jaeger --voice                                       # default: two_pass STT, blocking TTS
python -m python_jaeger --voice --stt-mode continuous                 # alt STT algorithm
python -m python_jaeger --voice --require-wake-word                   # gated ("hey jaeger, …")
python -m python_jaeger --voice --require-wake-word --barge-in        # full robot mode (AEC if speexdsp installed)
python -m python_pydantic_ai --voice --barge-in                       # same flag surface
```

Voice combines a Whisper STT plugin (`base.en` fast pass + `medium.en` accurate commit), a Kokoro TTS plugin with chunked async playback for barge-in, and an optional speexdsp AEC layer so the AI's voice gets canceled out of mic input. See [docs/PYTHON_JAEGER.md#voice-loop](docs/PYTHON_JAEGER.md) for the full flag surface.

**Messaging gateway (Discord / Telegram / iMessage):**

```bash
DISCORD_BOT_TOKEN=… TELEGRAM_BOT_TOKEN=… python -m python_jaeger.plugins.messaging_gateway
```

## Jaeger instance management

Jaeger supports multiple isolated agent personas (instances). Each has its own identity, config, memory, credentials, logs, and skills.

| Command | What it does |
|---|---|
| `python -m python_jaeger --list-instances` | show every instance and which one is active |
| `python -m python_jaeger --create-instance NAME` | non-interactive create with default identity / config |
| `python -m python_jaeger --clear-instance NAME` | wipe memory + logs, keep identity / config / credentials / skills (prompts unless `--force`) |
| `python -m python_jaeger --delete-instance NAME` | nuke entire instance dir (prompts unless `--force`; default instance protected) |
| `python -m python_jaeger --setup` | interactive wizard (re)setup for the current instance |
| `python -m python_jaeger --instance NAME` | launch chat against a specific instance |

In-chat slash commands (read-only, no restart):

```
/instances     list all instances
/whoami        show current instance + identity
```

Mutating an instance (delete / clear / create) always requires the CLI flag and a restart; the chat loop holds an exclusive `fcntl` lock on its instance dir.

## Head-to-head benchmark

All four in-process frameworks share a 23-prompt routing benchmark. Run one framework at a time for clean Metal context:

```bash
python benchmark/bench.py --only python_jaeger --with-jaeger
python benchmark/bench.py --only python_pydantic_ai
python benchmark/bench.py --only python_hermes_xml
python benchmark/bench.py --only python_custom_json
```

Current status: **all four pass 23/23** on a fresh Metal context (multi-framework sessions can drift due to Gemma 4 temp=0 variance). See [benchmark/BENCHMARKING.md](benchmark/BENCHMARKING.md) for trend analysis and [benchmark/BENCH_RESULTS.md](benchmark/BENCH_RESULTS.md) for historical numbers.

### Voice plugin perf (no hardware required)

| Component | Result |
|---|---|
| AEC (speexdsp) | 31.7 µs per 10 ms frame — **315× realtime** |
| ReferenceBuffer round-trip | 1.14 µs / op |
| Kokoro TTS load | 5.3 s cold (one-time at startup) |
| Kokoro TTS synth | RTF 0.12–0.17 (5–8× faster than playback) |
| Whisper STT load (base.en, Metal) | 0.1 s |
| Whisper STT transcribe | ~10 ms / s of audio |

## Shared design ideas

Every framework here implements the same core ideas with different formats:

- **Skip-final-LLM optimization** — when a tool's dict result IS the user-facing answer (`get_time`, `calculate`, `remember`, `delete_file`, etc.), intercept after the tool returns and skip the second LLM call. Saves ~280 ms per simple command (~3× faster).
- **Prewarm** — run a trivial turn at startup to prime the KV cache so the first user-facing turn isn't cold.
- **Sandboxed file ops** — agents can write only inside their own workspace (`workspace/` or `<instance>/skills/`); paths like `~/Desktop` get redirected with an honest "I saved it here instead" reply.
- **MANDATORY tool routing rules** — short imperative system-prompt rules that combat the failure mode where small local models say "OK, I'll remember" without actually calling `remember`. 4 rules, near the top of the prompt.
- **with_memory gate** — by default, every prompt runs against a fresh context (bench-clean). Set `--with-memory` or `JAEGER_WITH_MEMORY=1` to accumulate conversation history.
- **Vocabulary contract** — every component is exactly one of Tool / Skill / Plugin / Runner (or infra: Library / Transport / Model / Hardware). See [docs/VOCABULARY.md](docs/VOCABULARY.md).

The fifth framework (`python_hermes_agent/`) wraps an external agent process and is its own world — see its dedicated doc.

## Production capabilities (jaeger)

The flagship framework, [`python_jaeger`](docs/PYTHON_JAEGER.md), adds production guarantees on top of the routing core:

- **Instance isolation** — each agent persona has its own `<instance>/` directory: identity, config, manifest, memory, skills, credentials, logs. Multi-tenant by design. Managed via `--list-instances` / `--create-instance` / `--clear-instance` / `--delete-instance`.
- **Skill versioning + smoke tests** — agent-authored skills land in `<instance>/skills/<name>_v<N>/` with a `SKILL.md` and a `tests/smoke_test.py`. The skill loader runs the smoke test before activation; failure means the skill is rejected.
- **Credential store** — secrets in `<instance>/credentials/` are off-limits to direct file reads; the agent uses `get_credential(name)` instead and never echoes the value back.
- **Plugin system** — `plugins/mcp/` (MCP servers), `plugins/{discord,telegram,imessage}/` (messaging), `plugins/{kokoro_tts,whisper_stt}/` (voice), with `plugins/messaging_gateway.py` and `plugins/voice_loop.py` as daemon orchestrators. `core/runners/thinking_runner.py` for background CoT. All opt-in via flags or env vars.
- **Git auto-commit per write** — every agent-authored `file_write` / `append_file` / `delete_file` lands as a real git commit inside the instance, giving a true authorship audit trail.

## Repo layout

```
AgenticLLM/
├── README.md                  ← you are here
├── docs/
│   ├── VOCABULARY.md          ← Tool / Skill / Plugin / Runner — read first
│   ├── PYTHON_JAEGER.md       ← per-framework deep dives
│   ├── PYTHON_PYDANTIC_AI.md
│   ├── PYTHON_HERMES_XML.md
│   ├── PYTHON_CUSTOM_JSON.md
│   ├── PYTHON_HERMES_AGENT.md
│   ├── FRAMEWORKS.md          ← side-by-side comparison
│   ├── ARCHITECTURE.md
│   ├── AGENTIC_CODING_PRACTICE.md
│   ├── SETUP.md
│   └── PROJECT.md
├── benchmark/                 ← 23-prompt head-to-head, history, dispatcher
├── models/                    ← gitignored; symlink to GGUF lives here
├── python_jaeger/             ← self-improving agent + plugin system
│   ├── __main__.py            ← `python -m python_jaeger` entry
│   ├── main.py                ← CLI dispatch + chat loop
│   ├── core/
│   │   ├── audio/             ← AEC, ReferenceBuffer, chimes
│   │   ├── runners/           ← thinking_runner, cron_runner
│   │   └── tools/             ← atomic LLM-callable functions
│   ├── plugins/
│   │   ├── kokoro_tts/        ← TTS (speak, play_async, chunked)
│   │   ├── whisper_stt/       ← STT (two_pass + continuous)
│   │   ├── mcp/, discord/, telegram/, imessage/
│   │   ├── voice_loop.py      ← daemon: STT → agent → TTS
│   │   └── messaging_gateway.py  ← daemon: multi-channel messaging
│   ├── skills/                ← framework-shipped skills (read-only zone)
│   └── instance/<name>/       ← per-instance state (agent-writable zone)
├── python_pydantic_ai/        ← Pydantic AI reference (same plugin shape as jaeger)
├── python_hermes_xml/         ← hand-rolled XML
├── python_custom_json/        ← hand-rolled JSON + GBNF
├── python_hermes_agent/       ← Nous upstream wrapped over local HTTP
├── main.py                    ← top-level dispatcher for the in-process frameworks
├── model_resolver.py          ← AGENTICLLM_MODEL_PATH → repo-local → LM Studio fallback chain
├── agent_doctor.py            ← pre-flight health check
└── requirements.txt
```

## Why five frameworks?

The goal is to surface where prompt design, output format, and agent architecture actually matter for tool-calling latency and reliability — using the **same model weights** across all five so any quality gap is purely an agent gap, not a model gap.

- **`python_jaeger`** — when you need a real shipping agent (skill versioning, instance isolation, plugin system, voice + messaging, sandbox guarantees).
- **`python_pydantic_ai`** — when speed matters and you don't need skill authoring. Same routing core as jaeger, much smaller surface.
- **`python_hermes_xml`** — reference for the Hermes function-calling format the underlying model series was trained on.
- **`python_custom_json`** — strict GBNF-grammar tool routing, useful when the model is small or untrusted and you need hard format guarantees.
- **`python_hermes_agent`** — sanity check: same Gemma weights, full Nous production framework. Any difference is pure agent-architecture, since the model is identical.

## License

MIT — see [LICENSE](LICENSE).

---

Built by [Jenkins Robotics](https://www.youtube.com/@Jenkins_Robotics).

[YouTube](https://www.youtube.com/@Jenkins_Robotics) · [Patreon](https://www.patreon.com/JenkinsRobotics) · [Discord](https://discord.gg/sAnE5pRVyT) · [GitHub](https://jenkinsrobotics.github.io)
