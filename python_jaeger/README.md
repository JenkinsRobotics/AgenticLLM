# python_jaeger — self-improving local agent framework

Jaeger is a Pydantic-AI-based agent that can extend its own capabilities
by writing new skill files at runtime, with a hard safety boundary
between framework code (read-only) and agent state (writable).

## Directory tour

```
python_jaeger/
├── README.md            ← you are here
├── main.py              ← CLI entry point (`python main.py python_jaeger`)
│
├── agent/               ← THE CONSCIOUS NODE — everything cognitive
│   ├── tools/             built-in agent tools (file_write/read, get_time, …)
│   ├── skills/            core skills shipped with the framework (read-only)
│   ├── skill_registry/    discover + register skills (core + instance)
│   ├── prompts/           system-prompt assembler
│   ├── prompt_assets/     raw prompt markdown (system prompt body)
│   ├── runners/           ThinkingRunner (deep-think loop)
│   └── background/        cron schedule firing + daily housekeeping
│
├── core/                ← SHARED INFRASTRUCTURE — used by everything
│   ├── instance.py        path resolution, lockfile, manifest gate
│   ├── schemas.py         Pydantic v2 schemas (identity, config, manifest)
│   ├── setup_wizard.py    first-run flow (interactive)
│   ├── credentials.py     get_credential + 0600 perm enforcement
│   ├── memory.py          per-instance facts / episodic / schedules I/O
│   ├── log_rotation.py    daily rotation + retention enforcement
│   ├── migrations.py      discover + apply per-version migrations
│   ├── llm_model.py       in-process Gemma adapter for pydantic-ai
│   └── audio/             AEC wrapper + reference buffer
│
├── plugins/             ← OPT-IN EXTENSIONS (voice loop, kokoro, whisper,
│                          discord, telegram, imessage, mcp)
│
├── migrations/     ← per-version migration scripts (paired with core/migrations.py)
│
└── instance/            ← AGENT-WRITABLE state (created by the wizard)
    ├── .gitignore         keeps user state out of the repo
    ├── README.md          explains what lives under each instance
    └── <name>/            one dir per instance (default: `default/`)
        ├── identity.yaml      wizard-owned
        ├── config.yaml        wizard-owned
        ├── manifest.json      core_version pin
        ├── credentials/       0600 secrets (off-limits to agent)
        ├── skills/            agent's writable scratchpad
        ├── memory/            facts.json, episodic.jsonl, schedules.jsonl
        └── logs/              audit.log, latency.jsonl
```

## The safety boundary

There are TWO zones, and the framework enforces a hard line between them:

**Read-only to the agent** (everything in `python_jaeger/` except `instance/<name>/skills/`):
- All of `agent/`, `core/`, `plugins/`, `migrations/`
- Everything in `instance/<name>/` EXCEPT the `skills/` subfolder
- `credentials/` is doubly protected — the sandboxed `file_read` tool
  refuses to read it; the agent must use `get_credential(name)` instead

**Writable by the agent** (its only writable zone):
- `instance/<name>/skills/` — where the agent authors new skill folders
  via the sandboxed `file_write` tool

The `file_write` tool resolves every path relative to `<instance>/skills/`,
rejects absolute paths and `..` escapes, and refuses any write that lands
outside the sandbox. See `agent/tools/` for the implementation.

## Skills: core vs instance

Two distinct kinds, both follow the same `<name>_v<N>/` versioned-folder
contract with `SKILL.md` + Python module + `tests/smoke_test.py`:

- **Core skills** (`python_jaeger/agent/skills/`) ship with the framework. Read-only.
- **Instance skills** (`<instance>/skills/`) are agent-authored. Writable.

On name collision, **instance wins over core** (override-via-versioning).
Within a zone, the highest `_v<N>` suffix wins. See `agent/skill_registry/skill_loader.py`.

## Where the instance lives

The setup wizard creates the instance dir on first launch. Resolution
order (highest priority first):

1. `JAEGER_INSTANCE_DIR=/some/path` env var — explicit override (always wins)
2. `/var/lib/jaeger/<name>/` — when running as root (system service mode)
3. **`python_jaeger/instance/<name>/`** ← **default for dev / single-user**
4. `~/.jaeger/<name>/` — fallback when the bundled dir isn't writable
   (e.g. pip-installed in a system-wide site-packages tree)

The dev default lives inside the framework dir so you can SEE the agent's
state in your source tree. This is intentional and safe — the framework
dir is read-only to the agent (the v2 contract), so co-locating doesn't
weaken the safety boundary.

## Running

```bash
python main.py python_jaeger              # first run triggers the wizard, then chat loop
python main.py python_jaeger --self-test  # exercises sandbox + memory + skill loader (no LLM)
python main.py python_jaeger --setup      # re-run the wizard (backs up existing instance)
python main.py python_jaeger --migrate    # apply pending migrations and exit
python main.py python_jaeger --set-credential telegram_bot_token   # stdin / getpass
python main.py python_jaeger --list-credentials                    # names only

JAEGER_INSTANCE_DIR=/tmp/test_instance python main.py python_jaeger   # custom location
```

See `agent/prompt_assets/agent_system_prompt.md` for the v2 self-improvement contract
the agent operates under.
