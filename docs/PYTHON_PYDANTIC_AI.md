# python_pydantic_ai

**Fast Pydantic-AI-based local agent with a custom in-process llama-cpp-python `Model` adapter. The lean reference implementation that `python_jaeger` was forked from.**

This framework is the routing-speed leader. It uses Pydantic AI's typed `@agent.tool_plain` decorators with our custom `LlamaCppModel` adapter so Gemma 4 runs in-process while pydantic-ai handles tool-call format, retries, and message threading. The `agent.iter()` skip-final intercept saves ~280 ms on simple commands by bypassing the second LLM round-trip when the tool result IS the answer.

**Benchmark status:** 23/23 on the routing bench.

---

## Entry points

```bash
# Interactive chat
python main.py python_pydantic_ai

# One-shot
python main.py python_pydantic_ai "what time is it"

# Extensions
python main.py python_pydantic_ai --with-memory       # carry history across turns
python main.py python_pydantic_ai --with-mcp          # MCP server tools
python main.py python_pydantic_ai --think             # background CoT
```

The voice loop (`voice_assistant.py`) and messaging gateway (`plugins/messaging/gateway.py`) both default to this framework as the agent backend.

---

## Tool-call format

Pydantic AI's native typed `Tool` system. We do **not** parse JSON or XML ourselves — pydantic-ai handles tool-call format, type validation, and retries.

Tool declarations are inferred from Python function signatures + docstrings:

```python
@agent.tool_plain
def remember(key: str, value: str) -> dict:
    """MANDATORY when the user states a preference, identity fact,
    plan, or anything they might recall later ("remember that…",
    "my favorite X is…", "I'll be in town on…")...."""
    return tools.remember(key=key, value=value)
```

Drift recovery: if Gemma emits a tool call in a slightly off format, pydantic-ai's `ModelRetry` triggers a re-decode with a hint about what the correct shape looks like — up to `tool_retries=2`.

---

## Tool surface

30 typed tools, organized one-file-per-category in `core/tools/`. Same shape jaeger inherited.

| Category | Tools |
|---|---|
| Memory | `remember`, `recall`, `forget`, `list_facts`, `search_memory` |
| Files | `create_file`, `append_file`, `delete_file`, `read_file`, `list_directory` |
| Time / math / state | `get_time`, `calculate`, `system_status` |
| Web | `web_search`, `get_weather` |
| Speech | `speak`, `speak_file`, `warm_kokoro` |
| Vision | `look_at`, `generate_image` |
| Host control | `launch_url`, `open_file`, `open_app` |
| Scheduling | `schedule_prompt`, `list_schedules`, `cancel_schedule` |
| Code | `run_python` |
| Messaging | `send_message` |
| Coordination | `delegate`, `ask_user`, `help_me` |

Plus dynamically-registered MCP tools when `--with-mcp` is on.

---

## Routing loop — `agent.iter()` + skip-final intercept

The defining optimization of this framework. Implementation lives in `_run_via_iter`:

1. Drive the agent with `async with agent.iter(user_text, message_history=history) as run:`.
2. As nodes stream in, watch for `CallToolsNode` — exposes the first tool call before it runs.
3. If `len(tool_parts) == 1 and tc.tool_name in SKIP_FINAL_TOOLS` → mark `skip_final = True`.
4. Wait for the next `ModelRequestNode` — its parts contain the `ToolReturnPart` with the tool result.
5. Synthesize the final answer via `_format_tool_result_as_answer(tool_name, result_dict)` — bypasses the second LLM call entirely.

The 17 tools in `SKIP_FINAL_TOOLS` are the ones whose dict result IS the user-facing answer: `get_time`, `calculate`, `remember`, `recall`, `forget`, `delete_file`, `create_file`, `append_file`, `speak`, `speak_file`, `launch_url`, `open_file`, `open_app`, `ask_user`, `schedule_prompt`, `cancel_schedule`, `delegate`, `send_message`, `help_me`.

**Why it matters.** A bare `get_time` request without skip-final: ~620 ms (decide LLM + tool + finalize LLM). With skip-final: ~340 ms. The finalize step's job ("respond with the time the tool returned") is pure overhead — Gemma's second call always restates the value verbatim.

---

## System prompt

Lean by design. Lives in `core/prompts.py` as `SYSTEM_PROMPT`:

```
You are Lilith, a fast local AI tool router built on Pydantic AI.

Mandatory tool rules — these are not suggestions:

1. PERSISTING FACTS. If the user states a preference, identity fact, ...
2. RECALLING FACTS. If the user asks about something they told you ...
3. FORGETTING FACTS. "Forget my X" ... require calling `forget(key)`.
4. NARRATING FILES. "Read X out loud" with a NAMED FILE means: speak_file.

The only writable area is the sandboxed workspace at python_pydantic_ai/workspace.
[behavior rules...]
```

Four imperative rules near the top, plus a sandbox declaration and behavior guidelines. ~60 lines, ~500 words total. The lean prompt is what keeps Gemma's MANDATORY-rule attention high — piling in more rules dilutes them (this is the lesson the jaeger refactor confirmed).

---

## Memory model

Per-framework directory: `python_pydantic_ai/memory/`.

```
memory/
├── facts.json                ← k/v store (fcntl-locked)
├── episodic.jsonl            ← append-only cross-session turn log
├── episodic.embeddings.npz   ← sentence-transformers index for search_memory
└── identity.md               ← optional persona, prepended when --with-memory
```

Gated by `--with-memory`. Default off → fresh context per prompt (bench-clean). When on:
- Last 5 episodic turns load on first prompt per `session_key` (default `"voice"`).
- In-process history accumulates up to `_MAX_HISTORY_MESSAGES = 20`.
- Each turn writes to `episodic.jsonl` for cross-session recall.

The bench leaves it off so the routing benchmark stays at 23/23 — accumulated history was costing 3/23 on Gemma 4.

---

## Plugin system

Plugins in `python_pydantic_ai/plugins/`.

### `plugins/mcp_bridge.py`
Connects to MCP servers from `plugins/mcp_config.json`. JSON Schema → pydantic-ai `Tool` via `Tool.from_schema`. Add a new server in the config; tools register on next agent build.

### `plugins/thinking_runner.py`
Background chain-of-thought after each user turn. Single-worker pool sharing the main LLM lock so it never decodes concurrently. Writes `plugins/thinking.jsonl`.

### `plugins/messaging/`
- `gateway.py` — loads agent once, starts every adapter with credentials
- `discord_bridge.py`, `telegram_bridge.py`, `imessage_bridge.py` — per-channel inbound + outbound
- Shared registry; `send_message(channel, recipient, text)` pushes proactive messages from the agent or a scheduled prompt

Same plugin shape jaeger ported verbatim — see [PYTHON_JAEGER.md](PYTHON_JAEGER.md) for the deeper writeup; the architectures are identical.

---

## Sandbox

File ops are restricted to `python_pydantic_ai/workspace/`. Path arguments are relative to that root — no `~`, no absolute paths, no `..` escapes. If the user asks to save to Desktop, the file lands in `workspace/` and the agent's reply explains where it actually went.

This is the simpler sandbox model that jaeger replaced with the instance-isolation pattern. For a single-user dev setup, `workspace/` is sufficient and faster (no instance bookkeeping).

---

## Prewarm

The first agent call against a freshly-loaded model pays a ~1 s prefill cost to tokenize the system prompt + tool schema. `prewarm(client)` runs a single trivial turn at startup so the cost moves from the first user turn into the load phase. Idempotent.

```python
prewarm(client)  # called once after model load
```

Saves ~1 second from the user's first observed latency.

---

## Bridging API

For external entry points (voice loop, messaging gateway, bench):

| Function | Purpose |
|---|---|
| `LlamaCppPythonClient(ctx=4096, warmup=True)` | Load Gemma in-process |
| `init_extensions(args, client)` | Wire memory / MCP / thinking from flags + env vars |
| `prewarm(client)` | Prime KV cache |
| `run_command(client, user_text, mode, session_key)` | CLI / one-shot — prints to stdout |
| `run_for_voice(client, user_text, session_key)` | Same as run_command but returns `{text, tool_activity, spoke_via_tool, elapsed_s, ...}` |
| `shutdown_extensions(wait=True)` | Drain background thinking jobs |

The voice loop calls `run_for_voice`; the bench calls `run_command`; the messaging gateway calls `run_for_voice` with channel-keyed `session_key`.

---

## Key files

| Path | Purpose |
|---|---|
| `main.py` | CLI, agent build, `_run_via_iter`, `init_extensions`, `run_for_voice` |
| `core/prompts.py` | `SYSTEM_PROMPT` constant |
| `core/llm_model.py` | `LlamaCppModel` — pydantic-ai `Model` adapter over llama-cpp-python |
| `core/tools/*.py` | One file per tool category |
| `memory/memory_module.py` | facts.json read/write, episodic append, semantic search |
| `memory/cron_runner.py` | Background scheduler for `schedule_prompt` |
| `memory/config.py` | User-facing display config (memory/config.json) |
| `plugins/mcp_bridge.py` | MCP registry + tool routing |
| `plugins/thinking_runner.py` | Background CoT |
| `plugins/messaging/*.py` | Multi-channel adapters |
| `tools.py` | Backward-compat shim re-exporting from `core.tools` |

---

## Benchmark dispatch

```bash
python benchmark/bench.py --only python_pydantic_ai
```

Loaded in-process by `benchmark/bench.py`:
```python
from python_pydantic_ai.main import LlamaCppPythonClient, init_extensions, run_command, prewarm
```

23/23 on the routing bench (strict tool-name matching — same surface as `python_custom_json` and `python_hermes_xml`).

---

## Related docs

- [PYTHON_JAEGER.md](PYTHON_JAEGER.md) — the production fork with skill versioning + instance isolation
- [FRAMEWORKS.md](FRAMEWORKS.md) — side-by-side with the other four
- [ARCHITECTURE.md](ARCHITECTURE.md) — request pipeline
