# instance/ — where the agent's per-instance state lives

This is the **dev / single-user default** location for instance state.
When you run `python main.py python_jaeger` for the first time, the setup
wizard creates `instance/<instance_name>/` here (default: `instance/default/`).

After the first run you'll see:

```
instance/
└── default/                  ← created by the wizard
    ├── identity.yaml         ← agent name + role + personality (wizard-owned)
    ├── config.yaml           ← model path + display prefs (wizard-owned)
    ├── manifest.json         ← core_version pin
    ├── .lock                 ← exclusive lockfile (active while running)
    ├── credentials/          ← 0600 API keys / tokens (off-limits to agent)
    ├── skills/               ← the AGENT's writable scratchpad
    │   └── <name>_v<N>/      ← skills the agent authors at runtime
    ├── memory/               ← facts.json, episodic.jsonl, schedules.jsonl
    └── logs/                 ← audit.log, latency.jsonl
```

## Why is this inside the framework folder?

Visibility. Putting the dev instance here (vs. `~/.jaeger/`) means everything
the agent reads or writes is one click away in the source tree. Symmetric
with `python_pydantic_ai/workspace/`.

This is the **dev default** — the resolver order is:

1. `JAEGER_INSTANCE_DIR=...` env var (always wins; use for tests / multi-instance)
2. `/var/lib/jaeger/<name>/` when running as root (system service mode)
3. **`python_jaeger/instance/<name>/`** ← here (dev / single-user default)
4. `~/.jaeger/<name>/` fallback when the bundled dir isn't writable
   (e.g. pip-installed inside a system-wide site-packages tree)

## What's the contract with the agent?

The agent can ONLY write to **`<instance>/skills/`**. Everything else
under your instance directory is read-only to the agent (the v2 contract,
enforced by the sandboxed `file_write` tool).

The agent CANNOT touch anything outside its own instance directory —
not `python_jaeger/core/`, not `python_jaeger/skills/` (the core skills
shipped with the framework), not even other instances under
`python_jaeger/instance/`.

## What's the difference between `python_jaeger/skills/` and `python_jaeger/instance/<name>/skills/`?

- **`python_jaeger/skills/`** = **core skills** shipped with the framework.
  Read-only at runtime. Bundled with the install (`hello_v1/`, etc.).
- **`python_jaeger/instance/<name>/skills/`** = the agent's **writable
  scratchpad**. New skills the agent authors land here. On name collision,
  instance skills WIN over core skills (override-via-versioning).

## Cleaning up

Delete `instance/<name>/` to reset that instance. The wizard will recreate
it on next launch.
