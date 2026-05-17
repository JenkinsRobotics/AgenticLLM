# AgenticLLM

A fast local agentic LLM harness on macOS. **Four agents**, all running the same local Gemma 4 26B-A4B model — the first three on the same hand-rolled 19-tool surface, the fourth wrapping the full NousResearch hermes-agent framework with its 40+ built-in tools:

| Agent | Approach | Tool surface | Loop |
|---|---|---|---|
| **`python_pydantic_ai/`** ⭐ | Production [Pydantic AI](https://github.com/pydantic/pydantic-ai) with custom in-process llama-cpp-python `Model` adapter | our 19 typed tools | iter() with skip-final intercept |
| `python_hermes_xml/` | Hand-rolled Nous Function-Calling XML format | our 19 tools | `decide → tool → finalize` |
| `python_custom_json/` | Hand-rolled JSON + GBNF-grammar-constrained decode | our 19 tools | `decide → tool → finalize` |
| **`python_hermes_agent/`** 🆕 | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) wired to a local llama-cpp-python OpenAI-compat server | hermes' **40+ tools** (web/terminal/file/code/vision/tts/skills/cron/messaging/computer-use…) | hermes' self-improving agent loop |

The first three load the model in-process and answer to a strict per-prompt latency budget (warm-cache routing in 0.3–0.5 s). The fourth runs the model behind an HTTP boundary so a much larger, self-improving agent system can drive it — same offline LLM, very different agent philosophy.

See [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md) for a side-by-side breakdown, [benchmark/BENCHMARK.md](benchmark/BENCHMARK.md) for the live 3-way latency table (auto-updated for the in-process trio), and [benchmark/BENCHMARK_4WAY.md](benchmark/BENCHMARK_4WAY.md) for the curated 5-prompt run that includes `python_hermes_agent` head-to-head.

**Why each one is useful:**
- **`python_pydantic_ai`** is our recommendation for the robot agent: type-safe tool arguments (bad coords get rejected before they hit motors), automatic `ModelRetry` on bad output, and the skip-final optimization makes simple commands 3× faster than the others. This is what `voice_assistant.py` defaults to.
- **`python_hermes_xml`** is the hand-rolled reference for the Hermes function-calling format that the underlying Hermes model series was trained on. Also wired as a swap-in for `voice_assistant.py` (`VOICE_FRAMEWORK=hermes_xml`).
- **`python_custom_json`** demonstrates strict grammar-constrained tool routing — useful when the model is small or untrusted and you need format guarantees.
- **`python_hermes_agent`** is the full Nous framework — lets us compare against a real agent OS (skills, cron, messaging gateway, subagent delegation) using the *same* local Gemma weights, so any quality gap is purely an agent-architecture gap, not a model gap.

The goal is to maximize fast local realtime agentic performance and surface where prompt design + output format + agent architecture actually matter for tool-calling latency and reliability.

## What's in the box (the three in-process frameworks)

| | `python_custom_json/` | `python_hermes_xml/` | `python_pydantic_ai/` |
|---|---|---|---|
| Tool-call format | Bare JSON: `{"tool":"x","args":{...}}` | XML: `<tool_call>{"name":"x","arguments":{...}}</tool_call>` | pydantic-ai's typed `Tool` decorators |
| Tool declarations | Plain-text list in system prompt | JSON Schema in `<tools>` block | inferred from function signatures + docstrings |
| Decoding | GBNF grammar-constrained | Unconstrained | OpenAI-style tool-calls, with drift recovery |
| Tool result round-trip | Appended user turn: `Tool result: ...` | `<tool_response>{...}</tool_response>` turn | structured `ToolReturnPart` |
| Skip-final-LLM | manual `fast` mode | `decision.mode=fast` | `SKIP_FINAL_TOOLS` set, intercept via `agent.iter()` |
| Strength | Hard format guarantee; cheaper cold start | Faster warm decode; cleaner free-text | Type-safe args; auto-retry; fastest warm-cache |

All three share the same model, the same tool implementations, the same `LlamaCppPythonClient` plumbing, and the same latency reporting format. The differences live in `prompts.py`, `tool_router.py`, the `decide` / `finalize` shapes, and (for pydantic_ai) the `agent.iter()` skip-final intercept.

The fourth framework (`python_hermes_agent/`) is its own self-contained world — see [its README](python_hermes_agent/README.md) for setup and design.

## Setup

### Requirements

- macOS on Apple Silicon (tested on M-series with Metal)
- Python 3.10–3.12
- ~16 GB free RAM for Gemma 4 26B-A4B at Q4_K_M (~15.6 GB resident)
- Microphone / speaker not needed unless you use the `speak` / `speak_file` tools

### Install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The heavy deps (`torch`, `kokoro`, `llama-cpp-python`) take a while to install on a fresh venv. `llama-cpp-python` builds against Metal automatically on Apple Silicon.

### Download the model

Both frameworks default to:

```
~/.lmstudio/models/lmstudio-community/gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf
```

The easiest way to get it is [LM Studio](https://lmstudio.ai/) — search for `gemma-4-26B-A4B-it-GGUF`, pick the `Q4_K_M` quant. If you store the file elsewhere, pass `--model-path /your/path.gguf` to either runner.

### Verify install (no model needed)

The safe-tool self-test runs the parser + every tool against canned inputs without loading the LLM:

```bash
.venv/bin/python main.py python_custom_json --self-test
.venv/bin/python main.py python_hermes_xml   --self-test
.venv/bin/python main.py python_pydantic_ai  --self-test
```

If they all print a series of tool-result lines without errors, the install is healthy.

## Running

### Interactive chat

```bash
.venv/bin/python main.py python_pydantic_ai    # ⭐ recommended (fastest, type-safe)
.venv/bin/python main.py python_hermes_xml     # hand-rolled XML framework
.venv/bin/python main.py python_custom_json    # hand-rolled JSON+grammar framework
```

You'll see a `You:` prompt. Type anything; `exit`, `quit`, or Ctrl-C to leave. After each reply you'll see a latency report:

```
Latency:
- decision: 0.430s  (ttft 0.135s)
- tool: 0.001s
- final: 0.481s  (ttft 0.140s)
- total: 0.912s
```

`ttft` = time-to-first-token. `decision` is the routing call; `final` is the optional follow-up rewrite of the tool result into natural language (skipped for `fast`-mode tools).

### One-shot mode

```bash
.venv/bin/python main.py python_custom_json "what time is it"
.venv/bin/python main.py python_hermes_xml "search the web for robot vacuum reviews"
```

Useful for scripting or running a fixed prompt without the interactive loop.

### Head-to-head benchmark

```bash
.venv/bin/python benchmark/bench.py                       # default mode
.venv/bin/python benchmark/bench.py --with-mcp            # adds opt-in MCP prompts
.venv/bin/python benchmark/bench.py --think               # adds background thinking
.venv/bin/python benchmark/bench.py --only python_custom_json       # one framework only
.venv/bin/python benchmark/bench.py --prompts file.txt    # custom prompt list
.venv/bin/python benchmark/bench.py --skip-run            # re-summarize existing logs
.venv/bin/python benchmark/bench.py --history             # trend view across runs
```

Each run gets a `mode_tag` (`default` / `mcp` / `think` / `mcp+think`) in `benchmark/bench_history.jsonl` so trends compare cleanly. Two default prompts play audio (`read bench.txt`, `narrate youtube_intro.txt`); pass a smaller prompt list to skip TTS.

Two prompts in the default set play audio out loud (`read bench.txt out loud`, `narrate youtube_intro.txt`). Skip them by passing a smaller prompt list if you don't want TTS during benchmarking.

## Run the robot

Once `pip install -r requirements.txt` succeeds and `agent_doctor.py` is green, you have four ways to talk to the same agent:

```bash
# 1. Headless CLI — type to it
.venv/bin/python main.py python_pydantic_ai

# 2. Voice — wake word "hey jaeger", full-duplex AEC, barge-in supported
.venv/bin/python voice_assistant.py
# (or, restart-on-crash for unattended:)
.venv/bin/python supervisor.py -- .venv/bin/python voice_assistant.py

# 3. Messaging — bidirectional Discord / Telegram / iMessage daemon
export DISCORD_BOT_TOKEN='...'                          # https://discord.com/developers/applications
export DISCORD_ALLOWED_USER_IDS='123,456'               # comma-separated user IDs
export TELEGRAM_BOT_TOKEN='...'                         # talk to @BotFather on Telegram
export TELEGRAM_ALLOWED_CHAT_IDS='789,234'              # comma-separated chat IDs
export IMESSAGE_ALLOWED_HANDLES='+15551234567,you@me.com'  # macOS, needs Full Disk Access
.venv/bin/python -m messaging.gateway

# 4. Schedule it — agent calls schedule_prompt; CronRunner fires unattended
#    (started automatically inside voice_assistant.py and messaging.gateway)
```

Every surface shares the same memory, the same skills, and the same in-process Gemma. The `CronRunner` claims due schedules atomically via fcntl flock so two channels can't double-fire.

**Outbound from the agent:** all bridges that successfully start register in a shared registry. The `send_message(channel, recipient, text)` tool lets the agent — or a scheduled prompt — push a message to any live channel without being prompted first. Example: `schedule_prompt("0 7 * * *", "send the weather for Indianapolis to telegram chat 234567")` → every 7 AM the cron runner fires that prompt → agent looks up weather → calls `send_message("telegram", "234567", "...")` → done.

## Tools (28 in `python_pydantic_ai`, 19 in the other two)

File ops are confined to each framework's own `workspace/` — even if you ask the model to "save to Desktop," it lands in the workspace and the reply tells you where it actually went. Memory lives in a shared `memory/` directory at the project root so every interface (chat, voice, Discord, iMessage) sees the same identity and facts.

| Category | Tools | Notes |
|---|---|---|
| **Time / math / state** | `get_time`, `calculate`, `system_status` | skip-final → tool result IS the answer |
| **Workspace files** | `create_file`, `append_file`, `delete_file`, `read_file`, `list_directory` | sandboxed; `delete_file` gates on `confirm=True` when `DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1` |
| **Speech** | `speak`, `speak_file` | Kokoro TTS, fully offline |
| **Web** | `web_search`, `get_weather` | DuckDuckGo + wttr.in; no API key |
| **Host control** | `launch_url`, `open_file`, `open_app` | macOS only |
| **Memory (k/v + log)** | `remember`, `recall`, `list_facts`, `forget` | shared `memory/facts.json`; `forget` is approval-gated |
| **Memory (semantic)** ⭐ | `search_memory(query, k)` | sentence-transformers index over `memory/episodic.jsonl` |
| **Code execution** ⭐ | `run_python(code, timeout_s)` | sandboxed subprocess, 10 s timeout, tempdir |
| **Vision** ⭐ | `look_at(image_path, question)` | lazy Moondream2 VLM, CPU |
| **Image gen** ⭐ | `generate_image(prompt, out_path, …)` | lazy SDXL-Turbo, MPS |
| **Clarify** ⭐ | `ask_user(question)` | voice loop speaks it, next phrase is the answer |
| **Scheduling** ⭐ | `schedule_prompt(cron, prompt, name)`, `list_schedules`, `cancel_schedule` | fired by `CronRunner` inside `voice_assistant.py` or `messaging.gateway` |
| **Delegation** ⭐ | `delegate(subtask)` | spawns a fresh sub-agent, depth-limited |

⭐ added in Sprint 1–3. The first three frameworks share the 19 core tools; the ⭐ tools are `python_pydantic_ai`-only.

### Skip-final optimization

Tools whose dict result *is* the user-facing answer are listed in `SKIP_FINAL_TOOLS` (in [python_pydantic_ai/main.py](python_pydantic_ai/main.py)). When the agent picks one of these AND it's the only tool call in the turn, we intercept after the tool returns and **skip the would-be "final-answer" LLM call** — saves ~280 ms per simple command (3× faster on calc/time/etc.).

## Project structure

```
AgenticLLM/
├── main.py             # Dispatcher: python main.py [python_custom_json|python_hermes_xml] [prompt]
├── benchmark/          # All bench scripts + history + result docs (see benchmark/BENCHMARKING.md)
│   ├── bench.py          # Head-to-head 3-way bench + comparison table
│   ├── bench_all.py      # 4-way side-by-side (5 curated prompts; includes hermes_agent)
│   ├── bench_jaeger.py   # python_jaeger vs python_pydantic_ai parity check
│   ├── bench_history.jsonl  # append-only per-run history
│   ├── BENCHMARK.md      # auto-generated 3-way table
│   ├── BENCHMARK_4WAY.md # auto-generated 4-way table
│   ├── BENCH_RESULTS.md  # historical + per-mode breakdown
│   └── BENCHMARKING.md   # how to run benchmarks and read history
├── requirements.txt
├── python_custom_json/ # OUR JSON + GBNF grammar framework (was "pygentic/")
│   ├── main.py          # decide / finalize / CLI loop
│   ├── prompts.py       # Unified system prompt (shared decide+finalize)
│   ├── tool_router.py   # SAFE_TOOLS, GBNF grammar, parser
│   ├── tools.py         # Tool implementations
│   ├── llm_client.py    # llama-cpp-python + server clients
│   ├── logs/            # latency.jsonl (append-only history)
│   └── workspace/       # Sandboxed file ops
├── python_hermes_xml/  # OUR Nous Function-Calling XML format framework (was "hermes/")
├── python_pydantic_ai/ # Pydantic AI wrapper with custom LlamaCppModel adapter
│   ├── main.py          # build_agent / run_command / run_for_voice / iter() skip-final
│   ├── llm_model.py     # LlamaCppModel — in-process Gemma as a pydantic-ai Model
│   ├── tools.py         # Same 19 tools (shared semantics with the other two)
│   ├── prompts.py       # System prompt
│   └── workspace/, logs/
├── python_hermes_agent/ # NousResearch hermes-agent wired to local Gemma over HTTP
│   ├── setup.sh         # clones upstream/, pip-installs, links cli-config.yaml
│   ├── start_llm.sh     # serves Gemma via llama_cpp.server on :11435
│   ├── cli-config.yaml  # hermes config: provider=custom, base_url=local
│   ├── run_prompt.py    # one-shot wrapper that mirrors our run_for_voice shape
│   ├── README.md        # demo quickstart
│   └── upstream/        # the cloned framework (gitignored — re-derived by setup.sh)
├── voice_assistant.py  # AEC + barge-in voice loop; framework swappable via VOICE_FRAMEWORK
├── agent_doctor.py     # Pre-flight health check (14 checks; exits non-zero on FAIL)
├── supervisor.py       # Restart-on-crash wrapper with exponential backoff
├── voice_validation.py # 14-check end-to-end contract test for the voice loop
├── messaging/          # Remote messaging gateways (shared agent across channels)
│   ├── gateway.py       # Daemon: loads agent once + starts every configured adapter
│   ├── discord_bridge.py # DM + @mention adapter (DISCORD_BOT_TOKEN)
│   └── imessage_bridge.py # chat.db poll + AppleScript send (IMESSAGE_ALLOWED_HANDLES)
├── memory/             # Unified memory — shared across all interfaces
│   ├── identity.md      # Stable persona, prepended to every system prompt
│   ├── facts.json       # Atomic key/value (schema_version=1, fcntl-locked)
│   ├── episodic.jsonl   # Append-only cross-session turn log
│   ├── schedules.jsonl  # Append-only cron schedule log
│   ├── memory_module.py # Read/write helpers + semantic search index
│   ├── cron_runner.py   # Background thread that fires due schedules
│   └── maintenance.py   # `python -m memory.maintenance --all` for log/episodic rotation
├── mcp_bridge.py       # Opt-in MCP client (--with-mcp)
├── mcp_config.json     # MCP servers to connect to when MCP is enabled
│   # Each in-process framework also owns its own thinking_runner.py +
│   # thinking.jsonl (opt-in --think extension), mcp_bridge.py + mcp_config.json
│   # (opt-in --with-mcp), and memory/ store.
└── docs/               # FRAMEWORKS.md, ARCHITECTURE.md, AGENTIC_CODING_PRACTICE.md, SETUP.md, TODO.md
```

## Production checklist (the shipping posture)

| concern | mechanism | env var / command |
|---|---|---|
| Pre-flight health check | 14 checks: model file, deps, memory, audio, … | `python agent_doctor.py` (exits 0/1) |
| Crash recovery | exponential backoff + per-crash log | `python supervisor.py -- python voice_assistant.py` |
| Approval gate on destructive ops | `delete_file` / `forget` preview unless `confirm=True` | `DESTRUCTIVE_OPS_REQUIRE_CONFIRM=1` (auto-set by voice/gateway) |
| Memory schema version + cross-process flock | `facts.json`, `schedules.jsonl` use fcntl LOCK_EX | automatic |
| Log rotation + episodic archive | rotate `>10 MB`, move old turns to `memory/archive/` | `python -m memory.maintenance --all` |
| Cold-cache prewarm | one trivial turn at load time | automatic (`prewarm()` in load path) |
| Cron scheduling (single-claim) | `claim_due_schedules` uses file lock | started by `voice_assistant.py` or `messaging.gateway` |
| Contract test for new tools | exercises every tool through `run_for_voice` | `python voice_validation.py` |

## Performance notes

A few non-obvious findings from running both frameworks side-by-side on Gemma 4 26B-A4B Q4_K_M:

- **Hermes wins on warm prompts, Pygentic wins on cold start.** Pygentic's lighter system prompt (~25 lines) prefills faster than Hermes's heavier JSON-Schema block (~150 lines) on the very first call. After that, llama.cpp's prefix cache equalizes the prefill cost and Hermes's unconstrained decode pulls ahead.
- **Use one system prompt across decide+finalize.** If `finalize` uses a different system prompt than `decide`, every finalize call clobbers the KV cache and the *next* decide pays cold prefill (~+0.3s TTFT). Pygentic's `SYSTEM_PROMPT` is intentionally written to cover both turns.
- **Cache the compiled GBNF grammar.** `LlamaGrammar.from_string()` adds 50-200ms per call if you let it recompile. `LlamaCppPythonClient._compile_grammar` caches by grammar string.
- **JSON-wrapping free-text answers is expensive.** Forcing every final answer through `{"final":"..."}` triples generation time for jokes/stories/titles vs plain text. Pygentic v2 could close this gap with a hybrid grammar that allows either a constrained tool-call block or unconstrained free text.
- **TTS audio dominates wall-clock on narration prompts.** `speak_file` on a 4-sentence paragraph takes ~28s regardless of framework — that's the audio playback length, not LLM work.

The latency reports in `latency.jsonl` carry TTFT + total time per stage so you can re-analyze any past run with `bench.py --skip-run` or your own scripts. Each bench run also appends an aggregate to `benchmark/bench_history.jsonl` — see [benchmark/BENCHMARKING.md](benchmark/BENCHMARKING.md) for how to read trends with `python benchmark/bench.py --history`.

## Docs

- [docs/FRAMEWORKS.md](docs/FRAMEWORKS.md) — full side-by-side of all four agents, when to use which
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design, request pipeline, framework differences
- [benchmark/BENCHMARKING.md](benchmark/BENCHMARKING.md) — running benchmarks, reading history, regression detection
- [benchmark/BENCH_RESULTS.md](benchmark/BENCH_RESULTS.md) — latest numbers per mode + historical consistency view
- [docs/PROJECT.md](docs/PROJECT.md) — high-level project overview
- [docs/SETUP.md](docs/SETUP.md) — install and verification
- [docs/TODO.md](docs/TODO.md) — open work
- [python_hermes_agent/README.md](python_hermes_agent/README.md) — NousResearch hermes-agent demo: install, local-LLM wiring, comparison framing

## License

MIT — see [LICENSE](LICENSE).

---

Built by [Jenkins Robotics](https://www.youtube.com/@Jenkins_Robotics).

[YouTube](https://www.youtube.com/@Jenkins_Robotics) · [Patreon](https://www.patreon.com/JenkinsRobotics) · [Discord](https://discord.gg/sAnE5pRVyT) · [GitHub](https://jenkinsrobotics.github.io)
