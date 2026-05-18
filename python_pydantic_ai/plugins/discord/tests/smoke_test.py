"""Smoke test for the discord plugin. Confirms importability without
discord.py installed."""

from __future__ import annotations


def test_bridge_importable() -> None:
    from python_pydantic_ai.plugins.discord import DiscordBridge

    assert DiscordBridge is not None


if __name__ == "__main__":
    test_bridge_importable()
    print("discord plugin smoke: OK")
