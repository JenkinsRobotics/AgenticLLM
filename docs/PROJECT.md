# AgenticLLM Project Notes

High-level overview. For deep technical detail see:

- [ARCHITECTURE.md](ARCHITECTURE.md) — system design, request pipeline, framework differences, key decisions
- [../benchmark/BENCHMARKING.md](../benchmark/BENCHMARKING.md) — how to run benchmarks and read the history log
- [../benchmark/BENCH_RESULTS.md](../benchmark/BENCH_RESULTS.md) — latest tracked numbers per mode + historical consistency view
- [SETUP.md](SETUP.md) — install and verification
- [TODO.md](TODO.md) — open work

## Current goal

Maximize fast local realtime agentic performance on macOS. Two parallel
frameworks (Pygentic and Hermes) run the same Gemma 4 26B-A4B model against
the same 11 sandboxed tools so the trade-offs of prompt design and output
format are measurable head-to-head.

## Entry points

- `main.py` — dispatcher: `python main.py [pygentic|hermes] [prompt]`
- `benchmark/bench.py` — head-to-head benchmark + history log (`bench.py --history`)

## Frameworks

| | Pygentic | Hermes |
|---|---|---|
| Output | Bare JSON | `<tool_call>` XML |
| Decoding | GBNF grammar | Unconstrained |
| Strength | Hard format guarantee, lighter cold prefill | Faster warm decode, clean free-text |

## Tools

11 tools, identical across both frameworks:

`get_time`, `create_file`, `append_file`, `delete_file`, `read_file`,
`list_directory`, `system_status`, `calculate`, `speak` (SSML-aware),
`speak_file`, `web_search`.

All file ops sandboxed inside `<framework>/workspace/`. `speak` and
`speak_file` understand `<break time="200ms"/>` and `<breath/>` for paced
narration without speed cost.

## Local model

- Default file: `gemma-4-26B-A4B-it-Q4_K_M.gguf`
- Backend: `llama-cpp-python` (in-process, default) or `llama-server` over HTTP
- Default path:
  `~/.lmstudio/models/lmstudio-community/gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf`

## Performance tracking

Every request appends to `<framework>/logs/latency.jsonl` with a UTC
`timestamp` and an optional `run_id` (set during bench runs). Bench runs
also append an aggregate per (framework, prompt) to
`benchmark/bench_history.jsonl` so trends are easy to read with
`python benchmark/bench.py --history`.
