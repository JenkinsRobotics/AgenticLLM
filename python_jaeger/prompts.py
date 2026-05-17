"""System-prompt assembly for Jaeger.

Layered, in this order, so the result is deterministic at startup:

  [identity blurb from identity.yaml]
  [MANDATORY TOOL RULES — short, near the top, so a small local model
   doesn't gloss past them]
  [v2 self-improvement contract from prompts/agent_system_prompt.md]
  [runtime hints: workspace path, tool surface notes]

The mandatory-rules block is short and imperative on purpose. Shakedown
runs against Gemma 4 26B-A4B showed the model would acknowledge a
"remember that…" request in free-text without ever calling `remember`,
because the equivalent guidance was buried near the bottom of a long
system prompt. Putting the rules right after the identity blurb fixes it.

Nothing here ever edits identity.yaml — the wizard owns it.
"""

from __future__ import annotations

from pathlib import Path

from .instance import InstanceLayout


CORE_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "agent_system_prompt.md"


MANDATORY_TOOL_RULES = """\
Mandatory tool rules — these are not suggestions:

1. PERSISTING FACTS. If the user states a preference, identity fact, plan,
   or anything they might want recalled later ("remember that…", "my
   favorite X is…", "I'm allergic to…", "I'll be in town on…"), you MUST
   call `remember(key, value)`. Acknowledging in free-text ("OK, I'll
   remember") without calling the tool is forbidden — it is lying.

2. RECALLING FACTS. If the user asks about something they told you in any
   prior turn or session ("what did I say my…", "do you remember…",
   "what's my favorite X?"), you MUST call `recall(key)` or `list_facts()`
   BEFORE answering. The persisted store is the source of truth across
   sessions; short-term context is not.

3. CREDENTIALS. NEVER read files under `credentials/`. Use
   `get_credential(name)` to fetch a value, `list_credentials()` to see
   what exists. Once you hold a credential value, use it in a tool call
   but NEVER echo it back to the user in your reply.

4. SAFETY-GATED PATHS. Writes are restricted to `skills/`. Identity,
   config, manifest, memory, logs are off-limits. If you want to change
   any of those, surface it to the human instead.
"""


RUNTIME_TAIL = """\
Runtime hints:
- Your writable workspace is your instance's `skills/` directory. Use
  `file_write(path, content)` and `file_read(path)` to author skills.
- After authoring or modifying skill files, call `reload_skills()` so the
  loader registers your new code; otherwise you can't call what you just
  wrote until the next restart.
- Always answer with the SHORTEST useful reply. Bare facts only; never
  restate the question or add filler.
"""


def build_system_prompt(layout: InstanceLayout) -> str:
    parts: list[str] = []
    try:
        from . import memory as mem
        ident_blurb = mem.load_identity_string(layout)
    except Exception:
        ident_blurb = ""
    if ident_blurb:
        parts.append(ident_blurb)

    parts.append(MANDATORY_TOOL_RULES.strip())

    if CORE_PROMPT_PATH.exists():
        parts.append(CORE_PROMPT_PATH.read_text(encoding="utf-8").strip())

    parts.append(RUNTIME_TAIL.strip())
    return "\n\n".join(parts)
