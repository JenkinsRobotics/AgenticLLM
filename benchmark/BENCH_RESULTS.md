# Benchmark results

Snapshot of the latest bench runs across modes. Regenerate with:

```bash
python bench.py                  # adds a fresh default run to bench_history.jsonl
python bench.py --write-results  # rewrites this file from the latest entries
```

See [BENCHMARKING.md](BENCHMARKING.md) for bench mechanics and mode flags.

## Current baseline — default mode

Run `2026-05-13T20:10:03+00:00`.

| prompt | python_custom_json total | python_custom_json ttft | python_hermes_xml total | python_hermes_xml ttft |
|---|---:|---:|---:|---:|
| what time is it | 1.393 | 1.006 | 2.917 | 2.558 |
| calculate 47 times 23 plus 12 | 1.110 | 0.139 | 0.666 | 0.143 |
| list the workspace | 0.639 | 0.104 | 0.507 | 0.105 |
| make a file called bench.txt with the message... | 1.610 | 0.145 | 1.125 | 0.150 |
| read bench.txt out loud | 3.493 | 0.116 | 2.912 | 0.116 |
| search the web for recent news about local llms | 6.116 | 0.187 | 5.549 | 0.174 |
| tell me a one sentence story about a robot | 1.717 | 0.126 | 0.480 | 0.111 |
| delete bench.txt | 1.066 | 0.107 | 0.866 | 0.107 |
| what is the cpu and disk status of this machine | 0.894 | 0.131 | 0.500 | 0.134 |
| what time is it in shanghai | 0.813 | 0.104 | 0.549 | 0.105 |
| search the web for trending youtube topics ab... | 6.471 | 0.139 | 5.022 | 0.134 |
| write a 4 sentence youtube intro script about... | 6.038 | 0.151 | 2.398 | 0.154 |
| append a closing line to youtube_intro.txt as... | 2.209 | 0.147 | 1.296 | 0.149 |
| narrate youtube_intro.txt out loud as if you ... | 28.189 | 0.172 | 30.009 | 0.161 |
| come up with a catchy youtube title for a vid... | 0.320 | 0.151 | 3.913 | 0.134 |
| delete youtube_intro.txt | 1.235 | 0.114 | 0.951 | 0.116 |
| remember that my preferred youtube video leng... | 1.141 | 0.140 | 0.746 | 0.141 |
| what video length do I prefer? | 0.740 | 0.121 | 0.542 | 0.119 |
| what do you know about me? | 0.525 | 0.115 | 0.219 | 0.097 |
| forget my video length preference | 0.704 | 0.111 | 0.533 | 0.111 |

## Historical consistency — original 9 prompts

Spot-check for regressions: if the latest column drifts >50% from r1 on
the simple-tool prompts (calc, list, delete, cpu/disk), investigate.

### Python_custom_json — total (seconds)

| prompt | r1 first baseline | r16 prior | r17 latest |
|---|---:|---:|---:|
| what time is it | – | 1.378 | 1.393 |
| calculate 47 times 23 plus 12 | – | 1.124 | 1.110 |
| list the workspace | – | 0.646 | 0.639 |
| make a file called bench.txt with the message... | – | 1.769 | 1.610 |
| read bench.txt out loud | – | 3.416 | 3.493 |
| search the web for recent news about local llms | – | 11.435 | 6.116 |
| tell me a one sentence story about a robot | – | 1.696 | 1.717 |
| delete bench.txt | – | 1.054 | 1.066 |
| what is the cpu and disk status of this machine | – | 0.937 | 0.894 |

### Python_hermes_xml — total (seconds)

| prompt | r1 first baseline | r16 prior | r17 latest |
|---|---:|---:|---:|
| what time is it | – | 2.923 | 2.917 |
| calculate 47 times 23 plus 12 | – | 0.660 | 0.666 |
| list the workspace | – | 0.503 | 0.507 |
| make a file called bench.txt with the message... | – | 1.115 | 1.125 |
| read bench.txt out loud | – | 2.923 | 2.912 |
| search the web for recent news about local llms | – | 9.476 | 5.549 |
| tell me a one sentence story about a robot | – | 0.476 | 0.480 |
| delete bench.txt | – | 0.839 | 0.866 |
| what is the cpu and disk status of this machine | – | 0.482 | 0.500 |

### Python_pydantic_ai — total (seconds)

| prompt | r1 first baseline | r16 prior | r17 latest |
|---|---:|---:|---:|
| what time is it | – | 1.810 | 1.810 |
| calculate 47 times 23 plus 12 | – | 0.668 | 0.673 |
| list the workspace | – | 0.631 | 0.775 |
| make a file called bench.txt with the message... | – | 0.754 | 0.750 |
| read bench.txt out loud | – | 3.009 | 2.956 |
| search the web for recent news about local llms | – | 7.910 | 6.095 |
| tell me a one sentence story about a robot | – | 0.398 | 0.401 |
| delete bench.txt | – | 0.569 | 0.568 |
| what is the cpu and disk status of this machine | – | 1.084 | 1.308 |

## Mode comparison — latest run per mode

- **default** ⟶ run `2026-05-13T20:10:03+00:00`
- **think** ⟶ run `2026-05-13T19:57:02+00:00`
- **memory** ⟶ run `2026-05-13T18:52:19+00:00`
- **mcp** ⟶ run `2026-05-12T21:02:59+00:00`
- **mcp+think+memory** ⟶ run `2026-05-12T21:39:28+00:00`

### Python_custom_json — total (seconds)

| prompt | default | think | memory | mcp | mcp+think+memory |
|---|---:|---:|---:|---:|---:|
| what time is it | 1.393 | 1.295 | 1.822 | – | – |
| calculate 47 times 23 plus 12 | 1.110 | 1.177 | 1.102 | – | – |
| list the workspace | 0.639 | 0.664 | 0.724 | – | – |
| make a file called bench.txt with the message... | 1.610 | 1.679 | 1.537 | – | – |
| read bench.txt out loud | 3.493 | 5.283 | 3.288 | – | – |
| search the web for recent news about local llms | 6.116 | 6.589 | 6.945 | – | – |
| tell me a one sentence story about a robot | 1.717 | 1.647 | 1.856 | – | – |
| delete bench.txt | 1.066 | 1.082 | 1.410 | – | – |
| what is the cpu and disk status of this machine | 0.894 | 0.956 | 1.181 | – | – |
| what time is it in shanghai | 0.813 | 0.787 | 0.816 | – | – |
| search the web for trending youtube topics ab... | 6.471 | 4.307 | 3.672 | – | – |
| write a 4 sentence youtube intro script about... | 6.038 | – | 6.902 | – | – |
| append a closing line to youtube_intro.txt as... | 2.209 | – | 2.999 | – | – |
| narrate youtube_intro.txt out loud as if you ... | 28.189 | – | 33.896 | – | – |
| come up with a catchy youtube title for a vid... | 0.320 | – | 1.052 | – | – |
| delete youtube_intro.txt | 1.235 | – | 1.556 | – | – |
| remember that my preferred youtube video leng... | 1.141 | – | 1.735 | – | – |
| what video length do I prefer? | 0.740 | – | 1.396 | – | – |
| what do you know about me? | 0.525 | – | 0.959 | – | – |
| forget my video length preference | 0.704 | – | 1.379 | – | – |

### Python_hermes_xml — total (seconds)

| prompt | default | think | memory | mcp | mcp+think+memory |
|---|---:|---:|---:|---:|---:|
| what time is it | 2.917 | – | 3.353 | – | – |
| calculate 47 times 23 plus 12 | 0.666 | – | 0.703 | – | – |
| list the workspace | 0.507 | – | 0.573 | – | – |
| make a file called bench.txt with the message... | 1.125 | – | 1.137 | – | – |
| read bench.txt out loud | 2.912 | – | 2.958 | – | – |
| search the web for recent news about local llms | 5.549 | – | 5.154 | – | – |
| tell me a one sentence story about a robot | 0.480 | – | 0.912 | – | – |
| delete bench.txt | 0.866 | – | 1.340 | – | – |
| what is the cpu and disk status of this machine | 0.500 | – | 0.966 | – | – |
| what time is it in shanghai | 0.549 | – | 0.610 | – | – |
| search the web for trending youtube topics ab... | 5.022 | – | 4.453 | – | – |
| write a 4 sentence youtube intro script about... | 2.398 | – | 2.888 | – | – |
| append a closing line to youtube_intro.txt as... | 1.296 | – | 2.163 | – | – |
| narrate youtube_intro.txt out loud as if you ... | 30.009 | – | 32.985 | – | – |
| come up with a catchy youtube title for a vid... | 3.913 | – | 1.093 | – | – |
| delete youtube_intro.txt | 0.951 | – | 1.683 | – | – |
| remember that my preferred youtube video leng... | 0.746 | – | 1.455 | – | – |
| what video length do I prefer? | 0.542 | – | 1.332 | – | – |
| what do you know about me? | 0.219 | – | 1.220 | – | – |
| forget my video length preference | 0.533 | – | 1.343 | – | – |

### Python_pydantic_ai — total (seconds)

| prompt | default | think | memory | mcp | mcp+think+memory |
|---|---:|---:|---:|---:|---:|
| what time is it | 1.810 | 2.189 | 2.200 | – | – |
| calculate 47 times 23 plus 12 | 0.673 | 4.089 | 0.897 | – | – |
| list the workspace | 0.775 | 4.361 | 1.536 | – | – |
| make a file called bench.txt with the message... | 0.750 | 4.585 | 1.844 | – | – |
| read bench.txt out loud | 2.956 | 6.728 | 415.259 | – | – |
| search the web for recent news about local llms | 6.095 | 7.252 | 1.340 | – | – |
| tell me a one sentence story about a robot | 0.401 | 4.958 | 1.097 | – | – |
| delete bench.txt | 0.568 | 4.627 | 1.490 | – | – |
| what is the cpu and disk status of this machine | 1.308 | 5.719 | 2.650 | – | – |
| what time is it in shanghai | 0.705 | 4.647 | 0.972 | – | – |
| search the web for trending youtube topics ab... | 4.489 | 9.367 | 5.144 | – | – |
| write a 4 sentence youtube intro script about... | 1.736 | 6.545 | 5.144 | – | – |
| append a closing line to youtube_intro.txt as... | 0.859 | 0.007 | 2.676 | – | – |
| narrate youtube_intro.txt out loud as if you ... | 25.314 | 0.005 | 598.668 | – | – |
| come up with a catchy youtube title for a vid... | 0.320 | 0.005 | 6.514 | – | – |
| delete youtube_intro.txt | 0.632 | 0.005 | 2.912 | – | – |
| remember that my preferred youtube video leng... | 0.737 | 0.006 | 2.728 | – | – |
| what video length do I prefer? | 0.530 | 0.006 | 2.225 | – | – |
| what do you know about me? | 0.751 | 0.004 | 2.940 | – | – |
| forget my video length preference | 0.699 | 0.006 | 2.123 | – | – |

## What to watch for in future runs

- **Pygentic single-tool prompts** (calculate, list, delete, cpu/disk) should stay around 0.6–1.2 s. A jump to 3 s+ means the multi-step loop is firing when it shouldn't.
- **Hermes single-tool prompts** should stay around 0.5–1.1 s.
- **TTFT** for warm prompts should be ~0.10–0.15 s on both. Spikes to 0.5 s+ indicate a KV cache miss.
- **Memory prompts** route reliably only with `--with-memory`. Raw-mode failures there are expected, not regressions.
- **TTS prompts** are wall-clock-dominated by audio playback. Variance there is normal.