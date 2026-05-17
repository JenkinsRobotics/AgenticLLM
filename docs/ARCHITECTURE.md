# Architecture

This doc describes the system as it stands. Two parallel agent frameworks
share one model and one tool implementation set; what differs is the prompt
design, the output format, and the parse/round-trip pattern.

## System diagram

```
              ┌────────────────────────────────────────────────────────┐
              │                  main.py (dispatcher)                   │
              │ python main.py [python_custom_json|python_hermes_xml]   │
              │   (future: pygentic | hermes_agent — real upstreams)    │
              └────────────┬──────────────────────────┬─────────────────┘
                           │                          │
              ┌────────────▼──────────┐ ┌─────────────▼───────────┐
              │  python_custom_json/  │ │  python_hermes_xml/      │
              │  JSON + GBNF grammar  │ │  <tool_call> XML format  │
              │  (was "pygentic/")    │ │  (was "hermes/")         │
              └────────────┬──────────┘ └──────────────┬──────────┘
                           │                      │
                           │   Both share:        │
                           ├──────────────────────┤
                           │   • Gemma 4 26B-A4B (Q4_K_M, ~15.6 GB)
                           │   • llama-cpp-python Metal build
                           │   • Same 11 sandboxed tools
                           │   • LLMResult dataclass + latency reporting
                           ▼
              ┌─────────────────────────────┐
              │   bench.py                  │
              │   Runs both head-to-head,   │
              │   writes bench_history.jsonl│
              └─────────────────────────────┘
```

## Per-request pipeline

Both frameworks follow the same three-stage pipeline; the steps differ only in
message format and grammar enforcement.

```
  user text
     │
     ▼
  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
  │  decide  │───▶│  parse   │───▶│   tool   │───▶│ finalize │
  └──────────┘    └──────────┘    └──────────┘    └──────────┘
     │                │               │               │
   model            router          Python         model
   (LLM)            (regex)         function       (LLM, optional)
     │                │               │               │
     │ tool-call      │ ToolDecision  │ tool_result   │ natural-language
     │ or final       │               │ dict          │ answer
     ▼                ▼               ▼               ▼
  ─ time ─────────────────────────────────────────────────────▶
  TTFT₁           ~0ms            ~tool latency    TTFT₂

  Stages logged: decision, tool, final, total (+ TTFT per LLM call).
```

If the decision is `{"final":"..."}` (no tool needed), the pipeline short-circuits
after parse. If the tool's default mode is `fast`, finalize is skipped and the
tool result is formatted directly.

## What differs between Pygentic and Hermes

|                       | Pygentic                                            | Hermes                                                                  |
|-----------------------|-----------------------------------------------------|-------------------------------------------------------------------------|
| System prompt size    | ~25 lines plain text                                | ~150 lines (JSON Schema for every tool)                                 |
| Output format         | `{"tool":"x","args":{...}}` or `{"final":"..."}`    | `<tool_call>{"name":"x","arguments":{...}}</tool_call>` or plain text   |
| Decoding              | GBNF grammar-constrained (cached per process)       | Unconstrained                                                           |
| Tool-result re-entry  | `Tool result: <json>` appended as user turn         | `<tool_response>{"name":...,"content":...}</tool_response>` user turn   |
| Parse on failure      | Raises ValueError (loud)                            | Falls back to treating output as final answer (forgiving)               |
| Pros                  | Hard format guarantee, lighter cold prefill         | Faster warm decode, clean free-text answers                             |
| Cons                  | JSON-wraps free-text answers (slow on stories etc.) | Heavier first-call prefill; relies on model to follow format            |

## Key design decisions

### 1. Same system prompt across `decide` and `finalize` (Pygentic)

When `finalize()` uses a different system prompt than `decide()`, every
finalize call overwrites the KV cache prefix that the *next* decide would
otherwise hit. We measured ~0.3 s of avoidable TTFT on every natural-mode
follow-up. `pygentic/prompts.py` now exposes one `SYSTEM_PROMPT` that covers
both turns; `DECISION_SYSTEM_PROMPT` / `FINAL_SYSTEM_PROMPT` remain as aliases
for back-compat.

### 2. GBNF grammar cached per client

`LlamaGrammar.from_string()` parses 50-200 ms of grammar text on every call
if you let it. `LlamaCppPythonClient._compile_grammar()` caches by grammar
string so each grammar is parsed once per process.

### 3. Per-tool default response mode

`TOOL_DEFAULT_MODE` in each `tool_router.py` decides whether a tool's output
*is* the answer (fast) or needs a natural-language summary (natural). The
decision model doesn't have to emit a `"mode"` field — the router infers it
from the tool. This shaves tokens from every decision output.

### 4. Sandboxed workspace per framework

`python_custom_json/workspace/` and `python_hermes_xml/workspace/` are independent. Every file
tool resolves paths through `workspace_path()` which `Path.resolve()`s and
verifies the result stays inside `WORKSPACE`. Symlinks pointing outside the
sandbox get rejected. The model can request "save to Desktop" all it likes;
the file lands in the workspace and the natural-language reply says where.

### 5. SSML in the TTS tool (minimal subset)

`speak()` and `speak_file()` recognize three tags:

- `<speak>...</speak>` — wrapper, stripped
- `<break time="200ms"/>` — insert silence (`ms` or `s`)
- `<breath/>` — short silent gap (220 ms)

Parsing is regex; silence is `numpy.zeros`. No speed cost on the plain-text
path because the SSML branch is only entered when a tag is present.

### 6. Same model for both frameworks

Both packages default to the same Gemma 4 26B-A4B GGUF. We're comparing
framework idioms, not model capability. Swap models via `--model-path` on
either runner if you want a model-vs-framework matrix.

## Latency report shape

Every `run_command` writes one line to `<framework>/logs/latency.jsonl`:

```json
{
  "framework": "pygentic",
  "timestamp": "2026-05-12T15:23:01+00:00",
  "run_id": "2026-05-12T15:23:00+00:00",
  "user": "what time is it",
  "decision_raw": "{\"tool\":\"get_time\",\"args\":{}}",
  "decision": {"tool": "get_time", "args": {}, "mode": "fast", "final": null},
  "tool_result": {"datetime": "2026-05-12 03:23:01 PM UTC", "iso": "..."},
  "answer": "2026-05-12 03:23:01 PM UTC",
  "mode": "fast",
  "latency": {
    "decision": 0.847,
    "decision_ttft": 0.129,
    "tool": 0.001,
    "final": 0.0,
    "final_ttft": 0.0,
    "total": 0.848
  }
}
```

`run_id` is set by `bench.py` so all entries from one benchmark run group
together. Interactive sessions still get a `timestamp` but no `run_id`.

## Memory (opt-in via `--with-memory`, unified across interfaces)

Memory is a project-root sibling of the frameworks — `memory/` — so every
agent process and future interface (voice, Discord, web) reads and writes
the same files. That's what makes the agent feel like the same individual
no matter where it's running.

Four layers, the first three wired today:

| Layer | File | Tools | Purpose |
|---|---|---|---|
| **Identity** | `memory/identity.md` | (none — auto-loaded) | Stable persona, voice, behavioral hints. Prepended to every framework's system prompt when `--with-memory` is set. ~100 tokens of prefill, cached after the first call. |
| **Facts** | `memory/facts.json` | `remember(key, value)`, `recall(key)`, `forget(key)`, `list_facts` | Key/value scratchpad the agent self-curates as the user shares preferences or topics. Atomic writes (temp + fsync + rename) so concurrent processes never see half-written files. **Tools are always registered** (not gated by --with-memory); identity injection just primes the model to use them. |
| **Episodic** | `memory/episodic.jsonl` | (no tool yet; auto-loaded) | Append-only per-turn log across all interfaces. When `--with-memory` is set, every turn is appended *and* the last N (default 5) are loaded into the session history at startup so the model sees prior conversation context. |
| **Semantic** *(future, optional)* | `memory/semantic/` | `recall_similar(query)` | FAISS-backed embeddings for "what did we talk about last week" queries. |

### Why opt-in (matches MCP/thinking)

The user's design principle is "default stays fast; everything else is
opt-in." Identity + history adds ~100-300 prefill tokens (cached) plus an
accumulating message-history prefix as the session continues. Small but
measurable. Making it opt-in lets the bench A/B raw vs memory cleanly.

For interactive product use, agents should be launched with `--with-memory`
so they feel like Lilith. For benchmark comparisons, `default` mode runs
without identity to isolate framework cost from memory cost.

### Session history (the Phase-2 addition)

When `--with-memory` is set, each framework keeps an in-process
`_session_history` list of `(user_msg, assistant_decision)` pairs. Every
new `decide()` / `finalize()` call sends:

```
[system, ...history, user_text]
```

The KV-cache prefix is preserved: the system prompt + earlier history
turns are reused; only the new user message needs fresh prefill. After
each turn, the new pair is appended to history (capped at the last 10
turns to bound prefix growth) and also written to `memory/episodic.jsonl`
for cross-session continuity.

This is what fixes the "key consistency" problem we observed in Phase 1:
the model can now see "I called `remember(key='X')`" three turns ago, so
when asked to recall, it uses the same key.

### Implementation details

- `memory/memory_module.py` is the shared module both frameworks import.
  Same functions, same files, same view of the world.
- Each framework's `_build_base_system_prompt()` prepends identity.md to its
  own routing prompt at module-load time. MCP-extended prompts also flow
  through this helper so identity stays at the top.
- Atomic write strategy: temp file in the same directory → `fsync` → `os.replace`.
  Cross-process safety follows from `os.replace` being atomic on POSIX.
- In-process safety: a `threading.Lock` around the read-modify-write cycle
  so two threads in one process never lose a write to each other.

### Memory + extensions

- **Memory + MCP**: independent. Memory tools live in-process for speed
  (sub-millisecond). MCP tools handle external capability (fetch, browser,
  etc.). Both addressable from the same router.
- **Memory + thinking**: thinking jobs also see the identity layer because
  they reuse the framework's `_pipeline["system_prompt"]`. So background
  reasoning is "as Lilith" too, not a generic chain-of-thought voice.

## Opt-in extensions

The default pipeline is hand-tuned for speed. Two extensions are available as
opt-in capability without touching that fast path:

### MCP (`--with-mcp`)

Connects the agent to one or more MCP (Model Context Protocol) servers
declared in `mcp_config.json`. Each server's tools are registered globally
with the namespaced name `mcp:<server>/<tool>` and merged into the
framework's tool surface.

```
┌─────────────────┐    JSON-RPC over stdio    ┌────────────────────────┐
│ pygentic/hermes │◀─────────────────────────▶│  mcp-server-fetch      │
│  + mcp_bridge   │     ClientSession         │  (Python subprocess)   │
└─────────────────┘                           └────────────────────────┘
```

Implementation details:

- `mcp_bridge.py` owns a persistent asyncio event loop running in a daemon
  thread. The bridge submits coroutines to it via `run_coroutine_threadsafe`
  so the rest of the agent stays synchronous.
- Each MCP server is a stdio subprocess (`python -m mcp_server_fetch`, for
  example). The `ClientSession` is kept open for the lifetime of the process.
- Tool discovery happens once at startup; results are cached in a module-level
  `MCPRegistry`. No per-call discovery overhead.
- When `--with-mcp` is set, the framework's system prompt is rebuilt once to
  include the extra tool descriptions, and (for Pygentic only) the GBNF
  grammar is rebuilt to include the new tool names as valid alternatives.
- Default agent paths import nothing from `mcp_bridge` — there's no cost
  when the flag is off.

Trade-offs: each MCP call adds ~50–200 ms of IPC + JSON serialization vs.
an in-process Python call. Fast for capabilities our in-process tools
don't offer (URL fetch, browser, persistent memory); not worth it as a
replacement for trivially fast in-process tools (`get_time`, `calculate`).

### Background thinking (`--think`)

Runs a chain-of-thought-style "thinking" LLM call after each user turn, in
a background thread, with results logged to `thinking.jsonl`. The main
response is unblocked.

```
   main thread                   thinking thread (single-worker pool)
   ────────────                  ──────────────────────────────────
   acquire llm_lock              wait for lock
     decide ────▶ tool ────▶ final
   release lock         ◀─────── queue("user text")
   return to caller              acquire lock (now free)
                                   chat(thinking-prompt)
                                 release lock
                                 append to thinking.jsonl
```

Implementation details:

- `thinking_runner.ThinkingRunner` owns a single-worker `ThreadPoolExecutor`
  and a shared `threading.Lock`. The same lock is also acquired by the main
  thread's `run_command` so the model is never called concurrently
  (llama-cpp-python isn't thread-safe for that).
- If the user submits another prompt before the previous thinking call
  finishes, the main thread blocks at `lock.acquire()`. This is the
  intended back-pressure — we never run two completions at once on one
  Llama instance.
- `--think` adds zero cost to the fast path; the lock object is `None`
  when the flag is off, so `run_command` does no acquire/release.

Trade-offs: thinking calls are 200-2000 tokens at decode-time, adding
5-50 s of background work per turn. Useful for planning-heavy prompts
where the *follow-up* turn benefits from the analysis. Not useful for
trivial tool calls.

## File-level pointers

| Path                                | Purpose                                              |
|-------------------------------------|------------------------------------------------------|
| `main.py`                           | Dispatcher: import + call the chosen framework       |
| `bench.py`                          | Head-to-head runner, history aggregator              |
| `memory/memory_module.py`           | Shared persistent memory (identity + facts)          |
| `<fw>/memory/identity.md`           | Stable persona, prepended to every system prompt     |
| `<fw>/memory/facts.json`            | Atomic key/value store for the agent's curated facts |
| `<fw>/mcp_bridge.py`                | Opt-in MCP client + async-to-sync bridge             |
| `<fw>/mcp_config.json`              | List of MCP servers to connect to when --with-mcp    |
| `<fw>/thinking_runner.py`           | Opt-in background thinking runner                    |
| `<fw>/thinking.jsonl`               | Per-turn background thinking log                     |
| `<fw>/main.py`                      | `decide` / `finalize` / `run_command` / `cli_loop`   |
| `<fw>/prompts.py`                   | System prompt; tool descriptions or JSON schemas     |
| `<fw>/tool_router.py`               | `SAFE_TOOLS`, `TOOL_DEFAULT_MODE`, parser, grammar   |
| `<fw>/tools.py`                     | Tool implementations (shared shape across frameworks)|
| `<fw>/llm_client.py`                | llama-cpp-python client + server client              |
| `<fw>/logs/latency.jsonl`           | Per-call latency history                             |
| `bench_history.jsonl`               | One line per (run, framework, prompt) for trend view |

See `docs/BENCHMARKING.md` for how to run benchmarks and read history.
