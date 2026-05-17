# skills/ — placeholder for v2-contract skill packages

**This directory is empty.** pydantic_ai does NOT have a skill loader
today — its capabilities are exposed as atomic TOOLS in
[`../core/tools/`](../core/tools/), not as skill packages.

The directory exists for **structural parity with python_jaeger**, which
DOES have a skill loader. In jaeger, this same directory holds the
framework's core v2-contract skills (e.g. `example_v1/`), and the agent
can author new skills at runtime into `instance/<name>/skills/`.

## What would live here

If a future pydantic_ai release ships a skill loader (M5+), it would
discover folders under this directory following the v2 contract:

```
skills/<name>_v<N>/
├── SKILL.md
├── <python_module>.py     # exposes register(agent)
└── tests/smoke_test.py
```

For now, treat this folder as reserved. New capabilities should be added
as TOOLS in `../core/tools/` until the skill-loader concept is needed.

See [python_jaeger/skills/](../../python_jaeger/skills/) for a working
example of the skill contract in action.
