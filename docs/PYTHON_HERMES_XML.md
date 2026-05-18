# python_hermes_xml

**Hand-rolled agent using the Nous Function-Calling XML format. Decide-tool-finalize loop with no grammar constraint — unconstrained decoding for faster generation, with an XML parser extracting `<tool_call>` blocks from free text.**

This framework is the reference for the function-calling format the underlying Hermes-style models were trained on. It uses no agent framework — just direct llama-cpp-python calls, a hand-written parser, and a deliberate three-phase loop. Slower than `python_pydantic_ai` on the warm path but useful as a control: same model, same tools, very different routing layer.

**Benchmark status:** 23/23 on the routing bench.

---

## Entry points

```bash
# Interactive chat
python main.py python_hermes_xml

# One-shot
python main.py python_hermes_xml "search the web for robot vacuum reviews"

# Extensions
python main.py python_hermes_xml --with-memory
python main.py python_hermes_xml --with-mcp
python main.py python_hermes_xml --think
```

No voice plugin yet — voice support lives in jaeger/pydantic_ai's `plugins/voice_loop.py`. Wire hermes_xml when bringup gets its own voice plugin.

---

## Tool-call format

XML-wrapped JSON. The model emits:

```xml
<tool_call>{"name": "get_time", "arguments": {}}</tool_call>
```

inside free text. The parser pulls the block out, dispatches the tool, then sends the result back as:

```xml
<tool_response>{"datetime": "2026-05-17 04:48 PM PDT", ...}</tool_response>
```

Tool schemas are declared as JSON Schema inside `<tools></tools>` in the system prompt. No grammar constraint at decode time — Gemma generates freely and we parse the result.

**Strength:** Unconstrained decoding is faster than grammar-constrained (~10-20% on warm turns) and the prose around tool calls is more natural.
**Weakness:** Format violations are possible. The parser has drift recovery for common variations (`<function_call>` instead of `<tool_call>`, missing closing tag, etc.) but malformed output requires a retry.

---

## Tool surface

19 hand-rolled tools, shared (by convention, not by import) with `python_custom_json`. Declared in `tool_router.py` as `SAFE_TOOLS`.

| Category | Tools |
|---|---|
| Memory | `remember`, `recall`, `forget`, `list_facts` |
| Files | `create_file`, `append_file`, `delete_file`, `read_file`, `list_directory` |
| Time / math / state | `get_time`, `calculate`, `system_status` |
| Web | `web_search`, `get_weather` |
| Speech | `speak`, `speak_file` |
| Host control | `launch_url`, `open_file`, `open_app` |

Plus dynamically-registered MCP tools when `--with-mcp` is on.

---

## Routing loop — decide → tool → finalize

Three explicit phases per turn, each a separate LLM call (unless skip-final fires):

1. **Decide.** Send the user prompt + tool schema; Gemma either emits free text (final answer) or a `<tool_call>` block.
2. **Tool.** Parse the XML, dispatch via `tool_router.run_tool(name, args)`, capture the result dict.
3. **Finalize.** Send the original prompt + tool call + tool result; Gemma writes the natural-language answer.

The skip-final optimization (similar to `python_pydantic_ai`): when the tool is in `FAST_TOOLS` and `decision.mode == "fast"`, the tool result is rendered into the final answer by `format_result_as_answer()` and the finalize LLM call is skipped.

Multi-step chaining is gated by `_wants_chain()` — a heuristic that detects intent like "and then…" or "after that…" and continues the loop. Otherwise, single-step by default. Loop guard halts if the same tool+args is called twice in a row.

---

## System prompt

Two prompts share the same prefix (`SYSTEM_PROMPT`) so the KV cache is reused across decide+finalize. The prompt includes:

- Identity line
- The tool schema in `<tools>...</tools>` blocks (JSON Schema for each tool)
- Format rules (use `<tool_call>` exactly once when calling a tool; emit prose otherwise)
- The same 4 MANDATORY rules pattern as the other frameworks (remember/recall/forget/speak_file)

Using one prompt across both turns is critical: separate decide/finalize prompts caused the finalize call to clobber the KV cache, adding ~300 ms to the next decide.

---

## Memory model

`python_hermes_xml/memory/` — same shape as `python_pydantic_ai`'s memory dir:

```
memory/
├── facts.json
├── episodic.jsonl
└── episodic.embeddings.npz
```

Gated by `--with-memory`. Default off (bench-clean).

---

## Plugin system

`python_hermes_xml/plugins/`:

- `mcp_bridge.py` — MCP server registry (same design as the other frameworks)
- `thinking_runner.py` — background CoT, logs to `plugins/thinking.jsonl`

No `messaging/` plugin in this framework — messaging is `python_pydantic_ai` and `python_jaeger` only.

---

## Sandbox

File ops restricted to `python_hermes_xml/workspace/`. Same model as `python_pydantic_ai`: relative paths, no `..`, no absolutes, no `~`.

---

## Key files

| Path | Purpose |
|---|---|
| `main.py` | CLI, the three-phase decide-tool-finalize loop |
| `prompts.py` | Shared `SYSTEM_PROMPT` (decide + finalize) |
| `tool_router.py` | `SAFE_TOOLS` registry, XML parser, drift recovery |
| `tools.py` | Tool implementations (one module re-exporting subfiles) |
| `llm_client.py` | `LlamaCppPythonClient` (in-process + HTTP-server modes) |
| `core/tools/*.py` | One file per category |
| `plugins/mcp_bridge.py` | MCP support |
| `plugins/thinking_runner.py` | Background CoT |

---

## Benchmark dispatch

```bash
python benchmark/bench.py --only python_hermes_xml
```

Loaded in-process by `benchmark/bench.py`:
```python
from python_hermes_xml.llm_client import LlamaCppPythonClient
from python_hermes_xml.main import init_from_env, run_command, shutdown_extensions
```

23/23 on the routing bench (strict tool-name validation).

---

## Performance notes

- **Warm decode wins, cold prefill loses.** The XML system prompt with full JSON Schema is heavier than `python_custom_json`'s tool list (~150 lines vs ~25). First-call prefill costs ~+200 ms; after that, llama.cpp's prefix cache equalizes and unconstrained decoding pulls ahead.
- **Parser drift recovery is load-bearing.** Without `drift_call_form_2` etc. in `tool_router.py`, ~5% of routing decisions get rejected on slight format variations. With recovery on, the framework hits 23/23.
- **One system prompt across decide+finalize** is the single most important optimization for warm latency — see the comment in `prompts.py`.

---

## Related docs

- [PYTHON_CUSTOM_JSON.md](PYTHON_CUSTOM_JSON.md) — the GBNF-constrained sibling
- [FRAMEWORKS.md](FRAMEWORKS.md) — side-by-side comparison
- [ARCHITECTURE.md](ARCHITECTURE.md) — pipeline details
