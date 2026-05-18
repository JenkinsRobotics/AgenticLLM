"""Smoke test for the mcp plugin. Confirms the client module imports
cleanly and finds its config file."""

from __future__ import annotations


def test_client_importable() -> None:
    from python_pydantic_ai.plugins.mcp import client

    assert hasattr(client, "init_from_config")
    assert hasattr(client, "MCPRegistry")
    assert hasattr(client, "call_mcp_tool")


def test_default_config_path_resolves() -> None:
    from python_pydantic_ai.plugins.mcp import client

    assert client.DEFAULT_CONFIG_PATH.exists()
    assert client.DEFAULT_CONFIG_PATH.name == "mcp_config.json"


if __name__ == "__main__":
    test_client_importable()
    test_default_config_path_resolves()
    print("mcp plugin smoke: OK")
