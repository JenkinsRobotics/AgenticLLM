# hello_v1

## What
A trivial reference skill. Exposes a single tool `say_hello(name)` that
returns a greeting. Its only purpose is to demonstrate the skill contract
end-to-end (SKILL.md, module with `register(agent)`, smoke test).

## When
Never trigger this for real work — it's a reference. Use it as a
template when building new skills.

## How
Tool signature: `say_hello(name: str) -> dict`. Returns `{"greeting": str, "skill": "hello_v1"}`.

## Depends on
Nothing. No external libraries, no other skills, no file system access.
