# AgenticLLM Project Notes

## Current Goal

Build a fast local agentic LLM loop on macOS: a small local model decides
whether to call a tool, the Python router runs the tool, and the response is
either returned raw (fast mode) or rewritten by the LLM (natural mode). The
focus is minimum decision-to-answer latency.

## Current Entry Points

- `main.py` — headless agentic tool harness (re-execs into `agent_test.main`).

## Headless Agent Test Harness

`agent_test/` is the raw latency benchmark path:

- Gemma 4 24B / 4B-active GGUF
- llama.cpp server
- CLI Python agent
- local Python tool router
- latency report per command

Safe tools currently enabled:

- `get_time`
- `create_file`
- `read_file`
- `list_directory`
- `system_status`

Dangerous tools are intentionally not wired yet:

- `delete_file`
- `run_shell_command`
- `run_python_snippet`

The model only decides which tool to call. The Python router executes tools.
Each command reports decision, tool, final-response, and total latency.

## Local Model

The reference harness is configured for:

- Model file: `gemma-4-26B-A4B-it-Q4_K_M.gguf`
- Backend: `llama-cpp-python` (in-process) or `llama-server` over HTTP
- Expected local path:
  `/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf`

## Notes

- The current script assumes the model already exists at the configured LM Studio path.
- Tool routing is JSON-only; the Python router is the single source of truth for tool execution.
