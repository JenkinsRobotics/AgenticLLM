# python_custom_json

**Hand-rolled agent with strict GBNF-grammar-constrained tool routing. The model emits bare JSON — no XML wrapper, no prose around the call — and the grammar guarantees the output is parseable before a single byte leaves the decoder.**

This framework is the format-safety reference. When you can't trust the model to emit well-formed tool calls (small models, untrusted contexts, brittle parsers), GBNF-constrained decoding makes invalid output impossible by construction. Slower than unconstrained decoding (~10-20%) but the format guarantee is hard rather than statistical.

**Benchmark status:** 23/23 on the routing bench.

---

## Entry points

```bash
# Interactive chat
python main.py python_custom_json

# One-shot
python main.py python_custom_json "what time is it"

# Extensions
python main.py python_custom_json --with-memory
python main.py python_custom_json --with-mcp
python main.py python_custom_json --think
```

---

## Tool-call format

Bare JSON, constrained by a GBNF grammar at decode time. The model emits exactly one of:

```json
{"tool": "get_time", "args": {}}
```

or

```json
{"final": "It's 4:48 PM PDT."}
```

No prose, no `<tags>`, no markdown fences. The grammar (`TOOL_CALL_GRAMMAR` in `tool_router.py`) is compiled by `LlamaCppPythonClient._compile_grammar` and cached by grammar-string identity so repeated calls don't recompile.

Tool result round-trip uses a plain user-role message:

```
Tool result: {"datetime": "2026-05-17 04:48 PM PDT", ...}
```

---

## Tool surface

19 hand-rolled tools, shared (by convention) with `python_hermes_xml`. Declared in `tool_router.py` as `SAFE_TOOLS` with a parallel list of `dict`-style schemas.

| Category | Tools |
|---|---|
| Memory | `remember`, `recall`, `forget`, `list_facts` |
| Files | `create_file`, `append_file`, `delete_file`, `read_file`, `list_directory` |
| Time / math / state | `get_time`, `calculate`, `system_status` |
| Web | `web_search`, `get_weather` |
| Speech | `speak`, `speak_file` |
| Host control | `launch_url`, `open_file`, `open_app` |

Plus dynamically-registered MCP tools when `--with-mcp` is on (named `mcp:<server>/<tool>`).

---

## Routing loop — decide → tool → finalize

Same three-phase pattern as `python_hermes_xml`:

1. **Decide.** Send user prompt + tool schema + grammar; Gemma emits `{"tool": ...}` or `{"final": ...}`.
2. **Tool.** Parse the JSON, dispatch via `tool_router.run_tool(name, args)`.
3. **Finalize.** Send the original prompt + tool call + tool result; Gemma writes the natural-language answer.

Skip-final: same gate as the other frameworks. When `decision.mode == "fast"` and the tool is in `FAST_TOOLS`, the tool result is rendered into the final answer and the finalize LLM call is bypassed.

Multi-step chaining via `_wants_chain()` heuristic. Loop guard halts on repeated tool+args.

**Key file:** `python_custom_json/main.py:run_command` is the entry point that orchestrates these phases.

---

## GBNF grammar

The grammar enforces the output format before sampling. It allows exactly two shapes:

```
root ::= tool-call | final-answer
tool-call ::= "{\"tool\":" tool-name ",\"args\":" args "}"
tool-name ::= "\"get_time\"" | "\"calculate\"" | ... (one per registered tool)
final-answer ::= "{\"final\":" string "}"
```

`tool_router.build_grammar(SAFE_TOOLS)` regenerates this string when the tool list changes (e.g., when MCP tools come online). Grammar compilation is ~50-200 ms; caching by string identity makes it free after the first call.

**Trade-off.** Constrained decoding is ~10-20% slower than unconstrained per token (Gemma evaluates the grammar at each sampling step). But you never need a retry, the parser never crashes, and free-text answers can't pollute tool calls.

---

## System prompt

`prompts.py` has a single `SYSTEM_PROMPT` shared across decide + finalize (same KV-cache-friendly pattern as `python_hermes_xml`). It includes:

- Identity line
- A plain-text list of tools (just names + one-line descriptions — no JSON Schema since the grammar handles validation)
- Format rules ("emit exactly one JSON object, no prose, no markdown")
- The 4 MANDATORY rules (remember/recall/forget/speak_file)

The system prompt is intentionally lighter than `python_hermes_xml`'s — the grammar carries most of the format burden, so the prompt doesn't need to spell out the JSON Schema for every tool.

---

## Memory model

`python_custom_json/memory/`:

```
memory/
├── facts.json
├── episodic.jsonl
└── episodic.embeddings.npz
```

Gated by `--with-memory`. Default off (bench-clean).

---

## Plugin system

`python_custom_json/plugins/`:

- `mcp_bridge.py` — MCP server registry. When MCP tools register, the grammar is rebuilt to include their names in the `tool-name` alternation.
- `thinking_runner.py` — background CoT, logs to `plugins/thinking.jsonl`.

---

## Sandbox

File ops restricted to `python_custom_json/workspace/`. Same path discipline as the other in-process frameworks.

---

## Key files

| Path | Purpose |
|---|---|
| `main.py` | CLI, `run_command`, decide-tool-finalize orchestration |
| `prompts.py` | Shared `SYSTEM_PROMPT` |
| `tool_router.py` | `SAFE_TOOLS`, GBNF grammar builder, parser, `FAST_TOOLS` |
| `tools.py` | Tool implementations (re-export shim) |
| `llm_client.py` | `LlamaCppPythonClient` with grammar compilation cache |
| `core/tools/*.py` | One file per category |
| `plugins/mcp_bridge.py` | MCP integration |
| `plugins/thinking_runner.py` | Background CoT |

---

## Benchmark dispatch

```bash
python benchmark/bench.py --only python_custom_json
```

Loaded in-process:
```python
from python_custom_json.llm_client import LlamaCppPythonClient
from python_custom_json.main import init_from_env, run_command, shutdown_extensions
```

23/23 on the routing bench (strict tool-name validation).

---

## Performance notes

- **Cold-start wins, warm decode loses.** The plain-text tool list prefills faster than `python_hermes_xml`'s JSON Schema block (~25 lines vs ~150). On the very first call this framework leads by ~150 ms. After the prefix cache warms, unconstrained decoding pulls `python_hermes_xml` ahead by 50-100 ms per turn.
- **Cache the compiled grammar.** `LlamaGrammar.from_string()` adds 50-200 ms per call without caching. `LlamaCppPythonClient._compile_grammar` caches by grammar string — important when MCP changes invalidate the grammar.
- **JSON-wrapping free-text is expensive.** Wrapping every final answer through `{"final": "..."}` triples generation time for jokes / stories / titles vs plain text. A hybrid grammar that allows either a constrained tool-call OR unconstrained free text would close this gap.
- **Same single-prompt-across-turns pattern** as `python_hermes_xml` — separate decide/finalize prompts clobber KV cache.

---

## When to use this framework

- The model is small (≤4B) and free-text drifts often
- You need format guarantees stronger than "the parser is robust"
- Cold-start matters more than warm-decode throughput
- You're integrating with a non-LLM consumer of tool calls that can't tolerate format drift

For everyday agent work where Gemma 4 is reliable enough, `python_pydantic_ai` (or `python_hermes_xml` for unconstrained speed) will be faster.

---

## Related docs

- [PYTHON_HERMES_XML.md](PYTHON_HERMES_XML.md) — the unconstrained sibling
- [FRAMEWORKS.md](FRAMEWORKS.md) — side-by-side comparison
- [ARCHITECTURE.md](ARCHITECTURE.md) — pipeline details
