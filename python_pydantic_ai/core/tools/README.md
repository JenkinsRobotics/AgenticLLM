# core/tools/ — built-in tools (atomic functions, organized by category)

This is the framework's primitive tool surface. **Tools are individual
Python functions**, grouped into category files (one `.py` per category)
and registered onto the agent via `@agent.tool_plain` from main.py.

This is intentionally NOT a "skills" folder. Skills (the v2-contract
versioned-folder kind) are a higher-order concept; see
[`../../skills/`](../../skills/) for that.

## How to add a new tool

Add a function to the appropriate category file:

```python
# core/tools/web.py
def my_new_tool(arg: str) -> dict[str, Any]:
    """Short one-line docstring — this is what the LLM sees."""
    ...
    return {"result": ...}
```

Re-export it from [`__init__.py`](__init__.py), then wire it onto the
agent in `python_pydantic_ai/main.py`:

```python
@agent.tool_plain
def my_new_tool(arg: str) -> dict:
    """Same docstring — the LLM sees THIS one."""
    return tools.my_new_tool(arg=arg)
```

If the result dict IS the user-facing answer (skip the final LLM
rewrite), add the tool name to `SKIP_FINAL_TOOLS` in main.py and
provide a one-line formatter in `_format_tool_result_as_answer`.

## Category files

| file | tools |
|---|---|
| `_common.py` | shared infra: `WORKSPACE`, `workspace_path`, destructive-op gate |
| `time_and_math.py` | `get_time`, `calculate`, `system_status` |
| `files.py` | `create_file`, `append_file`, `delete_file`, `read_file`, `list_directory`, `launch_url`, `open_file`, `open_app` |
| `memory.py` | `remember`, `recall`, `forget`, `list_facts`, `search_memory` |
| `scheduling.py` | `schedule_prompt`, `list_schedules`, `cancel_schedule` |
| `web.py` | `web_search`, `get_weather` |
| `code.py` | `run_python` (sandboxed subprocess) |
| `speak.py` | `speak`, `speak_file`, `warm_kokoro` (Kokoro TTS) |
| `vision.py` | `look_at`, `generate_image` (Moondream2 + SDXL-Turbo) |
| `messaging.py` | `send_message` (routes to plugins/messaging bridges) |
| `delegation.py` | `ask_user`, `help_me` |

Plus `delegate` lives in `main.py` (needs recursion access).

## Tools vs. Skills

| | Tools (here) | Skills (`../../skills/`) |
|---|---|---|
| Shape | One `def` in a category `.py` file | A folder `<name>_v<N>/` with `SKILL.md` + module + smoke test |
| Granularity | Atomic primitive | Higher-order package |
| Who writes them | Framework maintainers | (pydantic_ai has no skill loader yet; placeholder for parity with jaeger) |

Rule of thumb: if it's a single short Python function with one clear
purpose, it's a tool. Skills are for composable, versioned, replaceable
capability packages.
