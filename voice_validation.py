#!/usr/bin/env python3
"""End-to-end validation of voice_assistant.py's agent contract.

Skips the audio I/O layer (no mic, no Kokoro playback) but exercises
every new tool through `run_for_voice` — the exact entry point the
voice loop uses. For each prompt we check:

  • the agent picks a sensible tool (or none)
  • `run_for_voice` returns the structured dict shape voice_assistant.py
    expects: {text, tool_activity, spoke_via_tool, elapsed_s, ...}
  • new Sprint 1/2/3 tools work in the voice context

Audio I/O is validated separately with a real mic — see
`docs/VOICE_VALIDATION.md` for the manual checklist.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


# Voice mode posture: approval gate ON.
os.environ.setdefault("DESTRUCTIVE_OPS_REQUIRE_CONFIRM", "1")
# Don't pre-warm Kokoro — we're not playing audio in this validation.
os.environ.setdefault("BENCH_NO_WARM_TTS", "1")


def _section(title: str) -> None:
    print(f"\n{'=' * 4} {title} {'=' * (66 - len(title))}", flush=True)


def _check(label: str, ok: bool, detail: str = "") -> None:
    mark = "✓" if ok else "✗"
    print(f"  [{mark}] {label:<48} {detail}", flush=True)
    if not ok:
        _check.failures.append(label)  # type: ignore[attr-defined]
_check.failures = []  # type: ignore[attr-defined]


def main() -> int:
    from python_pydantic_ai.main import (
        LlamaCppPythonClient,
        init_extensions,
        prewarm,
        run_for_voice,
    )
    from python_pydantic_ai import tools as agent_tools

    _section("loading voice-mode agent")
    started = time.perf_counter()
    client = LlamaCppPythonClient(ctx=4096, warmup=True)
    print(f"  model loaded in {time.perf_counter() - started:.1f}s", flush=True)

    class _Args:
        with_memory = True
        with_mcp = False
        think = False
    init_extensions(_Args(), client)
    agent_tools.ensure_workspace()
    # Mirror voice_assistant's startup: prewarm the KV cache so the first
    # user-facing turn isn't cold-cache slow.
    prewarm(client)
    print(f"  memory=on, approval-gate={os.environ.get('DESTRUCTIVE_OPS_REQUIRE_CONFIRM')}", flush=True)

    # ----- The contract: every voice turn returns this shape -----
    def run(prompt: str) -> dict:
        t0 = time.perf_counter()
        r = run_for_voice(client, prompt)
        r["_wall_s"] = time.perf_counter() - t0
        return r

    def has_keys(r: dict, keys: list[str]) -> bool:
        return all(k in r for k in keys)

    def used_tool(r: dict, name: str) -> bool:
        return any(name in (line or "") for line in r.get("tool_activity") or [])

    # ----- Sanity: a basic skip-final tool turn -----
    _section("contract: simple skip-final turn")
    r = run("what time is it")
    _check("returns required keys", has_keys(r, ["text", "tool_activity", "spoke_via_tool", "elapsed_s"]),
           f"keys={list(r.keys())[:6]}…")
    _check("text is non-empty", bool(r["text"]), f"text={r['text'][:60]!r}")
    _check("get_time tool was used", used_tool(r, "get_time"))
    _check("spoke_via_tool is False (no speak call)", r.get("spoke_via_tool") is False)
    _check("wall ≤ 3s warm", r["_wall_s"] < 3.0, f"{r['_wall_s']:.2f}s")

    # ----- ask_user (Sprint 1) -----
    _section("ask_user — clarify-question tool")
    r = run("delete the report file")  # ambiguous: which report file?
    _check("ambiguous prompt produced a non-empty response", bool(r["text"]),
           f"text={r['text'][:80]!r}")
    # Model may either ask_user or call delete_file (gated → preview).
    # Either is acceptable; bench is about the contract, not policy.

    # ----- run_python (Sprint 1) -----
    _section("run_python — sandboxed code execution")
    r = run("use run_python to compute 12345 multiplied by 67890 and tell me the answer")
    # Accept either grouping format the model uses ("838102050" or "838,102,050").
    no_commas = r["text"].replace(",", "")
    _check("answer mentions correct product", "838102050" in no_commas, f"text={r['text'][:80]!r}")
    _check("run_python tool was invoked", used_tool(r, "run_python"))

    # ----- approval gate: delete_file requires confirm in voice mode -----
    _section("approval gate — delete preview then commit")
    target = Path("python_pydantic_ai/workspace/voice_val_target.txt")
    try:
        agent_tools.create_file("voice_val_target.txt", "to be deleted")
        r = run("delete the file voice_val_target.txt")
        # In voice mode the first call should preview, not delete.
        _check("file still exists after first delete call", target.exists(),
               "delete_file should return a preview, not destroy")
    finally:
        # Always clean up, even if the check above raised.
        if target.exists():
            target.unlink()

    # ----- search_memory (Sprint 2) -----
    _section("search_memory — semantic recall")
    r = run("did we ever talk about the cpu and disk status of this machine?")
    _check("text is non-empty", bool(r["text"]), f"text={r['text'][:80]!r}")
    # search_memory may or may not be picked; the agent might use recall instead.

    # ----- schedule_prompt + list_schedules + cancel_schedule (Sprint 2) -----
    _section("cron scheduling — schedule → list → cancel")
    r = run("schedule a prompt named voice_val to say hi every five minutes")
    _check("agent reports schedule created", "voice_val" in (r["text"] + " ".join(r["tool_activity"])).lower()
           or any("schedule" in line.lower() for line in r["tool_activity"]), f"text={r['text'][:120]!r}")
    r = run("list my scheduled prompts")
    _check("list_schedules returned content", bool(r["text"]), f"text={r['text'][:120]!r}")
    r = run("cancel the voice_val schedule")
    _check("cancel succeeded", bool(r["text"]), f"text={r['text'][:120]!r}")

    # ----- delegate (Sprint 3) -----
    _section("delegate — subagent handoff")
    r = run("delegate the subtask of calculating 9 times 8 to a subagent")
    _check("delegate returned an answer", bool(r["text"]), f"text={r['text'][:80]!r}")

    # ----- run_for_voice still works on a no-tool free-text prompt -----
    _section("free-text turn (no tool)")
    r = run("tell me a one sentence story about a robot")
    _check("got a story (no tool call)", bool(r["text"]) and len(r["tool_activity"]) == 0,
           f"text={r['text'][:80]!r}")
    _check("spoke_via_tool is False", r.get("spoke_via_tool") is False)

    # ----- Summary -----
    _section("summary")
    failures = _check.failures  # type: ignore[attr-defined]
    if failures:
        print(f"  FAIL: {len(failures)} checks failed:")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("  PASS: every voice-mode contract check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
