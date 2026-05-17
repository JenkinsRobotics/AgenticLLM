"""Opt-in extensions for the pydantic_ai agent.

Each plugin is independent — the agent core has no hard dependency on
any of them. Default agent paths pay zero cost; they only load when the
corresponding CLI flag (`--with-mcp`, `--think`) or the messaging gateway
asks for them.

  • mcp_bridge.py / mcp_config.json — MCP server adapter + config
                                       (loaded by `--with-mcp`)
  • thinking_runner.py / thinking.jsonl — background CoT runner + log
                                           (loaded by `--think`)
  • messaging/                         — Discord / Telegram / iMessage
                                          bridges + gateway daemon
                                          (started by `messaging.gateway`)
"""
