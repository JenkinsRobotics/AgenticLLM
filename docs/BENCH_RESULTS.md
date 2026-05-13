# Benchmark results

Snapshot of the latest bench runs across modes. Regenerate with:

```bash
python bench.py                  # adds a fresh default run to bench_history.jsonl
python bench.py --write-results  # rewrites this file from the latest entries
```

See [BENCHMARKING.md](BENCHMARKING.md) for bench mechanics and mode flags.

## Current baseline — default mode

Run `2026-05-13T00:31:18+00:00`.

| prompt | python_custom_json total | python_custom_json ttft | python_hermes_xml total | python_hermes_xml ttft |
|---|---:|---:|---:|---:|
| what time is it | – | – | – | – |
| calculate 47 times 23 plus 12 | – | – | – | – |
| list the workspace | – | – | – | – |
| make a file called bench.txt with the message... | – | – | – | – |
| read bench.txt out loud | – | – | – | – |
| search the web for recent news about local llms | – | – | – | – |
| tell me a one sentence story about a robot | – | – | – | – |
| delete bench.txt | – | – | – | – |
| what is the cpu and disk status of this machine | – | – | – | – |
| what time is it in shanghai | – | – | – | – |
| search the web for trending youtube topics ab... | – | – | – | – |
| write a 4 sentence youtube intro script about... | – | – | – | – |
| append a closing line to youtube_intro.txt as... | – | – | – | – |
| narrate youtube_intro.txt out loud as if you ... | – | – | – | – |
| come up with a catchy youtube title for a vid... | – | – | – | – |
| delete youtube_intro.txt | – | – | – | – |
| remember that my preferred youtube video leng... | – | – | – | – |
| what video length do I prefer? | – | – | – | – |
| what do you know about me? | – | – | – | – |
| forget my video length preference | – | – | – | – |

## Historical consistency — original 9 prompts

Spot-check for regressions: if the latest column drifts >50% from r1 on
the simple-tool prompts (calc, list, delete, cpu/disk), investigate.

### Python_custom_json — total (seconds)

| prompt | r1 first baseline | r12 prior | r13 latest |
|---|---:|---:|---:|
| what time is it | – | – | – |
| calculate 47 times 23 plus 12 | – | – | – |
| list the workspace | – | – | – |
| make a file called bench.txt with the message... | – | – | – |
| read bench.txt out loud | – | – | – |
| search the web for recent news about local llms | – | – | – |
| tell me a one sentence story about a robot | – | – | – |
| delete bench.txt | – | – | – |
| what is the cpu and disk status of this machine | – | – | – |

### Python_hermes_xml — total (seconds)

| prompt | r1 first baseline | r12 prior | r13 latest |
|---|---:|---:|---:|
| what time is it | – | – | – |
| calculate 47 times 23 plus 12 | – | – | – |
| list the workspace | – | – | – |
| make a file called bench.txt with the message... | – | – | – |
| read bench.txt out loud | – | – | – |
| search the web for recent news about local llms | – | – | – |
| tell me a one sentence story about a robot | – | – | – |
| delete bench.txt | – | – | – |
| what is the cpu and disk status of this machine | – | – | – |

## Mode comparison — latest run per mode

- **default** ⟶ run `2026-05-13T00:31:18+00:00`
- **think** ⟶ run `2026-05-12T20:56:27+00:00`
- **memory** ⟶ run `2026-05-12T22:08:26+00:00`
- **mcp** ⟶ run `2026-05-12T21:02:59+00:00`
- **mcp+think+memory** ⟶ run `2026-05-12T21:39:28+00:00`

### Python_custom_json — total (seconds)

| prompt | default | think | memory | mcp | mcp+think+memory |
|---|---:|---:|---:|---:|---:|
| what time is it | – | – | – | – | – |
| calculate 47 times 23 plus 12 | – | – | – | – | – |
| list the workspace | – | – | – | – | – |
| make a file called bench.txt with the message... | – | – | – | – | – |
| read bench.txt out loud | – | – | – | – | – |
| search the web for recent news about local llms | – | – | – | – | – |
| tell me a one sentence story about a robot | – | – | – | – | – |
| delete bench.txt | – | – | – | – | – |
| what is the cpu and disk status of this machine | – | – | – | – | – |
| what time is it in shanghai | – | – | – | – | – |
| search the web for trending youtube topics ab... | – | – | – | – | – |
| write a 4 sentence youtube intro script about... | – | – | – | – | – |
| append a closing line to youtube_intro.txt as... | – | – | – | – | – |
| narrate youtube_intro.txt out loud as if you ... | – | – | – | – | – |
| come up with a catchy youtube title for a vid... | – | – | – | – | – |
| delete youtube_intro.txt | – | – | – | – | – |
| remember that my preferred youtube video leng... | – | – | – | – | – |
| what video length do I prefer? | – | – | – | – | – |
| what do you know about me? | – | – | – | – | – |
| forget my video length preference | – | – | – | – | – |

### Python_hermes_xml — total (seconds)

| prompt | default | think | memory | mcp | mcp+think+memory |
|---|---:|---:|---:|---:|---:|
| what time is it | – | – | – | – | – |
| calculate 47 times 23 plus 12 | – | – | – | – | – |
| list the workspace | – | – | – | – | – |
| make a file called bench.txt with the message... | – | – | – | – | – |
| read bench.txt out loud | – | – | – | – | – |
| search the web for recent news about local llms | – | – | – | – | – |
| tell me a one sentence story about a robot | – | – | – | – | – |
| delete bench.txt | – | – | – | – | – |
| what is the cpu and disk status of this machine | – | – | – | – | – |
| what time is it in shanghai | – | – | – | – | – |
| search the web for trending youtube topics ab... | – | – | – | – | – |
| write a 4 sentence youtube intro script about... | – | – | – | – | – |
| append a closing line to youtube_intro.txt as... | – | – | – | – | – |
| narrate youtube_intro.txt out loud as if you ... | – | – | – | – | – |
| come up with a catchy youtube title for a vid... | – | – | – | – | – |
| delete youtube_intro.txt | – | – | – | – | – |
| remember that my preferred youtube video leng... | – | – | – | – | – |
| what video length do I prefer? | – | – | – | – | – |
| what do you know about me? | – | – | – | – | – |
| forget my video length preference | – | – | – | – | – |

## What to watch for in future runs

- **Pygentic single-tool prompts** (calculate, list, delete, cpu/disk) should stay around 0.6–1.2 s. A jump to 3 s+ means the multi-step loop is firing when it shouldn't.
- **Hermes single-tool prompts** should stay around 0.5–1.1 s.
- **TTFT** for warm prompts should be ~0.10–0.15 s on both. Spikes to 0.5 s+ indicate a KV cache miss.
- **Memory prompts** route reliably only with `--with-memory`. Raw-mode failures there are expected, not regressions.
- **TTS prompts** are wall-clock-dominated by audio playback. Variance there is normal.