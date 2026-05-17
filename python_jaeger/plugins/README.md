# plugins/ — opt-in extensions

Empty in M1–M3. Reserved for opt-in extensions that the agent core has no
hard dependency on. Mirrors `python_pydantic_ai/plugins/` for visual
parity across frameworks.

A plugin should:
- Be importable as `python_jaeger.plugins.<name>` (so it's loaded only
  when explicitly asked for).
- Either expose its own tools through the skill loader, OR get wired up
  by a CLI flag inside `python_jaeger/main.py` (e.g. `--with-mcp`).
- Pay zero cost when not loaded (don't import heavy deps at module level).

Candidates worth adding here in M4+:
- `mcp_bridge.py` + `mcp_config.json` — MCP server adapter
- `messaging/` — Discord / Telegram / iMessage bridges, mirroring
  `python_pydantic_ai/plugins/messaging/`
- `voice/` — STT + TTS for a voice loop
