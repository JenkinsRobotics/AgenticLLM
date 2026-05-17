# The four agents

Four different agent implementations all driving the same local Gemma 4 26B-A4B Q4_K_M weights. Three were hand-rolled in this repo so we could pin down where prompt format, decoder constraints, and loop shape change tool-routing latency. The fourth wraps the full NousResearch [hermes-agent](https://github.com/NousResearch/hermes-agent) framework so we can compare against a real production-grade agent OS with the *exact same model* held constant.

## At a glance

| Dimension | `python_custom_json` | `python_hermes_xml` | `python_pydantic_ai` ⭐ | `python_hermes_agent` |
|---|---|---|---|---|
| Tool-call wire format | Bare JSON | Hermes XML | pydantic-ai typed tools | OpenAI function-call (HTTP) |
| Decode constraint | GBNF grammar | Unconstrained | OpenAI tool-calls + drift recovery | Whatever the LLM returns |
| Tool surface | our **19** typed tools | our **19** typed tools | our **19** typed tools (+ MCP) | hermes' **40+** built-in toolsets |
| Loop ownership | ours (`decide → tool → finalize`) | ours (multi-step `_run_collect`) | pydantic-ai's, with our `iter()` skip-final intercept | hermes-agent's |
| Skip-final-LLM | manual `fast` mode | per-step `mode=fast` | `SKIP_FINAL_TOOLS` set | n/a — hermes always summarizes |
| Memory layer | shared `memory/` (facts + episodic) | shared `memory/` | shared `memory/` | hermes' own (FTS5 sessions + Honcho) |
| MCP support | yes (dynamic via `mcp_bridge.py`) | yes (dynamic via `mcp_bridge.py`) | yes (`Tool.from_schema`, dynamic) | yes (hermes' native MCP integration) |
| Transport to LLM | in-process llama-cpp-python | in-process llama-cpp-python | in-process llama-cpp-python | HTTP → `llama_cpp.server` on port 11435 |
| Bench warm latency | ~0.5–0.7 s | ~0.5–0.7 s | **~0.3–0.5 s** (skip-final) | ~0.6–1.0 s (HTTP overhead) |
| Voice integration | — | `VOICE_FRAMEWORK=hermes_xml` | default in `voice_assistant.py` | not wired (its own gateway) |

Numbers above are warm-cache decision phase for a single-tool prompt. Bench history is in [../benchmark/BENCH_RESULTS.md](../benchmark/BENCH_RESULTS.md).

## 1. `python_custom_json/` — JSON + GBNF grammar

The "format guarantee" approach. The system prompt lists the available tools in plain text; the model is forced (via a GBNF grammar passed to llama.cpp) to emit either `{"final": "..."}` or `{"tool": "<name>", "args": {...}, "mode": "fast|natural"}`. The grammar makes malformed output impossible — but the grammar also forces specific token paths that can slow cold decode.

- **Decide phase:** grammar-constrained completion → `parse_decision()` → `ToolDecision`.
- **Finalize phase:** another LLM call only when `mode="natural"`; `mode="fast"` returns the tool result directly (this is our oldest skip-final pattern — predates the pydantic-ai work).
- **Best when:** the model is small/finicky and you need *guaranteed* parseable output.
- **Worst when:** the model is large/well-tuned and the grammar slows it down for no benefit.

## 2. `python_hermes_xml/` — Hermes function-calling XML

The format the open-source [Hermes](https://huggingface.co/NousResearch) model series was trained on. Tools are declared as JSON Schema inside `<tools>...</tools>` in the system prompt; the model emits `<tool_call>{"name": "...", "arguments": {...}}</tool_call>`; tool results come back as `<tool_response>...</tool_response>` user turns.

- **Decide phase:** unconstrained completion → `parse_decision()` parses the XML.
- **Multi-step loop:** the model can keep emitting tool calls; we detect repeated calls and end after `max_steps` or when the model emits a `<final>` payload.
- **Finalize phase:** optional `finalize()` LLM call when `mode="natural"`.
- **Best when:** the underlying model was trained on this format (Hermes 1/2/3/4). Gemma 4 handles it well too via its `<tool_call>` token.
- **Worst when:** you want type-safety on tool arguments — the model can emit any JSON; we validate at the tool boundary, not at the schema level.

## 3. `python_pydantic_ai/` ⭐ — Pydantic AI

The wrapper around [pydantic-ai](https://github.com/pydantic/pydantic-ai). We provide a custom `LlamaCppModel` adapter so pydantic-ai's tool-call machinery talks to our in-process Gemma instead of an OpenAI/Anthropic endpoint.

- **Decide + finalize:** pydantic-ai owns the loop. We expose 19 tools via `@agent.tool_plain` decorators; MCP tools are registered dynamically through `Tool.from_schema(...)`.
- **Skip-final optimization:** for tools whose result *is* the user-facing answer (`get_time`, `calculate`, `system_status`, `delete_file`, `speak`, …), we use `agent.iter()` to step through node-by-node and **break before the second `ModelRequestNode` fires**. The tool result is read directly out of `node.request.parts` and formatted — the final LLM call never happens. Saves ~280 ms per simple turn (3× faster on warm cache).
- **Type safety:** each tool's args are validated through pydantic before dispatch. Bad coords/strings/numbers raise `ModelRetry` and the model gets a structured "fix this" message.
- **Drift recovery:** Gemma sometimes emits its native `<|tool_call>call:name{...}<tool_call|>` instead of OpenAI-style `tool_calls`. `llm_model.py` salvages these via regex so we never lose a tool call to formatting drift.
- **Best when:** you want production-grade typed I/O, automatic retries, and the lowest warm-cache latency on simple commands.
- **Worst when:** you're debugging the loop itself — pydantic-ai's machinery is opaque compared to our hand-rolled frameworks.

This is the framework `voice_assistant.py` defaults to. It's also the one we recommend for the robot agent.

## 4. `python_hermes_agent/` 🆕 — NousResearch hermes-agent

Wraps the **full** NousResearch [hermes-agent](https://github.com/NousResearch/hermes-agent) framework. Where the first three are tool *routers*, this is a complete agent operating system: autonomous skill creation, FTS5 session search, Honcho dialectic user modeling, scheduled cron jobs, subagent delegation, Telegram/Discord/Slack/WhatsApp/Signal/Email gateways, 7 terminal backends (local, Docker, SSH, Singularity, Modal, Daytona, Vercel Sandbox).

We point it at our local Gemma so the LLM stays fully offline; only tool calls that need the internet (web search, fetch, etc.) leave the machine.

```
hermes CLI ─HTTP─► llama_cpp.server (port 11435) ─► Gemma 4 26B-A4B
   │
   └─► 40+ built-in tools: web search / fetch / browser automation / terminal /
       file ops / code execution / vision / TTS / skills / cron / messaging /
       computer-use / session search / memory / task planning / clarify /
       delegation / ...
```

- **Loop:** hermes-agent's own multi-turn agent loop. We don't intercept.
- **Memory:** hermes' own — persistent skills + FTS5 session search + Honcho user modeling, stored under `~/.hermes/`. Separate from our shared `memory/` directory.
- **Bench-comparable:** `python_hermes_agent/run_prompt.py` wraps `hermes chat -Q -q "..."` as a subprocess and returns the same `{text, elapsed_s, ...}` dict shape our other frameworks' `run_for_voice` returns.
- **Best when:** you want generality — cron schedules, messaging, skill learning, parallel subagents — and you can tolerate a small HTTP hop per LLM call.
- **Worst when:** you need narrow, fast, typed tool routing for a specific surface (e.g. a robot). The 40+ tool surface tends to drag down routing accuracy on a 4B-active MoE; the larger hermes prompt also eats more context.

## How they compare for the robot use case

Our north star is a robot agent that's fast, reliable, and runs locally. Ranking for that goal:

1. **`python_pydantic_ai`** — typed tool args (safety), skip-final (speed), and `voice_assistant.py` already plugs it into AEC + barge-in + memory. Recommended.
2. **`python_hermes_xml`** — same speed bracket, no type-safety on tool args, but it's also wired to `voice_assistant.py` for A/B.
3. **`python_hermes_agent`** — phenomenal *capability* surface but the HTTP boundary + bigger system prompt + broader toolset hurts routing latency on a small local model. Better suited for non-realtime "operator on the side" workflows than for a robot's main control loop.
4. **`python_custom_json`** — strict grammar is great for guarantees but the grammar slows decode. Keep as a fallback or for very small models.

## How to run each

```bash
# In-process three:
.venv/bin/python main.py python_pydantic_ai "what time is it"
.venv/bin/python main.py python_hermes_xml  "what time is it"
.venv/bin/python main.py python_custom_json "what time is it"

# hermes-agent (one-time setup, then start LLM server, then send prompts):
python_hermes_agent/setup.sh
python_hermes_agent/start_llm.sh &      # background or separate terminal
.venv/bin/python python_hermes_agent/run_prompt.py "what time is it"

# Voice loop with framework swap:
.venv/bin/python voice_assistant.py                            # → pydantic_ai
VOICE_FRAMEWORK=hermes_xml .venv/bin/python voice_assistant.py # → hermes_xml

# Bench the in-process three head-to-head:
.venv/bin/python benchmark/bench.py
```

The bench currently covers the three in-process frameworks (they share the same `benchmark/bench.py` interface). `python_hermes_agent/run_prompt.py` is the start of bench-equivalence for the fourth — the prompt-list loop is straightforward to add later if we want it in `benchmark/bench_history.jsonl`.
