# AgenticLLM

A fast local agentic LLM harness on macOS. Two frameworks — **Pygentic** (JSON + GBNF grammar) and **Hermes** (Nous Function-Calling) — run the same Gemma 4 26B-A4B model against the same 11 sandboxed tools, so you can A/B their prompt design, output format, and round-trip pattern head-to-head.

The goal is to maximize fast local realtime agentic performance and surface where prompt design + output format actually matter for tool-calling latency.

## What's in the box

| | Pygentic | Hermes |
|---|---|---|
| Tool-call format | Bare JSON: `{"tool":"x","args":{...}}` | XML: `<tool_call>{"name":"x","arguments":{...}}</tool_call>` |
| Tool declarations | Plain-text list in system prompt | JSON Schema in `<tools>` block |
| Decoding | GBNF grammar-constrained | Unconstrained |
| Tool result round-trip | Appended user turn: `Tool result: ...` | `<tool_response>{...}</tool_response>` turn |
| Strength | Hard format guarantee; cheaper cold start | Faster warm decode; cleaner free-text |

Both share the same model, the same tool implementations, the same `LlamaCppPythonClient` plumbing, and the same latency reporting format. The only things that differ are `prompts.py`, `tool_router.py`, and the `decide` / `finalize` call shapes in `main.py`.

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
.venv/bin/python main.py pygentic --self-test
.venv/bin/python main.py hermes   --self-test
```

If both print a series of `{"decision": ..., "result": ...}` lines without errors, the install is healthy.

## Running

### Interactive chat

```bash
.venv/bin/python main.py pygentic    # Pygentic chat loop
.venv/bin/python main.py hermes      # Hermes chat loop
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
.venv/bin/python main.py pygentic "what time is it"
.venv/bin/python main.py hermes "search the web for robot vacuum reviews"
```

Useful for scripting or running a fixed prompt without the interactive loop.

### Head-to-head benchmark

```bash
.venv/bin/python bench.py                       # default mode
.venv/bin/python bench.py --with-mcp            # adds opt-in MCP prompts
.venv/bin/python bench.py --think               # adds background thinking
.venv/bin/python bench.py --only pygentic       # one framework only
.venv/bin/python bench.py --prompts file.txt    # custom prompt list
.venv/bin/python bench.py --skip-run            # re-summarize existing logs
.venv/bin/python bench.py --history             # trend view across runs
```

Each run gets a `mode_tag` (`default` / `mcp` / `think` / `mcp+think`) in `bench_history.jsonl` so trends compare cleanly. Two default prompts play audio (`read bench.txt`, `narrate youtube_intro.txt`); pass a smaller prompt list to skip TTS.

Two prompts in the default set play audio out loud (`read bench.txt out loud`, `narrate youtube_intro.txt`). Skip them by passing a smaller prompt list if you don't want TTS during benchmarking.

## Tools

Both frameworks expose the same 15 tools (11 in-process + 4 unified-memory tools added below). File ops are confined to each framework's own `workspace/` — even if you ask the model to "save to Desktop," it lands in the workspace and the reply tells you where it actually went. Memory lives in a shared `memory/` directory at the project root so every interface sees the same identity and facts.

| Tool | Args | Purpose | Default mode |
|---|---|---|---|
| `get_time` | optional `timezone` (IANA) | Current date/time, optionally in a given timezone | fast |
| `create_file` | `path`, `content` | Write a text file (overwrites) | natural |
| `append_file` | `path`, `content` | Append to an existing file | natural |
| `delete_file` | `path` | Delete a file in the workspace | natural |
| `read_file` | `path` | Read a text file | fast |
| `list_directory` | `path` | List a directory | fast |
| `system_status` | — | CPU / disk / load | fast |
| `calculate` | `expression` | Safe arithmetic via AST eval (no `eval()`) | fast |
| `speak` | `text` | Kokoro TTS through default audio output | fast |
| `speak_file` | `path` | Read a file and speak it (single-call narration) | fast |
| `web_search` | `query` | DuckDuckGo via `ddgs`, no API key | natural |
| `remember` | `key`, `value` | Save a fact to shared `memory/facts.json` | fast |
| `recall` | `key` | Look up a previously stored fact | fast |
| `list_facts` | — | List every fact currently in memory | fast |
| `forget` | `key` | Remove a stored fact | fast |

`fast` mode returns the raw tool result without a second LLM call. `natural` mode runs `finalize` so the answer is a short natural-language summary. Override either with `--mode fast` / `--mode natural`.

## Project structure

```
AgenticLLM/
├── main.py             # Dispatcher: python main.py [pygentic|hermes] [prompt]
├── bench.py            # Head-to-head benchmark + comparison table
├── requirements.txt
├── pygentic/           # JSON + GBNF grammar framework
│   ├── main.py          # decide / finalize / CLI loop
│   ├── prompts.py       # Unified system prompt (shared decide+finalize)
│   ├── tool_router.py   # SAFE_TOOLS, GBNF grammar, parser
│   ├── tools.py         # Tool implementations (shared shape with hermes/)
│   ├── llm_client.py    # llama-cpp-python + server clients
│   ├── logs/            # latency.jsonl (append-only history)
│   └── workspace/       # Sandboxed file ops
├── hermes/             # Nous Function-Calling framework (same shape)
├── memory/             # Unified memory — shared across all interfaces
│   ├── identity.md      # Stable persona, prepended to every system prompt
│   ├── facts.json       # Atomic key/value scratchpad
│   └── memory_module.py # Shared read/write helpers
├── mcp_bridge.py       # Opt-in MCP client (--with-mcp)
├── mcp_config.json     # MCP servers to connect to when MCP is enabled
├── thinking_runner.py  # Opt-in background thinking (--think)
├── thinking.jsonl      # Background thinking log (written when --think runs)
└── docs/               # PROJECT.md, ARCHITECTURE.md, BENCHMARKING.md, SETUP.md, TODO.md
```

## Performance notes

A few non-obvious findings from running both frameworks side-by-side on Gemma 4 26B-A4B Q4_K_M:

- **Hermes wins on warm prompts, Pygentic wins on cold start.** Pygentic's lighter system prompt (~25 lines) prefills faster than Hermes's heavier JSON-Schema block (~150 lines) on the very first call. After that, llama.cpp's prefix cache equalizes the prefill cost and Hermes's unconstrained decode pulls ahead.
- **Use one system prompt across decide+finalize.** If `finalize` uses a different system prompt than `decide`, every finalize call clobbers the KV cache and the *next* decide pays cold prefill (~+0.3s TTFT). Pygentic's `SYSTEM_PROMPT` is intentionally written to cover both turns.
- **Cache the compiled GBNF grammar.** `LlamaGrammar.from_string()` adds 50-200ms per call if you let it recompile. `LlamaCppPythonClient._compile_grammar` caches by grammar string.
- **JSON-wrapping free-text answers is expensive.** Forcing every final answer through `{"final":"..."}` triples generation time for jokes/stories/titles vs plain text. Pygentic v2 could close this gap with a hybrid grammar that allows either a constrained tool-call block or unconstrained free text.
- **TTS audio dominates wall-clock on narration prompts.** `speak_file` on a 4-sentence paragraph takes ~28s regardless of framework — that's the audio playback length, not LLM work.

The latency reports in `latency.jsonl` carry TTFT + total time per stage so you can re-analyze any past run with `bench.py --skip-run` or your own scripts. Each bench run also appends an aggregate to `bench_history.jsonl` at the project root — see [docs/BENCHMARKING.md](docs/BENCHMARKING.md) for how to read trends with `python bench.py --history`.

## Docs

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design, request pipeline, framework differences
- [docs/BENCHMARKING.md](docs/BENCHMARKING.md) — running benchmarks, reading history, regression detection
- [docs/PROJECT.md](docs/PROJECT.md) — high-level project overview
- [docs/SETUP.md](docs/SETUP.md) — install and verification
- [docs/TODO.md](docs/TODO.md) — open work

## License

MIT — see [LICENSE](LICENSE).

---

Built by [Jenkins Robotics](https://www.youtube.com/@Jenkins_Robotics).

[YouTube](https://www.youtube.com/@Jenkins_Robotics) · [Patreon](https://www.patreon.com/JenkinsRobotics) · [Discord](https://discord.gg/sAnE5pRVyT) · [GitHub](https://jenkinsrobotics.github.io)
