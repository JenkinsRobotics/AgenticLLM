"""Hermes — Nous Function-Calling-style agent framework.

Tools are declared as JSON Schema inside <tools></tools> XML tags in the
system prompt. The model emits tool calls as <tool_call>{...}</tool_call>
XML blocks, and tool results are fed back as <tool_response>{...}</tool_response>.
No grammar constraint — Hermes is designed to work with unconstrained decoding.
"""
