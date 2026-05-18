# The five agents

Five different agent implementations all driving the same local Gemma 4 26B-A4B Q4_K_M weights. Four are hand-rolled in this repo (so we can pin down where prompt format, decoder constraints, and loop shape change tool-routing latency); the fifth wraps the full NousResearch [hermes-agent](https://github.com/NousResearch/hermes-agent) framework so we can compare against a real production-grade agent OS with the *exact same model* held constant.

Each has its own deep-dive doc:
- **[python_jaeger](PYTHON_JAEGER.md)** ⭐⭐ — production self-improving agent (skills, plugins, instance isolation)
- **[python_pydantic_ai](PYTHON_PYDANTIC_AI.md)** ⭐ — lean Pydantic AI reference (routing speed leader)
- **[python_hermes_xml](PYTHON_HERMES_XML.md)** — hand-rolled XML format
- **[python_custom_json](PYTHON_CUSTOM_JSON.md)** — hand-rolled JSON + GBNF grammar
- **[python_hermes_agent](PYTHON_HERMES_AGENT.md)** — Nous upstream wrapped over local HTTP

---

## At a glance

| Dimension | `python_jaeger` ⭐⭐ | `python_pydantic_ai` ⭐ | `python_hermes_xml` | `python_custom_json` | `python_hermes_agent` |
|---|---|---|---|---|---|
| Tool-call wire format | pydantic-ai typed | pydantic-ai typed | Hermes XML | bare JSON | OpenAI function-call (HTTP) |
| Decode constraint | none + drift recovery | none + drift recovery | none | GBNF grammar | whatever the model returns |
| Tool surface | 33 core + versioned skills + MCP | 30 typed + MCP | 19 typed + MCP | 19 typed + MCP | hermes' 40+ |
| Loop ownership | ours (`agent.iter()` + skip-final) | ours (`agent.iter()` + skip-final) | ours (`decide → tool → finalize`) | ours (`decide → tool → finalize`) | hermes-agent's |
| Skip-final-LLM | yes (24 tools) | yes (17 tools) | per-step `mode=fast` | manual `fast` mode | n/a |
| Sandbox | per-instance `<instance>/skills/` | per-framework `workspace/` | per-framework `workspace/` | per-framework `workspace/` | hermes' working dir |
| Memory backend | per-instance + episodic | per-framework + episodic | per-framework + episodic | per-framework + episodic | hermes' own (FTS5 + Honcho) |
| Multi-instance isolation | yes (lockfile, manifest) | no | no | no | no |
| Skill versioning + smoke tests | **yes** | no | no | no | no (hermes has its own skills) |
| Credential isolation | **yes** (`get_credential`) | no | no | no | no |
| Git auto-commit per write | **yes** | no | no | no | no |
| MCP support | yes (plugin) | yes (plugin) | yes (plugin) | yes (plugin) | yes (hermes native) |
| Background CoT | yes (`--think`) | yes (`--think`) | yes (`--think`) | yes (`--think`) | n/a |
| Messaging gateway | yes (Discord/TG/iMsg) | yes (Discord/TG/iMsg) | no | no | hermes own (Discord/TG/Slack/WhatsApp/Signal/Email) |
| Voice loop (mic → agent → speaker) | **yes** (`--voice`, two STT modes, optional AEC barge-in, chimes) | **yes** (same flag surface) | no | no | not wired |
| Instance management CLI | **yes** (`--list/create/clear/delete-instance`) | n/a (single workspace) | n/a | n/a | hermes' own |
| Transport to LLM | in-process llama-cpp | in-process llama-cpp | in-process llama-cpp | in-process llama-cpp | HTTP → `llama_cpp.server:11435` |
| Bench score (23 prompts) | **23/23** | **23/23** | **23/23** | **23/23** | not in bench |
| Warm latency budget | ~0.3–0.5 s | ~0.3–0.5 s | ~0.5–0.7 s | ~0.5–0.7 s | ~0.6–1.0 s (HTTP overhead) |

Latency numbers are warm-cache decision phase for a single-tool prompt. Bench history in [../benchmark/BENCH_RESULTS.md](../benchmark/BENCH_RESULTS.md).

---

## 1. `python_jaeger` ⭐⭐ — self-improving agent

**The flagship.** Production-grade agent that builds on `python_pydantic_ai`'s routing core and adds the guarantees you need to actually deploy: multi-instance isolation (lockfile + manifest + migration runner), versioned skill authoring (`<instance>/skills/<name>_v<N>/` with mandatory `SKILL.md` + `tests/smoke_test.py`), credential store (off-limits to direct file reads, only `get_credential(name)`), git auto-commit per agent-authored write, and a plugin system for MCP / messaging / background thinking.

- **Loop:** pydantic-ai's `agent.iter()` with skip-final intercept on 24 tools.
- **Sandbox:** per-instance — `<instance>/skills/` is the only writable area.
- **Memory:** per-instance, gated behind `--with-memory` (auto-on in interactive chat).
- **Plugins:** `plugins/{mcp,discord,telegram,imessage}/` (each with `plugin.yaml` + smoke test). Background CoT lives in `core/runners/thinking_runner.py` — it's a Runner, not a Plugin. See [VOCABULARY.md](VOCABULARY.md).
- **Best when:** you need a real shipping agent that can author its own skills, manages secrets safely, and gives you a real audit trail.
- **Worst when:** you only need routing — the instance / manifest / skill-loader overhead is dead weight for one-shot routing benchmarks.

**Full writeup:** [PYTHON_JAEGER.md](PYTHON_JAEGER.md)

---

## 2. `python_pydantic_ai` ⭐ — routing speed leader

The lean Pydantic AI reference. Same `agent.iter()` skip-final core as jaeger, without the instance/skills/credentials overhead. Custom `LlamaCppModel` adapter so pydantic-ai's tool-call machinery talks to our in-process Gemma instead of an OpenAI/Anthropic endpoint.

- **Loop:** `agent.iter()` with skip-final intercept on 17 tools (~280 ms saved per simple turn).
- **Sandbox:** `python_pydantic_ai/workspace/`.
- **Memory:** `python_pydantic_ai/memory/`, gated by `--with-memory`.
- **Plugins:** same shape as jaeger's (MCP, thinking, messaging).
- **Best when:** you want production-grade typed I/O, automatic retries, and the lowest warm-cache latency on simple commands.
- **Worst when:** you need skill authoring or multi-tenant isolation — that's what jaeger adds on top.

**Full writeup:** [PYTHON_PYDANTIC_AI.md](PYTHON_PYDANTIC_AI.md)

---

## 3. `python_hermes_xml` — Hermes function-calling XML

The format the open-source [Hermes](https://huggingface.co/NousResearch) model series was trained on. Tools are declared as JSON Schema inside `<tools>...</tools>` in the system prompt; the model emits `<tool_call>{"name": "...", "arguments": {...}}</tool_call>`; tool results come back as `<tool_response>...</tool_response>` user turns.

- **Loop:** three-phase decide → tool → finalize. Unconstrained decoding (no grammar).
- **Drift recovery:** XML parser handles `<function_call>` variants, missing closing tags, etc.
- **Best when:** the underlying model was trained on this format. Unconstrained decoding is ~10-20% faster than grammar-constrained per token.
- **Worst when:** you need hard format guarantees — Gemma can emit malformed XML and the recovery is statistical, not hard.

**Full writeup:** [PYTHON_HERMES_XML.md](PYTHON_HERMES_XML.md)

---

## 4. `python_custom_json` — JSON + GBNF grammar

The format-safety reference. The model is forced (via a GBNF grammar at decode time) to emit either `{"tool": "<name>", "args": {...}}` or `{"final": "<answer>"}`. Malformed output is impossible by construction.

- **Loop:** same three-phase decide → tool → finalize as `python_hermes_xml`.
- **Grammar:** compiled once per tool list, cached by string identity.
- **Best when:** the model is small (≤4B), untrusted, or you need a hard parse-safety guarantee.
- **Worst when:** the model is large and well-tuned — grammar costs ~10-20% per token for a guarantee you don't need.

**Full writeup:** [PYTHON_CUSTOM_JSON.md](PYTHON_CUSTOM_JSON.md)

---

## 5. `python_hermes_agent` — full Nous framework

Wraps the **complete** NousResearch hermes-agent OS. Where the first four are tool routers, this is a full agent system: autonomous skill creation, FTS5 session search, Honcho user modeling, scheduled cron, subagent delegation, six messaging channels (Telegram/Discord/Slack/WhatsApp/Signal/Email), seven deploy backends (local/Docker/SSH/Singularity/Modal/Daytona/Vercel-Sandbox).

We point it at our local Gemma over an OpenAI-compat HTTP server so the LLM stays fully offline; only tool calls that need the internet (web/search/fetch) leave the machine.

- **Loop:** hermes-agent's own multi-turn agent loop. We don't intercept.
- **Memory:** hermes' own at `~/.hermes/` — separate from anything in this repo.
- **Best when:** you want generality (cron, messaging, skill learning) and can tolerate the HTTP hop.
- **Worst when:** you need narrow, fast, typed tool routing for a specific surface — the 40+ tool surface tends to drag down routing accuracy on a 4B-active MoE.

**Full writeup:** [PYTHON_HERMES_AGENT.md](PYTHON_HERMES_AGENT.md)

---

## How they compare for the robot use case

The north star is a robot agent that's fast, reliable, and runs locally.

1. **`python_jaeger`** — when the robot needs persistent skills, per-deployment isolation, credential storage, and a real audit trail. Routes at the same speed as `python_pydantic_ai` since both share the `agent.iter()` skip-final core.
2. **`python_pydantic_ai`** — when you don't need skill authoring; lighter setup, same warm-cache speed.
3. **`python_hermes_xml`** — same speed bracket as pydantic_ai when the model handles the format well; lacks type-safety on tool args.
4. **`python_custom_json`** — strict grammar is great for guarantees but slows decode; best as fallback for very small or untrusted models.
5. **`python_hermes_agent`** — phenomenal capability surface but the HTTP boundary + bigger prompt + broader toolset hurts routing latency on a 4B-active MoE. Better suited for non-realtime "operator on the side" workflows than for a robot's main control loop.

---

## How to run each

```bash
# Jaeger (recommended — instance-based, skill-versioned, plugins on tap):
python -m python_jaeger                           # interactive chat (auto --with-memory)
python -m python_jaeger "what time is it"         # one-shot
python -m python_jaeger --with-mcp --think        # full extensions

# The other in-process three (via the main.py dispatcher):
python main.py python_pydantic_ai "what time is it"
python main.py python_hermes_xml  "what time is it"
python main.py python_custom_json "what time is it"

# Hermes-agent (one-time setup, then start LLM server, then send prompts):
cd python_hermes_agent
./setup.sh
./start_llm.sh &           # background or separate terminal
python run_prompt.py "what time is it"

# Bench all four in-process frameworks (one process per framework for clean Metal):
python benchmark/bench.py --only python_jaeger --with-jaeger
python benchmark/bench.py --only python_pydantic_ai
python benchmark/bench.py --only python_hermes_xml
python benchmark/bench.py --only python_custom_json
```

The bench covers the four in-process frameworks via `benchmark/bench.py`. `python_hermes_agent/run_prompt.py` is the start of bench-equivalence for the fifth — wiring it into `benchmark/bench_history.jsonl` is a follow-up.

---

## Related docs

- [PYTHON_JAEGER.md](PYTHON_JAEGER.md), [PYTHON_PYDANTIC_AI.md](PYTHON_PYDANTIC_AI.md), [PYTHON_HERMES_XML.md](PYTHON_HERMES_XML.md), [PYTHON_CUSTOM_JSON.md](PYTHON_CUSTOM_JSON.md), [PYTHON_HERMES_AGENT.md](PYTHON_HERMES_AGENT.md) — per-framework deep dives
- [ARCHITECTURE.md](ARCHITECTURE.md) — request pipeline + framework differences
- [AGENTIC_CODING_PRACTICE.md](AGENTIC_CODING_PRACTICE.md) — the v2 contract for AI agent developers
- [../benchmark/BENCH_RESULTS.md](../benchmark/BENCH_RESULTS.md) — historical bench numbers
