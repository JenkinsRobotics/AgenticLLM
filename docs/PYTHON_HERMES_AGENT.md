# python_hermes_agent

**Wraps the [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) framework so it runs against our local Gemma 4 26B-A4B over an OpenAI-compatible HTTP boundary. Same model weights as the other four frameworks, completely different agent philosophy.**

Unlike the other four frameworks in this repo (which we built ourselves), `python_hermes_agent` is a **wrapper around a production agent OS**. Hermes-agent ships with 40+ built-in tools across categories (web/terminal/file/code/vision/tts/skills/cron/messaging/computer-use), persistent skills with FTS5 session search, batch trajectory training, and seven different terminal backends. We expose our local Gemma via a llama-cpp-python OpenAI-compat server on `127.0.0.1:11435` and let hermes-agent drive it.

This framework is the **sanity check**: any difference in benchmark behavior between this and `python_pydantic_ai` is purely agent-architecture, since the model is identical.

---

## What's different from the in-process frameworks

| | Our in-process 4 | NousResearch hermes-agent |
|---|---|---|
| Scope | tool router on a fixed surface (19-33 tools) | full agent OS with 40+ tools across categories |
| Tool layout | one Python function per tool | toolset *categories* (web/terminal/file/code/vision/...) |
| Time/date | dedicated `get_time` tool | uses `terminal` to run `date` |
| Loop | our `agent.iter()` / decide→tool→finalize | hermes' multi-step agent loop with self-curation |
| Memory | flat `facts.json` + `episodic.jsonl` | persistent skills, FTS5 session search, Honcho user modeling |
| Training | none | batch trajectory + Atropos RL environments |
| Deploy | local Python process | 7 backends (local, Docker, SSH, Singularity, Modal, Daytona, Vercel Sandbox) |
| Front-ends | CLI + voice loop | CLI + Telegram/Discord/Slack/WhatsApp/Signal/Email |

---

## Architecture

```
┌───────────────────────────────┐         ┌────────────────────────────┐
│  hermes-agent CLI             │  HTTP   │  llama-cpp-python.server   │
│  (chat -Q -q "...")           ├────────►│  on http://127.0.0.1:11435 │
│  picks tools, runs them,      │  v1/    │  serving Gemma 4 26B-A4B   │
│  asks LLM how to summarize    │ chat/   │  Q4_K_M from local disk    │
└───────────────────────────────┘         └────────────────────────────┘
       │                                            ▲
       │ enabled toolsets (online: web/search/fetch │ no internet —
       │ etc.; local: terminal, files)              │ pure local Metal
       ▼
   tool results → fed back to the model → final reply
```

The local OpenAI-compat server is the same `Llama` engine our other four frameworks use, just exposed over HTTP so hermes-agent (which only speaks the OpenAI wire protocol) can drive it.

---

## Quick start

```bash
# 1. Clone hermes-agent upstream + install into our .venv + link config.
cd python_hermes_agent && ./setup.sh

# 2. Start the local LLM server (foreground; ~10s warm-up the first time).
./start_llm.sh
# leave this running

# 3. From a second terminal, send a one-shot prompt.
.venv/bin/hermes chat -Q -q "search the web for robot vacuum reviews"

# Or via our bench-friendly Python wrapper:
.venv/bin/python python_hermes_agent/run_prompt.py "tell me a one sentence story about a robot"
```

Override the model path with `HERMES_LLM_MODEL=/path/to/foo.gguf ./start_llm.sh`. The port defaults to **11435** (out of the way of LM Studio's 1234 and Ollama's 11434).

---

## Files in this directory

| File | What it does |
|---|---|
| `setup.sh` | clones upstream/, `pip install -e upstream`, symlinks `cli-config.yaml` into `~/.hermes/` |
| `start_llm.sh` | starts `python -m llama_cpp.server` with our Gemma model on `127.0.0.1:11435` |
| `cli-config.yaml` | hermes-agent config — `provider: custom`, `base_url: http://127.0.0.1:11435/v1`, `default: gemma-4-26b-a4b` |
| `run_prompt.py` | one-shot Python wrapper that returns a dict matching our `run_for_voice` shape, so this agent fits into the same comparison harness as the others |
| `upstream/` | clone of NousResearch/hermes-agent — not committed (ignored via `.gitignore`); rerun `setup.sh` to refresh |

---

## Tool surface

40+ tools across hermes-agent's toolset categories. Common ones we exercise in the bench:

| Toolset | What it covers |
|---|---|
| `web` | search (`web_search`), fetch URLs, parse pages |
| `terminal` | run shell commands (used for time, math via `bc`, file ops, etc.) |
| `files` | read/write files in hermes-agent's working dir |
| `code_execution` | run Python in a sandboxed subprocess |
| `vision` | image analysis (when a VLM is configured) |
| `tts` | text-to-speech |
| `memory` | persistent skills, session FTS5 search |
| `cron` | scheduled prompts |
| `messaging` | Discord / Telegram / Slack / WhatsApp / Signal / Email bridges |
| `computer-use` | desktop automation (mouse/keyboard) |

We can't enumerate exact tool names from our codebase — they live entirely inside `upstream/`. Bench-relevant toolsets are enabled via `cli-config.yaml`.

---

## Routing loop — black box from our perspective

We invoke hermes-agent as a subprocess (`hermes chat -Q -q <prompt>`). It does its own multi-step agent loop, tool chaining, and final-answer composition; we only see the final text on stdout.

This means:

- **No skip-final optimization** — hermes always does its own multi-step routing
- **No per-stage latency split** — we measure end-to-end wall-clock only
- **No tool-name validation in bench** — we just verify the final text isn't an obvious refusal

---

## Memory model

Hermes-agent's memory lives at `~/.hermes/` — outside this repo entirely. Includes persistent skills, FTS5 session search index, Honcho user modeling. Each invocation starts a new session unless `--session-id` is passed.

```bash
# wipe hermes-agent state
hermes uninstall
# or
rm -rf ~/.hermes
```

---

## What to expect

`hermes-agent` is a different agent philosophy than our hand-rolled routers. A small local model like Gemma 4 26B-A4B doesn't always pick the right hermes toolset for our usual prompts:

- `"what time is it"` → hermes' default behavior is "use the `terminal` tool to run `date`." A 4B-active MoE often refuses instead with "I don't have access to a clock." Compare to our frameworks where `get_time` is a typed tool the model picks reliably.
- `"search the web for X"` → hermes nails this via the `web` toolset.
- `"calculate 47 * 23 + 12"` → hermes either uses `code_execution` (Python) or `terminal` (`bc`); both work but cost an extra LLM round-trip compared to our typed `calculate` tool.

The takeaway: a bigger, broader agent surface buys generality (cron, messaging, skills, subagent delegation) but costs measurable routing accuracy when the LLM is small. The 4-way bench makes that tradeoff concrete.

---

## Running the head-to-head

Once `./start_llm.sh` is up, you can pipe the same prompts through all five agents and compare:

```bash
.venv/bin/python python_hermes_agent/run_prompt.py "tell me a one sentence story about a robot"

# vs the in-process frameworks:
.venv/bin/python -m python_jaeger          "tell me a one sentence story about a robot"
.venv/bin/python main.py python_pydantic_ai "tell me a one sentence story about a robot"
.venv/bin/python main.py python_hermes_xml  "tell me a one sentence story about a robot"
.venv/bin/python main.py python_custom_json "tell me a one sentence story about a robot"
```

Each prints the answer + a latency line. The in-process four load Gemma in-process (faster warm-up, no HTTP); hermes-agent adds a ~50–80 ms HTTP hop per LLM call but gains the full Nous toolset.

---

## Caveats

- **No `get_time` tool by default** — hermes-agent expects you to use `terminal`. If your robot needs reliable time, prefer one of our typed frameworks.
- **Memory state lives at `~/.hermes/`** — not in this repo. Wipe it with `hermes uninstall` (or `rm -rf ~/.hermes` if you want a clean slate).
- **`upstream/` is ignored by git** — the clone is ~214 MB and re-derivable from the public repo. `setup.sh` handles refresh.
- **Two-process model** — `start_llm.sh` must be running before `hermes` commands; the bench harness does NOT auto-start the server.

---

## When to use this framework

- You want the broadest possible agent surface (40+ tools, 7 messaging channels, 7 deploy backends)
- You don't need millisecond-tight routing latency (HTTP boundary + multi-step agent loop adds overhead)
- You're comparing your in-house agent against a production reference using the same model weights

For tight latency and hard format guarantees on a fixed tool surface, the in-process frameworks (`python_jaeger` / `python_pydantic_ai`) will be 2-3× faster on routing.

---

## Related docs

- [FRAMEWORKS.md](FRAMEWORKS.md) — side-by-side comparison
- [PYTHON_JAEGER.md](PYTHON_JAEGER.md) — the in-process self-improving agent (closer in scope, different philosophy)
- [Upstream hermes-agent README](https://github.com/NousResearch/hermes-agent) — full hermes-agent docs
