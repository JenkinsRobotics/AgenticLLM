"""System-prompt assembly for Jaeger.

Layered, in this order, so the result is deterministic at startup:

  [identity blurb from identity.yaml]
  [MANDATORY TOOL RULES — short, near the top, so a small local model
   doesn't gloss past them]
  [v2 self-improvement contract — OFF by default, gated behind
   skills.include_self_improvement_contract in the instance config]
  [runtime hints: workspace path, tool surface notes]

Mirrors python_pydantic_ai/core/prompts.py — four MANDATORY rules
(persist / recall / forget / narrate-files) plus a short runtime tail.
Larger surfaces (math, file delete, etc.) ride on tool docstrings, which
already say "MANDATORY for ANY ...". Bench data on Gemma 4 26B-A4B
showed that piling extra rules into the prompt actually hurt routing —
larger context dilutes the imperatives that get most attention.

The 115-line v2 self-improvement contract used to load every turn. It's
load-bearing when the agent is authoring skills (versioning, rollback,
smoke tests) but adds ~900 words otherwise and was costing 3/23 on the
routing bench. Now opt-in via the config flag.

Nothing here ever edits identity.yaml — the wizard owns it.
"""

from __future__ import annotations

from pathlib import Path

from python_jaeger.core.instance import InstanceLayout


# core/ lives one level deeper than the framework root, so reach up one.
CORE_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "agent_system_prompt.md"


MANDATORY_TOOL_RULES = """\
Mandatory tool rules — these are not suggestions:

1. PERSISTING FACTS. If the user states a preference, identity fact,
   plan, or anything they might want recalled later ("remember that…",
   "my favorite X is…", "I'm allergic to…", "I'll be in town on…"),
   you MUST call `remember(key, value)`. Acknowledging in free-text
   ("OK, I'll remember") without calling the tool is forbidden — it is
   lying.

2. RECALLING FACTS. If the user asks about something they told you in
   any prior turn or session ("what did I say my…", "do you remember…",
   "what's my favorite X?", "what video length do I prefer?"), you MUST
   call `recall(key)` or `list_facts()` BEFORE answering. The persisted
   store is the source of truth across sessions; short-term conversation
   context is not. Fall back to `search_memory` only if both miss.

3. FORGETTING FACTS. "Forget my X", "remove my X preference", "I changed
   my mind about X" all require calling `forget(key)`. Don't free-text
   acknowledge.

4. NARRATING FILES. "Read X out loud", "narrate X", "speak X as if for a
   video" with a NAMED FILE means: call `speak_file(path)`, not `speak`.
   Use `speak(text)` only when the user gives you literal text to say
   that isn't in a file.
"""


RUNTIME_TAIL = """\
The only writable area is the sandboxed `skills/` directory of your
instance. All "path" arguments to file tools are relative to that root.
Do NOT prefix paths with "skills/", "~", or any absolute path. If the
user asks to save somewhere else (Desktop, Downloads, etc.), still save
to skills/ and explain where it actually went.

Behavior:
- Use tools to fulfill requests. Each tool has a typed signature; pass
  arguments that match.
- If the user asks for something none of your tools can do, say so
  honestly in plain text — don't invent a tool error or pretend a tool
  ran when it didn't.
- After a tool returns, decide whether the user's request is fully
  answered. If yes, write the SHORTEST possible reply — often just one
  sentence, sometimes just the value. Never restate the question. Bare
  facts only.
- If the user explicitly asked for a follow-up action ("and speak it",
  "then save it"), call the next tool.
- After authoring or modifying skill files, call `reload_skills()` so
  the loader registers your new code.
"""


def build_system_prompt(layout: InstanceLayout) -> str:
    """Assemble the agent's system prompt.

    Default is lean — identity + 4 MANDATORY rules + runtime tail. The
    115-line v2 self-improvement contract is OFF by default because it
    tripled prompt size and was diluting routing accuracy on Gemma 4 in
    benchmarks. Flip `skills.include_self_improvement_contract: true` in
    the instance config when the agent is actively authoring skills.
    """
    parts: list[str] = []
    try:
        from . import memory as mem
        ident_blurb = mem.load_identity_string(layout)
    except Exception:
        ident_blurb = ""
    if ident_blurb:
        parts.append(ident_blurb)

    parts.append(MANDATORY_TOOL_RULES.strip())

    include_v2 = False
    try:
        from .schemas import Config, load_yaml
        cfg = load_yaml(layout.config_path, Config)
        include_v2 = cfg.skills.include_self_improvement_contract
    except Exception:
        include_v2 = False

    if include_v2 and CORE_PROMPT_PATH.exists():
        parts.append(CORE_PROMPT_PATH.read_text(encoding="utf-8").strip())

    parts.append(RUNTIME_TAIL.strip())
    return "\n\n".join(parts)
