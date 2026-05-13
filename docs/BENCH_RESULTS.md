# Benchmark results

Snapshot of the latest bench runs across modes. Regenerate with:

```bash
python bench.py                  # adds a fresh default run to bench_history.jsonl
python bench.py --write-results  # rewrites this file from the latest entries
```

See [BENCHMARKING.md](BENCHMARKING.md) for bench mechanics and mode flags.

## Current baseline — default mode

Run `2026-05-13T00:31:18+00:00`.

| prompt | pygentic total | pygentic ttft | hermes total | hermes ttft |
|---|---:|---:|---:|---:|
| what time is it | 1.242 | 0.860 | 2.507 | 2.148 |
| calculate 47 times 23 plus 12 | 1.096 | 0.136 | 0.659 | 0.140 |
| list the workspace | 0.654 | 0.107 | 0.506 | 0.104 |
| make a file called bench.txt with the message... | 1.684 | 0.146 | 1.114 | 0.149 |
| read bench.txt out loud | 3.498 | 0.118 | 2.915 | 0.115 |
| search the web for recent news about local llms | 4.758 | 0.182 | 5.121 | 0.177 |
| tell me a one sentence story about a robot | 1.557 | 0.135 | 0.479 | 0.110 |
| delete bench.txt | 1.021 | 0.107 | 0.848 | 0.106 |
| what is the cpu and disk status of this machine | 0.952 | 0.130 | 0.487 | 0.132 |
| what time is it in shanghai | 0.768 | 0.109 | 0.551 | 0.104 |
| search the web for trending youtube topics ab... | 4.608 | 0.137 | 5.495 | 0.132 |
| write a 4 sentence youtube intro script about... | 6.934 | 0.147 | 2.437 | 0.153 |
| append a closing line to youtube_intro.txt as... | 2.147 | 0.142 | 1.311 | 0.150 |
| narrate youtube_intro.txt out loud as if you ... | 30.828 | 0.159 | 26.583 | 0.163 |
| come up with a catchy youtube title for a vid... | 5.569 | 0.147 | 4.203 | 0.134 |
| delete youtube_intro.txt | 1.174 | 0.114 | 0.941 | 0.115 |
| remember that my preferred youtube video leng... | 1.089 | 0.139 | 0.742 | 0.141 |
| what video length do I prefer? | 0.725 | 0.121 | 0.569 | 0.119 |
| what do you know about me? | 0.505 | 0.115 | 0.219 | 0.097 |
| forget my video length preference | 0.683 | 0.112 | 0.530 | 0.111 |

## Historical consistency — original 9 prompts

Spot-check for regressions: if the latest column drifts >50% from r1 on
the simple-tool prompts (calc, list, delete, cpu/disk), investigate.

### Pygentic — total (seconds)

| prompt | r1 first baseline | r12 prior | r13 latest |
|---|---:|---:|---:|
| what time is it | 0.903 | 1.127 | 1.242 |
| calculate 47 times 23 plus 12 | 1.187 | 1.124 | 1.096 |
| list the workspace | 0.653 | 0.649 | 0.654 |
| make a file called bench.txt with the message... | 1.642 | 1.716 | 1.684 |
| read bench.txt out loud | 9.178 | 3.298 | 3.498 |
| search the web for recent news about local llms | 6.841 | 6.312 | 4.758 |
| tell me a one sentence story about a robot | 1.777 | 1.556 | 1.557 |
| delete bench.txt | 0.977 | 1.109 | 1.021 |
| what is the cpu and disk status of this machine | 0.926 | 0.921 | 0.952 |

### Hermes — total (seconds)

| prompt | r1 first baseline | r12 prior | r13 latest |
|---|---:|---:|---:|
| what time is it | 1.703 | 2.310 | 2.507 |
| calculate 47 times 23 plus 12 | 0.661 | 0.676 | 0.659 |
| list the workspace | 0.506 | 0.518 | 0.506 |
| make a file called bench.txt with the message... | 1.200 | 1.132 | 1.114 |
| read bench.txt out loud | 5.277 | 2.915 | 2.915 |
| search the web for recent news about local llms | 5.752 | 5.332 | 5.121 |
| tell me a one sentence story about a robot | 0.393 | 0.487 | 0.479 |
| delete bench.txt | 0.856 | 0.867 | 0.848 |
| what is the cpu and disk status of this machine | 0.486 | 0.497 | 0.487 |

## Mode comparison — latest run per mode

- **default** ⟶ run `2026-05-13T00:31:18+00:00`
- **think** ⟶ run `2026-05-12T20:56:27+00:00`
- **memory** ⟶ run `2026-05-12T22:08:26+00:00`
- **mcp** ⟶ run `2026-05-12T21:02:59+00:00`
- **mcp+think+memory** ⟶ run `2026-05-12T21:39:28+00:00`

### Pygentic — total (seconds)

| prompt | default | think | memory | mcp | mcp+think+memory |
|---|---:|---:|---:|---:|---:|
| what time is it | 1.242 | 1.081 | 2.520 | 1.292 | 1.600 |
| calculate 47 times 23 plus 12 | 1.096 | 1.159 | 1.881 | 1.136 | 1.517 |
| list the workspace | 0.654 | 0.660 | 2.525 | 0.641 | 1.021 |
| make a file called bench.txt with the message... | 1.684 | 1.655 | 2.053 | 1.438 | 1.880 |
| read bench.txt out loud | 3.498 | 8.237 | 9.576 | 8.211 | 9.146 |
| search the web for recent news about local llms | 4.758 | 7.408 | 7.722 | 6.759 | 4.253 |
| tell me a one sentence story about a robot | 1.557 | 1.807 | 1.936 | 1.507 | 1.846 |
| delete bench.txt | 1.021 | 1.019 | 1.917 | 1.012 | 1.394 |
| what is the cpu and disk status of this machine | 0.952 | 0.841 | 6.391 | 0.874 | 1.252 |
| what time is it in shanghai | 0.768 | 0.788 | 1.887 | 0.759 | 1.044 |
| search the web for trending youtube topics ab... | 4.608 | 5.210 | 5.960 | 4.991 | 4.365 |
| write a 4 sentence youtube intro script about... | 6.934 | 4.895 | 6.517 | 4.781 | 5.964 |
| append a closing line to youtube_intro.txt as... | 2.147 | 2.075 | 3.505 | 2.149 | 2.793 |
| narrate youtube_intro.txt out loud as if you ... | 30.828 | 28.584 | 29.114 | 24.755 | 29.835 |
| come up with a catchy youtube title for a vid... | 5.569 | 0.621 | 1.535 | 4.360 | 1.544 |
| delete youtube_intro.txt | 1.174 | 1.147 | 2.103 | 1.448 | 1.520 |
| remember that my preferred youtube video leng... | 1.089 | 1.124 | 3.148 | 1.471 | 1.728 |
| what video length do I prefer? | 0.725 | 0.705 | 2.269 | 0.756 | 1.401 |
| what do you know about me? | 0.505 | 0.509 | 2.192 | 0.543 | 0.975 |
| forget my video length preference | 0.683 | 0.699 | 2.461 | 0.738 | 1.419 |

### Hermes — total (seconds)

| prompt | default | think | memory | mcp | mcp+think+memory |
|---|---:|---:|---:|---:|---:|
| what time is it | 2.507 | 2.207 | 3.023 | 2.642 | 2.866 |
| calculate 47 times 23 plus 12 | 0.659 | 0.708 | 0.924 | 0.673 | 0.963 |
| list the workspace | 0.506 | 0.513 | 1.429 | 0.521 | 0.884 |
| make a file called bench.txt with the message... | 1.114 | 1.176 | 1.131 | 1.171 | 1.641 |
| read bench.txt out loud | 2.915 | 4.988 | 3.187 | 1823.549 | 5.502 |
| search the web for recent news about local llms | 5.121 | 5.660 | 5.824 | 6.292 | – |
| tell me a one sentence story about a robot | 0.479 | 0.465 | 0.856 | 0.439 | – |
| delete bench.txt | 0.848 | 0.882 | 1.333 | 0.912 | – |
| what is the cpu and disk status of this machine | 0.487 | 0.494 | 2.149 | 0.499 | – |
| what time is it in shanghai | 0.551 | 0.566 | 0.983 | 0.552 | 0.838 |
| search the web for trending youtube topics ab... | 5.495 | 3.779 | 4.601 | 5.452 | – |
| write a 4 sentence youtube intro script about... | 2.437 | 2.264 | 2.883 | 2.257 | – |
| append a closing line to youtube_intro.txt as... | 1.311 | 1.512 | 2.141 | 1.524 | – |
| narrate youtube_intro.txt out loud as if you ... | 26.583 | 31.277 | 32.689 | 16.514 | – |
| come up with a catchy youtube title for a vid... | 4.203 | – | 0.998 | 0.556 | – |
| delete youtube_intro.txt | 0.941 | – | 1.488 | 1.706 | – |
| remember that my preferred youtube video leng... | 0.742 | – | 1.882 | 0.686 | – |
| what video length do I prefer? | 0.569 | – | 1.646 | 0.898 | – |
| what do you know about me? | 0.219 | – | 1.654 | 1.275 | – |
| forget my video length preference | 0.530 | – | 1.661 | 0.809 | – |

## What to watch for in future runs

- **Pygentic single-tool prompts** (calculate, list, delete, cpu/disk) should stay around 0.6–1.2 s. A jump to 3 s+ means the multi-step loop is firing when it shouldn't.
- **Hermes single-tool prompts** should stay around 0.5–1.1 s.
- **TTFT** for warm prompts should be ~0.10–0.15 s on both. Spikes to 0.5 s+ indicate a KV cache miss.
- **Memory prompts** route reliably only with `--with-memory`. Raw-mode failures there are expected, not regressions.
- **TTS prompts** are wall-clock-dominated by audio playback. Variance there is normal.