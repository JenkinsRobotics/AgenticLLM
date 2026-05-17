"""User-facing configuration + first-run setup wizard.

One JSON file (memory/config.json) holds everything an end user might
want to flip without editing code: agent name, persona blurb, latency-
report visibility, and credentials for the messaging bridges. The wizard
is interactive (run via `python -m memory.config --setup` or auto-triggered
by main.py / messaging.gateway when no config exists).

The file is human-editable. Credentials are applied to os.environ so the
existing telegram_bridge / discord_bridge / imessage_bridge code keeps
working unchanged — they just stop needing the user to remember to export
env vars before launch.

Layout:
    {
      "schema_version": 1,
      "agent": {"name": "Lilith", "personality": "...", "voice_tone": "..."},
      "display": {"show_latency": false, "show_tool_activity": true},
      "telegram": {"enabled": false, "bot_token": "...", "allowed_chat_ids": [...]},
      "discord":  {"enabled": false, "bot_token": "...", "allowed_user_ids": [...]},
      "imessage": {"enabled": false, "allowed_handles": [...]}
    }
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
IDENTITY_PATH = ROOT / "identity.md"

SCHEMA_VERSION = 1

_DEFAULTS: dict[str, Any] = {
    "schema_version": SCHEMA_VERSION,
    "agent": {
        "name": "Lilith",
        "personality": (
            "Concise and direct. No filler. Confident on facts; honest "
            "about uncertainty. A touch of dry humor when it fits."
        ),
        "voice_tone": "neutral",
    },
    "display": {
        "show_latency": False,
        "show_tool_activity": True,
        "show_help_on_start": True,
    },
    "telegram": {"enabled": False, "bot_token": "", "allowed_chat_ids": []},
    "discord":  {"enabled": False, "bot_token": "", "allowed_user_ids": []},
    "imessage": {"enabled": False, "allowed_handles": []},
}


def _merge(into: dict[str, Any], src: dict[str, Any]) -> dict[str, Any]:
    """Recursive defaults-merge so newly-added keys appear without wiping user values."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(into.get(k), dict):
            _merge(into[k], v)
        elif k not in into:
            into[k] = v
    return into


def load() -> dict[str, Any]:
    """Read config.json (filling in defaults for any missing keys)."""
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _merge(data, _DEFAULTS)
        except (json.JSONDecodeError, OSError):
            pass
    return json.loads(json.dumps(_DEFAULTS))  # deep copy


def save(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg = dict(cfg)
    cfg["schema_version"] = SCHEMA_VERSION
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)


def exists() -> bool:
    return CONFIG_PATH.exists()


def apply_to_environ(cfg: dict[str, Any] | None = None) -> None:
    """Push enabled bridge credentials into os.environ.

    Existing env vars win (so you can still override with a one-shot
    `TELEGRAM_BOT_TOKEN=... python ...` invocation). Only enabled bridges
    contribute — disabling a bridge in config.json keeps its token out of
    the process even if the JSON still has it.
    """
    cfg = cfg or load()
    tg = cfg.get("telegram") or {}
    if tg.get("enabled"):
        if tg.get("bot_token") and not os.environ.get("TELEGRAM_BOT_TOKEN"):
            os.environ["TELEGRAM_BOT_TOKEN"] = tg["bot_token"]
        ids = tg.get("allowed_chat_ids") or []
        if ids and not os.environ.get("TELEGRAM_ALLOWED_CHAT_IDS"):
            os.environ["TELEGRAM_ALLOWED_CHAT_IDS"] = ",".join(str(x) for x in ids)
    dc = cfg.get("discord") or {}
    if dc.get("enabled"):
        if dc.get("bot_token") and not os.environ.get("DISCORD_BOT_TOKEN"):
            os.environ["DISCORD_BOT_TOKEN"] = dc["bot_token"]
        ids = dc.get("allowed_user_ids") or []
        if ids and not os.environ.get("DISCORD_ALLOWED_USER_IDS"):
            os.environ["DISCORD_ALLOWED_USER_IDS"] = ",".join(str(x) for x in ids)
    im = cfg.get("imessage") or {}
    if im.get("enabled"):
        handles = im.get("allowed_handles") or []
        if handles and not os.environ.get("IMESSAGE_ALLOWED_HANDLES"):
            os.environ["IMESSAGE_ALLOWED_HANDLES"] = ",".join(handles)


def update_identity_from_config(cfg: dict[str, Any] | None = None) -> None:
    """Rewrite memory/identity.md so the system prompt picks up the chosen
    name + personality on the next agent build."""
    cfg = cfg or load()
    agent = cfg.get("agent") or {}
    name = (agent.get("name") or "Lilith").strip() or "Lilith"
    personality = (agent.get("personality") or "").strip()

    content = (
        "# Persistent identity\n\n"
        f"You are {name} — the same {name} across every interface: chat, voice,\n"
        "background agents, Discord/Telegram/iMessage bots. Your identity\n"
        "persists across sessions and processes via this file.\n\n"
    )
    if personality:
        content += f"Voice: {personality}\n\n"
    content += (
        "Memory tools (always available):\n"
        "- `remember(key, value)` — save a fact the user shares.\n"
        "- `recall(key)` — fetch a previously saved fact.\n"
        "- `list_facts` — list everything you currently know.\n"
        "- `forget(key)` — remove a stored fact.\n\n"
        "Behavior: when the user shares a preference or fact worth keeping,\n"
        "call `remember` proactively. When the user asks something whose\n"
        "answer depends on prior context, check `recall` or `list_facts` first.\n"
    )
    IDENTITY_PATH.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Interactive setup wizard
# ---------------------------------------------------------------------------
def _prompt(label: str, default: str = "", *, secret: bool = False) -> str:
    suffix = f" [{default}]" if default and not secret else ""
    if secret:
        try:
            import getpass
            value = getpass.getpass(f"{label}{suffix}: ").strip()
        except Exception:
            value = input(f"{label}{suffix}: ").strip()
    else:
        value = input(f"{label}{suffix}: ").strip()
    return value or default


def _prompt_yn(label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = input(f"{label} ({hint}): ").strip().lower()
    if not raw:
        return default
    return raw[0] == "y"


def _prompt_csv_ints(label: str, default: list[int]) -> list[int]:
    placeholder = ",".join(str(x) for x in default) if default else ""
    raw = _prompt(label, placeholder)
    if not raw:
        return default
    out: list[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            print(f"  (ignoring non-numeric id: {tok!r})")
    return out


def _prompt_csv_strs(label: str, default: list[str]) -> list[str]:
    placeholder = ",".join(default) if default else ""
    raw = _prompt(label, placeholder)
    if not raw:
        return default
    return [t.strip() for t in raw.split(",") if t.strip()]


def run_wizard(*, force: bool = False) -> dict[str, Any]:
    """Interactive setup. Returns the final config dict (also persisted)."""
    existing = load() if (CONFIG_PATH.exists() and not force) else json.loads(json.dumps(_DEFAULTS))

    print()
    print("──────────────────────────────────────────────")
    print("  AgenticLLM — first-time setup")
    print("──────────────────────────────────────────────")
    print("  Press Enter at any prompt to accept the default in [brackets].")
    print("  Pick 'n' on any section to skip it; you can re-run with `--setup` later.")
    print()

    # --- Agent identity --------------------------------------------------
    print("[1/5] Agent identity")
    agent = existing.get("agent") or {}
    name = _prompt("  Name", agent.get("name", "Lilith"))
    personality = _prompt(
        "  Personality / voice (one sentence)",
        agent.get("personality", _DEFAULTS["agent"]["personality"]),
    )
    voice_tone = _prompt("  Voice tone tag", agent.get("voice_tone", "neutral"))
    existing["agent"] = {"name": name, "personality": personality, "voice_tone": voice_tone}
    print()

    # --- Display ---------------------------------------------------------
    print("[2/5] Display preferences")
    disp = existing.get("display") or {}
    show_latency = _prompt_yn("  Show per-turn latency breakdown?", disp.get("show_latency", False))
    show_activity = _prompt_yn("  Show tool-activity lines?", disp.get("show_tool_activity", True))
    show_help = _prompt_yn("  Show the help banner on startup?", disp.get("show_help_on_start", True))
    existing["display"] = {
        "show_latency": show_latency,
        "show_tool_activity": show_activity,
        "show_help_on_start": show_help,
    }
    print()

    # --- Telegram --------------------------------------------------------
    print("[3/5] Telegram bot (skip if you don't want one)")
    tg = existing.get("telegram") or {}
    if _prompt_yn("  Set up Telegram now?", tg.get("enabled", False)):
        print("  Create a bot by messaging @BotFather on Telegram (/newbot).")
        print("  Then find your numeric chat ID via @userinfobot.")
        token = _prompt("  Bot token", tg.get("bot_token", ""), secret=True)
        chat_ids = _prompt_csv_ints(
            "  Allowed chat IDs (comma-separated; empty = open)",
            tg.get("allowed_chat_ids", []),
        )
        existing["telegram"] = {
            "enabled": bool(token),
            "bot_token": token,
            "allowed_chat_ids": chat_ids,
        }
    else:
        existing["telegram"] = {**tg, "enabled": False}
    print()

    # --- Discord ---------------------------------------------------------
    print("[4/5] Discord bot (skip if you don't want one)")
    dc = existing.get("discord") or {}
    if _prompt_yn("  Set up Discord now?", dc.get("enabled", False)):
        print("  Create a bot at https://discord.com/developers/applications")
        print("  (enable Message Content intent in the Bot panel).")
        token = _prompt("  Bot token", dc.get("bot_token", ""), secret=True)
        user_ids = _prompt_csv_ints(
            "  Allowed user IDs (comma-separated; empty = open)",
            dc.get("allowed_user_ids", []),
        )
        existing["discord"] = {
            "enabled": bool(token),
            "bot_token": token,
            "allowed_user_ids": user_ids,
        }
    else:
        existing["discord"] = {**dc, "enabled": False}
    print()

    # --- iMessage --------------------------------------------------------
    print("[5/5] iMessage (macOS only; needs Full Disk Access)")
    im = existing.get("imessage") or {}
    if sys.platform == "darwin" and _prompt_yn("  Set up iMessage now?", im.get("enabled", False)):
        handles = _prompt_csv_strs(
            "  Allowed handles (phone numbers, Apple ID emails; comma-separated)",
            im.get("allowed_handles", []),
        )
        existing["imessage"] = {"enabled": bool(handles), "allowed_handles": handles}
    else:
        existing["imessage"] = {**im, "enabled": False}
    print()

    save(existing)
    update_identity_from_config(existing)
    apply_to_environ(existing)
    print(f"✓ Saved configuration to {CONFIG_PATH}")
    print(f"✓ Updated {IDENTITY_PATH.name} with your agent persona")
    print()
    return existing


def ensure_configured(*, prompt_if_missing: bool = True) -> dict[str, Any]:
    """Public entrypoint used by main.py / messaging.gateway at startup.

    If config.json exists, just load + push env vars and return. Otherwise
    run the wizard (or skip silently with defaults when prompt_if_missing
    is False, e.g. non-interactive runs)."""
    if CONFIG_PATH.exists():
        cfg = load()
        apply_to_environ(cfg)
        return cfg

    if not prompt_if_missing or not sys.stdin.isatty():
        cfg = load()  # defaults
        save(cfg)     # persist so we don't re-prompt next run
        apply_to_environ(cfg)
        return cfg

    cfg = run_wizard()
    return cfg


def main() -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--setup", action="store_true", help="Run (or re-run) the interactive wizard.")
    p.add_argument("--show", action="store_true", help="Print the current configuration.")
    args = p.parse_args()

    if args.show:
        print(json.dumps(load(), indent=2, ensure_ascii=False))
        return 0
    if args.setup or not CONFIG_PATH.exists():
        run_wizard(force=args.setup)
        return 0
    print(f"config.json already exists at {CONFIG_PATH} — pass --setup to re-run the wizard.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
