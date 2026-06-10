# example_v1

## What
The canonical reference skill that ships with Jaeger. Exposes a single tool
`say_example_greeting(name)` that returns a greeting dict. Its only purpose
is to demonstrate the skill contract end-to-end (SKILL.md + module +
smoke test) so humans AND the agent have a working template to copy.

## When
**Never trigger this for real work** — it's a reference, not a production
capability. Copy this folder as a starting point when authoring a new
skill (rename, replace `say_example` with your real logic, update this
SKILL.md, write a real smoke test).

## How
Tool signature: `say_example_greeting(name: str) -> dict`.
Returns: `{"greeting": "Hello, <name>!", "skill": "example_v1"}`.

## Depends on
Nothing. No external libraries, no other skills, no file system access.
