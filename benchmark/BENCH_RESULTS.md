# Benchmark results

Snapshot of the latest bench runs across modes. Regenerate with:

```bash
python bench.py                  # adds a fresh default run to bench_history.jsonl
python bench.py --write-results  # rewrites this file from the latest entries
```

See [BENCHMARKING.md](BENCHMARKING.md) for bench mechanics and mode flags.

## Current baseline — default mode

Run `2026-05-17T19:46:32+00:00`.

| prompt | python_custom_json total | python_custom_json ttft | python_hermes_xml total | python_hermes_xml ttft |
|---|---:|---:|---:|---:|
| what time is it | 1.359 | 0.973 | 2.936 | 2.569 |
| calculate 47 times 23 plus 12 | 1.107 | 0.138 | 0.673 | 0.143 |
| list the workspace | 0.654 | 0.105 | 0.518 | 0.106 |
| make a file called bench.txt with the message... | 1.726 | 0.147 | 1.147 | 0.152 |
| read bench.txt out loud | 3.479 | 0.117 | 2.992 | 0.118 |
| search the web for recent news about local llms | 7.302 | 0.228 | 7.222 | 0.193 |
| tell me a one sentence story about a robot | 1.841 | 0.168 | 0.546 | 0.125 |
| delete bench.txt | 1.082 | 0.111 | 0.882 | 0.108 |
| what is the cpu and disk status of this machine | 0.900 | 0.134 | 0.505 | 0.135 |
| what time is it in shanghai | 0.768 | 0.104 | 0.573 | 0.108 |
| search the web for trending youtube topics ab... | 4.661 | 0.142 | 4.828 | 0.135 |
| write a 4 sentence youtube intro script about... | 5.808 | 0.151 | 2.609 | 0.155 |
| append a closing line to youtube_intro.txt as... | 2.273 | 0.149 | 1.360 | 0.152 |
| narrate youtube_intro.txt out loud as if you ... | 28.330 | 0.161 | 27.699 | 0.165 |
| come up with a catchy youtube title for a vid... | 0.330 | 0.154 | 3.902 | 0.136 |
| delete youtube_intro.txt | 1.246 | 0.117 | 0.973 | 0.117 |
| remember that my preferred youtube video leng... | 1.184 | 0.141 | 0.769 | 0.144 |
| what video length do I prefer? | 0.741 | 0.119 | 0.555 | 0.121 |
| what do you know about me? | 0.528 | 0.116 | 0.223 | 0.099 |
| forget my video length preference | 0.736 | 0.113 | 0.546 | 0.114 |

## Historical consistency — original 9 prompts

Spot-check for regressions: if the latest column drifts >50% from r1 on
the simple-tool prompts (calc, list, delete, cpu/disk), investigate.

### Python_custom_json — total (seconds)

| prompt | r1 first baseline | r21 prior | r22 latest |
|---|---:|---:|---:|
| what time is it | – | 1.365 | 1.359 |
| calculate 47 times 23 plus 12 | – | 1.110 | 1.107 |
| list the workspace | – | 0.660 | 0.654 |
| make a file called bench.txt with the message... | – | 1.701 | 1.726 |
| read bench.txt out loud | – | 3.434 | 3.479 |
| search the web for recent news about local llms | – | 4.999 | 7.302 |
| tell me a one sentence story about a robot | – | 1.826 | 1.841 |
| delete bench.txt | – | 1.104 | 1.082 |
| what is the cpu and disk status of this machine | – | 0.925 | 0.900 |

### Python_hermes_xml — total (seconds)

| prompt | r1 first baseline | r21 prior | r22 latest |
|---|---:|---:|---:|
| what time is it | – | 2.932 | 2.936 |
| calculate 47 times 23 plus 12 | – | 0.668 | 0.673 |
| list the workspace | – | 0.511 | 0.518 |
| make a file called bench.txt with the message... | – | 1.128 | 1.147 |
| read bench.txt out loud | – | 2.953 | 2.992 |
| search the web for recent news about local llms | – | 5.263 | 7.222 |
| tell me a one sentence story about a robot | – | 0.491 | 0.546 |
| delete bench.txt | – | 0.868 | 0.882 |
| what is the cpu and disk status of this machine | – | 0.498 | 0.505 |

### Python_pydantic_ai — total (seconds)

| prompt | r1 first baseline | r21 prior | r22 latest |
|---|---:|---:|---:|
| what time is it | – | 2.866 | 2.865 |
| calculate 47 times 23 plus 12 | – | 0.462 | 0.461 |
| list the workspace | – | 0.937 | 1.287 |
| make a file called bench.txt with the message... | – | 0.534 | 0.535 |
| read bench.txt out loud | – | 2.728 | 2.755 |
| search the web for recent news about local llms | – | 3.370 | 5.441 |
| tell me a one sentence story about a robot | – | 0.421 | 0.408 |
| delete bench.txt | – | 0.351 | 0.341 |
| what is the cpu and disk status of this machine | – | 0.245 | 0.245 |

## Mode comparison — latest run per mode

- **default** ⟶ run `2026-05-17T19:46:32+00:00`
- **think** ⟶ run `2026-05-13T19:57:02+00:00`
- **memory** ⟶ run `2026-05-13T18:52:19+00:00`
- **mcp** ⟶ run `2026-05-14T01:06:01+00:00`
- **mcp+think+memory** ⟶ run `2026-05-12T21:39:28+00:00`

### Python_custom_json — total (seconds)

| prompt | default | think | memory | mcp | mcp+think+memory |
|---|---:|---:|---:|---:|---:|
| what time is it | 1.359 | 1.295 | 1.822 | – | – |
| calculate 47 times 23 plus 12 | 1.107 | 1.177 | 1.102 | – | – |
| list the workspace | 0.654 | 0.664 | 0.724 | – | – |
| make a file called bench.txt with the message... | 1.726 | 1.679 | 1.537 | – | – |
| read bench.txt out loud | 3.479 | 5.283 | 3.288 | – | – |
| search the web for recent news about local llms | 7.302 | 6.589 | 6.945 | – | – |
| tell me a one sentence story about a robot | 1.841 | 1.647 | 1.856 | – | – |
| delete bench.txt | 1.082 | 1.082 | 1.410 | – | – |
| what is the cpu and disk status of this machine | 0.900 | 0.956 | 1.181 | – | – |
| what time is it in shanghai | 0.768 | 0.787 | 0.816 | – | – |
| search the web for trending youtube topics ab... | 4.661 | 4.307 | 3.672 | – | – |
| write a 4 sentence youtube intro script about... | 5.808 | – | 6.902 | – | – |
| append a closing line to youtube_intro.txt as... | 2.273 | – | 2.999 | – | – |
| narrate youtube_intro.txt out loud as if you ... | 28.330 | – | 33.896 | – | – |
| come up with a catchy youtube title for a vid... | 0.330 | – | 1.052 | – | – |
| delete youtube_intro.txt | 1.246 | – | 1.556 | – | – |
| remember that my preferred youtube video leng... | 1.184 | – | 1.735 | – | – |
| what video length do I prefer? | 0.741 | – | 1.396 | – | – |
| what do you know about me? | 0.528 | – | 0.959 | – | – |
| forget my video length preference | 0.736 | – | 1.379 | – | – |

### Python_hermes_xml — total (seconds)

| prompt | default | think | memory | mcp | mcp+think+memory |
|---|---:|---:|---:|---:|---:|
| what time is it | 2.936 | – | 3.353 | – | – |
| calculate 47 times 23 plus 12 | 0.673 | – | 0.703 | – | – |
| list the workspace | 0.518 | – | 0.573 | – | – |
| make a file called bench.txt with the message... | 1.147 | – | 1.137 | – | – |
| read bench.txt out loud | 2.992 | – | 2.958 | – | – |
| search the web for recent news about local llms | 7.222 | – | 5.154 | – | – |
| tell me a one sentence story about a robot | 0.546 | – | 0.912 | – | – |
| delete bench.txt | 0.882 | – | 1.340 | – | – |
| what is the cpu and disk status of this machine | 0.505 | – | 0.966 | – | – |
| what time is it in shanghai | 0.573 | – | 0.610 | – | – |
| search the web for trending youtube topics ab... | 4.828 | – | 4.453 | – | – |
| write a 4 sentence youtube intro script about... | 2.609 | – | 2.888 | – | – |
| append a closing line to youtube_intro.txt as... | 1.360 | – | 2.163 | – | – |
| narrate youtube_intro.txt out loud as if you ... | 27.699 | – | 32.985 | – | – |
| come up with a catchy youtube title for a vid... | 3.902 | – | 1.093 | – | – |
| delete youtube_intro.txt | 0.973 | – | 1.683 | – | – |
| remember that my preferred youtube video leng... | 0.769 | – | 1.455 | – | – |
| what video length do I prefer? | 0.555 | – | 1.332 | – | – |
| what do you know about me? | 0.223 | – | 1.220 | – | – |
| forget my video length preference | 0.546 | – | 1.343 | – | – |

### Python_pydantic_ai — total (seconds)

| prompt | default | think | memory | mcp | mcp+think+memory |
|---|---:|---:|---:|---:|---:|
| what time is it | 2.865 | 2.189 | 2.200 | 1.954 | – |
| calculate 47 times 23 plus 12 | 0.461 | 4.089 | 0.897 | 0.667 | – |
| list the workspace | 1.287 | 4.361 | 1.536 | 0.886 | – |
| make a file called bench.txt with the message... | 0.535 | 4.585 | 1.844 | 0.735 | – |
| read bench.txt out loud | 2.755 | 6.728 | 415.259 | 3.071 | – |
| search the web for recent news about local llms | 5.441 | 7.252 | 1.340 | 5.469 | – |
| tell me a one sentence story about a robot | 0.408 | 4.958 | 1.097 | 0.481 | – |
| delete bench.txt | 0.341 | 4.627 | 1.490 | 0.560 | – |
| what is the cpu and disk status of this machine | 0.245 | 5.719 | 2.650 | 1.631 | – |
| what time is it in shanghai | 0.346 | 4.647 | 0.972 | 0.651 | – |
| search the web for trending youtube topics ab... | 6.212 | 9.367 | 5.144 | 3.618 | – |
| write a 4 sentence youtube intro script about... | 3.050 | 6.545 | 5.144 | 1.826 | – |
| append a closing line to youtube_intro.txt as... | 0.592 | 0.007 | 2.676 | 0.866 | – |
| narrate youtube_intro.txt out loud as if you ... | 0.895 | 0.005 | 598.668 | 24.619 | – |
| come up with a catchy youtube title for a vid... | 0.320 | 0.005 | 6.514 | 0.393 | – |
| delete youtube_intro.txt | 0.558 | 0.005 | 2.912 | 0.633 | – |
| remember that my preferred youtube video leng... | 0.173 | 0.006 | 2.728 | 0.740 | – |
| what video length do I prefer? | 0.650 | 0.006 | 2.225 | 0.478 | – |
| what do you know about me? | 0.720 | 0.004 | 2.940 | 0.849 | – |
| forget my video length preference | 0.567 | 0.006 | 2.123 | 0.716 | – |

## What to watch for in future runs

- **Pygentic single-tool prompts** (calculate, list, delete, cpu/disk) should stay around 0.6–1.2 s. A jump to 3 s+ means the multi-step loop is firing when it shouldn't.
- **Hermes single-tool prompts** should stay around 0.5–1.1 s.
- **TTFT** for warm prompts should be ~0.10–0.15 s on both. Spikes to 0.5 s+ indicate a KV cache miss.
- **Memory prompts** route reliably only with `--with-memory`. Raw-mode failures there are expected, not regressions.
- **TTS prompts** are wall-clock-dominated by audio playback. Variance there is normal.