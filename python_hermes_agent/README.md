# python_hermes_agent — NousResearch hermes-agent against our local Gemma

Wraps the real [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) framework so it runs **fully offline for inference** (local Gemma 4 26B-A4B via llama-cpp-python's OpenAI-compatible server) while still letting the agent use online tools (web search, fetch, etc.) — same posture the other three frameworks in this repo take.

This is **the fourth agent we can A/B compare** against `python_custom_json`, `python_hermes_xml`, and `python_pydantic_ai`. Unlike the three we built ourselves, hermes-agent is a full self-improving agent framework: it has 40+ tools, persistent skills, session search, and its own learning loop. Same model, very different agent philosophy.

## What's different from our other three frameworks

|  | Our 3 frameworks | NousResearch hermes-agent |
|---|---|---|
| Scope | narrow tool router on a fixed 19-tool surface | full agent OS with 40+ tools across categories |
| Tool layout | one Python function per tool | toolset *categories* (web/terminal/file/code/vision/tts/memory/skills/cron/messaging/computer-use) |
| Time/date | dedicated `get_time` tool | uses `terminal` to run `date` |
| Loop control | our `decide → tool → finalize` | hermes' own multi-step agent loop with self-curation |
| Memory | flat `memory/facts.json` + `episodic.jsonl` | persistent skills, FTS5 session search, Honcho user modeling |
| Training | none | batch trajectory + Atropos RL environments |
| Deploy | local process | 7 terminal backends (local, Docker, SSH, Singularity, Modal, Daytona, Vercel Sandbox) |
| Front-ends | CLI + voice loop | CLI + Telegram/Discord/Slack/WhatsApp/Signal/Email |

## Architecture of this demo

```
┌───────────────────────────────┐         ┌────────────────────────────┐
│  hermes-agent CLI             │  HTTP   │  llama-cpp-python.server   │
│  (chat -Q -q "...")           ├────────►│  on http://127.0.0.1:11435 │
│  picks tools, runs them,      │  v1/    │  serving Gemma 4 26B-A4B   │
│  asks LLM how to summarize    │ chat/   │  Q4_K_M from local disk    │
└───────────────────────────────┘         └────────────────────────────┘
       │                                            ▲
       │ enabled toolsets (online: web search,      │ no internet —
       │ fetch, etc.; local: terminal, files)       │ pure local Metal
       ▼
   tool results → fed back to the model → final reply
```

The local OpenAI-compatible server is the same `Llama` engine our other three frameworks use, just exposed over HTTP so hermes-agent (which only speaks the OpenAI wire protocol) can drive it.

## Quick start

```bash
# 1. Clone hermes-agent upstream + install into our .venv + link config.
./setup.sh

# 2. Start the local LLM server (foreground; ~10s warm-up the first time).
./start_llm.sh
# leave this running

# 3. From a second terminal, send a one-shot prompt.
.venv/bin/hermes chat -Q -q "search the web for robot vacuum reviews"

# Or via our bench-friendly Python wrapper:
.venv/bin/python python_hermes_agent/run_prompt.py "tell me a one sentence story about a robot"
```

Override the model path with `HERMES_LLM_MODEL=/path/to/foo.gguf ./start_llm.sh`. The port defaults to **11435** (off the way of LM Studio's 1234 and Ollama's 11434).

## Files in this directory

| File | What it does |
|---|---|
| `setup.sh` | clones upstream/, `pip install -e upstream`, symlinks `cli-config.yaml` into `~/.hermes/` |
| `start_llm.sh` | starts `python -m llama_cpp.server` with our Gemma model on `127.0.0.1:11435` |
| `cli-config.yaml` | hermes-agent config — `provider: custom`, `base_url: http://127.0.0.1:11435/v1`, `default: gemma-4-26b-a4b` |
| `run_prompt.py` | one-shot Python wrapper that returns a dict matching our `run_for_voice` shape, so this agent fits into the same comparison harness as the other three |
| `upstream/` | clone of NousResearch/hermes-agent — not committed (ignored via `.gitignore`); rerun `setup.sh` to refresh |

## What to expect

`hermes-agent` is a different agent philosophy than our hand-rolled routers. A small local model like Gemma 4 26B-A4B doesn't always pick the right hermes toolset for our usual prompts:

- `"what time is it"` → hermes' default behavior is "use the `terminal` tool to run `date`." A 4B-active MoE often refuses instead with "I don't have access to a clock." Compare to our frameworks where `get_time` is a typed tool the model picks reliably.
- `"search the web for X"` → hermes nails this via the `web` toolset.
- `"calculate 47 * 23 + 12"` → hermes either uses `code_execution` (Python) or `terminal` (`bc`); both work but cost an extra LLM round-trip compared to our typed `calculate` tool.

The takeaway: bigger, broader agent surface buys you generality (cron, messaging, skills, subagent delegation) but costs a measurable amount of routing accuracy when the LLM is small. Our 4-way bench is meant to make that tradeoff concrete.

## Running the head-to-head

Once `./start_llm.sh` is up, you can pipe the same prompts through all four agents and compare:

```bash
.venv/bin/python python_hermes_agent/run_prompt.py "tell me a one sentence story about a robot"

# vs the in-process frameworks:
.venv/bin/python main.py python_pydantic_ai "tell me a one sentence story about a robot"
.venv/bin/python main.py python_hermes_xml "tell me a one sentence story about a robot"
.venv/bin/python main.py python_custom_json "tell me a one sentence story about a robot"
```

Each prints the answer + a latency line. The in-process three load Gemma in-process (faster warm-up, no HTTP); hermes-agent adds a ~50–80 ms HTTP hop per LLM call but gains the full Nous toolset.

## Caveats

- **No `get_time` tool by default** — hermes-agent expects you to use `terminal`. If your robot needs reliable time, prefer one of our typed frameworks.
- **Memory state lives at `~/.hermes/`** — not in this repo. Wipe it with `hermes uninstall` (or `rm -rf ~/.hermes` if you want a clean slate).
- **httpx 0.28 + `mcp-server-fetch`** — the project-wide patch we applied earlier in `python_pydantic_ai` covers this; no separate fix needed here.
- **`upstream/` is ignored by git** — the clone is ~214 MB and re-derivable from the public repo. `setup.sh` handles refresh.
