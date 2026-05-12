# TODO

## Next

- Confirm the Gemma model path on this Mac.
- Start `llama-server` with the Gemma GGUF model and benchmark `main.py`.
- Compare `--mode fast` and `--mode natural` latency for common commands.
- Add TTFT (time-to-first-token) to the latency report.
- Try a smaller decision model (e.g. Qwen2.5-3B or Llama-3.2-3B) and compare routing accuracy.
- Add GBNF / JSON-schema grammar to the decision step so the parser can be deleted.
- Add dangerous tools only after safe-tool routing is stable.

## Improvements

- Move configuration values into a single config module.
- Add a lightweight diagnostics command for model availability and server health.
- Add structured logging for decide / tool / finalize stages.

## Risks

- `llama-cpp-python` installation can vary by Mac hardware and compiler setup.
- The hard-coded model path will fail on machines that do not share this exact LM Studio layout.
