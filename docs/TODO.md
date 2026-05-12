# TODO

## Next

- Confirm the Gemma model path on this Mac.
- Start `llama-server` with the Gemma GGUF model and benchmark `main.py`.
- Compare `--mode fast` and `--mode natural` latency for common commands.
- Run real prompts through the grammar-constrained decision path and confirm
  the model emits only valid tool-calls (no parse fallbacks should trigger).
- Add dangerous tools only after safe-tool routing is stable.

## Improvements

- Move configuration values into a single config module.
- Add a lightweight diagnostics command for model availability and server health.
- Add structured logging for decide / tool / finalize stages.

## Risks

- `llama-cpp-python` installation can vary by Mac hardware and compiler setup.
- The hard-coded model path will fail on machines that do not share this exact LM Studio layout.
