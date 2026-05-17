# Benchmarking and performance tracking

The repo tracks performance over time so regressions and improvements are
visible at a glance. Every benchmark run is tagged with a `run_id` (UTC
timestamp), and the aggregate appends to `bench_history.jsonl` at the project
root. `bench.py --history` reads that file and prints a trend view.

## Running a bench

```bash
.venv/bin/python bench.py                       # default mode (15 prompts, no extensions)
.venv/bin/python bench.py --with-mcp            # adds MCP-flavored prompts; tags entries mode_tag=mcp
.venv/bin/python bench.py --think               # background thinking enabled; tags entries mode_tag=think
.venv/bin/python bench.py --only python_custom_json       # just one framework
.venv/bin/python bench.py --prompts file.txt    # custom prompts (one per line)
.venv/bin/python bench.py --skip-run            # re-summarize existing logs
```

Each bench-history entry carries a `mode_tag` (`default` / `mcp` / `think` /
`mcp+think`) so the trend view lets you compare modes side by side. The
extension flags map to env vars (`BENCH_WITH_MCP=1`, `BENCH_WITH_THINKING=1`)
that the framework's `init_from_env()` reads when bench.py imports
`run_command` directly.

Each run:

1. Loads each chosen framework's model once
2. Runs every prompt with `--mode auto`
3. Appends per-call entries to `<framework>/logs/latency.jsonl`
4. Appends aggregate entries to `bench_history.jsonl` (one per prompt × framework)
5. Prints a side-by-side comparison table

Two prompts in the default set play audio out loud (~28 s each). Skip them
with a custom prompt file if you don't want TTS during timing.

## Tracked results table

Current numbers (latest run per mode, plus historical consistency view) live in
[BENCH_RESULTS.md](BENCH_RESULTS.md). After running a new bench, regenerate that
file by re-running the small script embedded at the top of this doc's history
(or just open `bench_history.jsonl` directly and read the latest entries).

## Reading the history

```bash
.venv/bin/python bench.py --history             # last 5 runs per prompt
.venv/bin/python bench.py --history --history-limit 10
```

## Cross-mode comparison

To compare the latest runs of multiple modes side-by-side in one table:

```bash
.venv/bin/python bench.py --compare default think memory
.venv/bin/python bench.py --compare default mcp memory
```

The view picks the most recent `run_id` per `mode_tag` and lays prompts as
rows, with one (pygentic, hermes) pair of columns per mode. Useful for
seeing "did thinking slow anything down?" or "does memory restore key
consistency?" at a glance.

Output groups by prompt and shows recent runs side-by-side. Example:

```
what time is it
  2026-05-12T08:30Z  pygentic 0.902s  ttft 0.439s
  2026-05-12T08:51Z  pygentic 0.902s  ttft 0.439s
  2026-05-12T15:23Z  pygentic 0.847s  ttft 0.482s       ← latest
  2026-05-12T08:30Z  hermes   1.655s  ttft 1.303s
  2026-05-12T15:23Z  hermes   1.657s  ttft 1.301s       ← latest
```

You can grep the file directly too — it's just JSONL:

```bash
jq -r 'select(.framework=="pygentic" and .prompt=="what time is it") | "\(.run_id)\t\(.total)"' bench_history.jsonl
```

## Correctness validation, not just latency

Each prompt in `DEFAULT_PROMPTS` is a `(text, expected_tool)` tuple. After
every turn, bench.py reads the framework's most recent log entry and
checks:

- Did the model pick `expected_tool`?
- Or, when `expected_tool` is `None`, did it return a free-text answer?
- Or, when `expected_tool` is `"*"`, did it call any tool at all?
- Was the entry tagged with `parse_fallback="silent_format_fail"` (i.e. the
  model emitted malformed tool-call syntax that got salvaged as a final)?

A per-framework summary line at the end of each run reports `N/M passed`
and lists any failures. This is what catches the failure mode where the
model emits `<|tool_call>call:foo{}<tool_call|>` and the parser silently
falls through to a "final" answer — the bench used to record `total:
1.9s` and call it a win; now it explicitly fails.

The hardened Hermes parser (`hermes/tool_router.py`) accepts five format
variants beyond the strict `<tool_call>{...}</tool_call>`:
chatml-style `<|tool_call|>` delimiters, markdown fences, and the
`call:tool_name{args}` form. Recovered calls are tagged with their
fallback label in the log entry so you can see which variants Gemma
drifted toward most often.

## What to watch in the numbers

| Signal                              | What it means                                       | Likely cause if it regresses                          |
|-------------------------------------|-----------------------------------------------------|-------------------------------------------------------|
| `decision_ttft` spike (~0.3 s) on natural-mode follow-ups | KV cache prefix not reused across decide+finalize | A new system prompt was introduced for finalize       |
| `decision` total > 1.5 s on simple tools | Grammar overhead or cache miss               | Grammar recompiled per call, or longer system prompt  |
| `total` dominated by `final`        | Finalize generation is the bottleneck               | Tool's default mode should probably be `fast`         |
| `total` dominated by `tool`         | Tool itself is slow (web_search, speak)             | Network latency or audio playback (expected)          |
| Free-text answers slow in Pygentic  | JSON-wrap cost on `{"final":"..."}`                 | Structural — won't change without hybrid grammar      |

The "Performance notes" section of the root README summarizes the five
non-obvious findings that drove the current design (prompt unification,
grammar caching, fast-mode defaults, sandbox honesty, SSML).

## Adding new prompts

`bench.py`'s `DEFAULT_PROMPTS` is just a Python list. Add a string, re-run.
The new prompt's history starts on that run. If you want to keep a stable
default set and run experimental prompts separately:

```bash
echo "what's the weather like" > extra.txt
echo "summarize the last paper you searched" >> extra.txt
.venv/bin/python bench.py --prompts extra.txt
```

## When to suspect a regression

Compare the last two runs of a prompt in `bench_history.jsonl`. If `total`
moves by more than ~10 % on the deterministic prompts (anything that's not
web_search or speak_file), it's worth investigating. The TTFT split tells
you whether the cost is in prefill (system prompt change?) or decode
(grammar / model change?).

For a quick visual: run `bench.py --history` after every meaningful change.
