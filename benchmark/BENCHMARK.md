# Benchmark

Last run: `2026-05-17T19:46:32+00:00` · frameworks: python_custom_json, python_hermes_xml, python_pydantic_ai

Regenerate with `python bench.py && python bench.py --write-results`.
Detail history: [docs/BENCH_RESULTS.md](docs/BENCH_RESULTS.md).

## 1. Best record per framework (lowest latency ever)

Each cell = the fastest result that framework has *ever* achieved on this prompt across all default-mode runs in `bench_history.jsonl`. Useful as a personal best target.

| prompt | tool | python_custom_json best | python_hermes_xml best | python_pydantic_ai best |
|---|---|---:|---:|---:|
| what time is it | `get_time` | 1.290 | 2.909 | 1.494 |
| calculate 47 times 23 plus 12 | `calculate` | 1.107 | 0.660 | 0.436 |
| list the workspace | `list_directory` | 0.627 | 0.503 | 0.519 |
| make a file called bench.txt with the message he... | `create_file` | 1.610 | 1.115 | 0.503 |
| read bench.txt out loud | `speak_file` | 3.295 | 2.912 | 2.728 |
| search the web for recent news about local llms | `web_search` | 4.999 | 4.517 | 3.370 |
| tell me a one sentence story about a robot | `(free-text)` | 1.696 | 0.476 | 0.390 |
| delete bench.txt | `delete_file` | 1.054 | 0.839 | 0.326 |
| what is the cpu and disk status of this machine | `system_status` | 0.891 | 0.482 | 0.243 |
| what time is it in shanghai | `get_time` | 0.750 | 0.538 | 0.327 |
| search the web for trending youtube topics about... | `web_search` | 4.536 | 4.697 | 3.682 |
| write a 4 sentence youtube intro script about a ... | `create_file` | 5.428 | 2.181 | 1.330 |
| append a closing line to youtube_intro.txt askin... | `append_file` | 2.135 | 1.293 | 0.592 |
| narrate youtube_intro.txt out loud as if you are... | `speak_file` | 26.535 | 27.699 | 0.895 |
| come up with a catchy youtube title for a video ... | `(free-text)` | 0.319 | 2.013 | 0.318 |
| delete youtube_intro.txt | `delete_file` | 1.197 | 0.924 | 0.360 |
| remember that my preferred youtube video length ... | `remember` | 1.096 | 0.694 | 0.173 |
| what video length do I prefer? | `recall` | 0.720 | 0.531 | 0.220 |
| what do you know about me? | `list_facts` | 0.503 | 0.217 | 0.216 |
| forget my video length preference | `forget` | 0.680 | 0.521 | 0.298 |
| **best-of-bests total** | | **60.47** | **55.72** | **18.42** |
| **best-of-bests avg** | | **3.023** | **2.786** | **0.921** |

## 2. Latest run — per-prompt totals

| prompt | tool | python_custom_json | python_hermes_xml | python_pydantic_ai |
|---|---|---:|---:|---:|
| what time is it | `get_time` | 1.359 | 2.936 | 2.865 |
| calculate 47 times 23 plus 12 | `calculate` | 1.107 | 0.673 | 0.461 |
| list the workspace | `list_directory` | 0.654 | 0.518 | 1.287 |
| make a file called bench.txt with the message he... | `create_file` | 1.726 | 1.147 | 0.535 |
| read bench.txt out loud | `speak_file` | 3.479 | 2.992 | 2.755 |
| search the web for recent news about local llms | `web_search` | 7.302 | 7.222 | 5.441 |
| tell me a one sentence story about a robot | `(free-text)` | 1.841 | 0.546 | 0.408 |
| delete bench.txt | `delete_file` | 1.082 | 0.882 | 0.341 |
| what is the cpu and disk status of this machine | `system_status` | 0.900 | 0.505 | 0.245 |
| what time is it in shanghai | `get_time` | 0.768 | 0.573 | 0.346 |
| search the web for trending youtube topics about... | `web_search` | 4.661 | 4.828 | 6.212 |
| write a 4 sentence youtube intro script about a ... | `create_file` | 5.808 | 2.609 | 3.050 |
| append a closing line to youtube_intro.txt askin... | `append_file` | 2.273 | 1.360 | 0.592 |
| narrate youtube_intro.txt out loud as if you are... | `speak_file` | 28.330 | 27.699 | 0.895 |
| come up with a catchy youtube title for a video ... | `(free-text)` | 0.330 | 3.902 | 0.320 |
| delete youtube_intro.txt | `delete_file` | 1.246 | 0.973 | 0.558 |
| remember that my preferred youtube video length ... | `remember` | 1.184 | 0.769 | 0.173 |
| what video length do I prefer? | `recall` | 0.741 | 0.555 | 0.650 |
| what do you know about me? | `list_facts` | 0.528 | 0.223 | 0.720 |
| forget my video length preference | `forget` | 0.736 | 0.546 | 0.567 |
| **TOTAL** | | **66.05** | **61.46** | **28.42** |
| **AVG / prompt** | | **3.303** | **3.073** | **1.421** |

## 3. Per-tool average seconds (latest run)

| tool | n prompts | python_custom_json avg | python_hermes_xml avg | python_pydantic_ai avg |
|---|---:|---:|---:|---:|
| `append_file` | 1 | 2.273 | 1.360 | 0.592 |
| `calculate` | 1 | 1.107 | 0.673 | 0.461 |
| `create_file` | 2 | 3.767 | 1.878 | 1.792 |
| `delete_file` | 2 | 1.164 | 0.927 | 0.450 |
| `forget` | 1 | 0.736 | 0.546 | 0.567 |
| `get_time` | 2 | 1.063 | 1.754 | 1.606 |
| `list_directory` | 1 | 0.654 | 0.518 | 1.287 |
| `list_facts` | 1 | 0.528 | 0.223 | 0.720 |
| `recall` | 1 | 0.741 | 0.555 | 0.650 |
| `remember` | 1 | 1.184 | 0.769 | 0.173 |
| `speak_file` | 2 | 15.905 | 15.345 | 1.825 |
| `system_status` | 1 | 0.900 | 0.505 | 0.245 |
| `web_search` | 2 | 5.981 | 6.025 | 5.827 |
| `(free-text)` | 2 | 1.086 | 2.224 | 0.364 |

## 4. Per-framework historical trend (last 5 runs)

Each framework's latencies across the most recent default-mode runs. Spot regressions and improvements over time.

### python_custom_json

| prompt | r3 | r4 | r5 | r6 | r7 |
|---|---:|---:|---:|---:|---:|
| what time is it | 1.378 | 1.393 | 1.333 | 1.365 | 1.359 |
| calculate 47 times 23 plus 12 | 1.124 | 1.110 | 1.121 | 1.110 | 1.107 |
| list the workspace | 0.646 | 0.639 | 0.627 | 0.660 | 0.654 |
| make a file called bench.txt with the message ... | 1.769 | 1.610 | 1.660 | 1.701 | 1.726 |
| read bench.txt out loud | 3.416 | 3.493 | 5.251 | 3.434 | 3.479 |
| search the web for recent news about local llm... | 11.435 | 6.116 | 6.182 | 4.999 | 7.302 |
| tell me a one sentence story about a robot | 1.696 | 1.717 | 1.847 | 1.826 | 1.841 |
| delete bench.txt | 1.054 | 1.066 | 1.143 | 1.104 | 1.082 |
| what is the cpu and disk status of this machin... | 0.937 | 0.894 | 0.970 | 0.925 | 0.900 |
| what time is it in shanghai | 0.776 | 0.813 | 0.754 | 0.775 | 0.768 |
| search the web for trending youtube topics abo... | 9.503 | 6.471 | 5.418 | 5.009 | 4.661 |
| write a 4 sentence youtube intro script about ... | 5.791 | 6.038 | 6.567 | 5.992 | 5.808 |
| append a closing line to youtube_intro.txt ask... | 2.135 | 2.209 | 2.188 | 2.239 | 2.273 |
| narrate youtube_intro.txt out loud as if you a... | 30.537 | 28.189 | 28.702 | 28.415 | 28.330 |
| come up with a catchy youtube title for a vide... | 0.320 | 0.320 | 0.327 | 9.594 | 0.330 |
| delete youtube_intro.txt | 1.327 | 1.235 | 1.255 | 1.226 | 1.246 |
| remember that my preferred youtube video lengt... | 1.132 | 1.141 | 1.116 | 1.141 | 1.184 |
| what video length do I prefer? | 0.785 | 0.740 | 0.720 | 0.752 | 0.741 |
| what do you know about me? | 0.547 | 0.525 | 0.504 | 0.523 | 0.528 |
| forget my video length preference | 0.726 | 0.704 | 0.705 | 0.711 | 0.736 |

Run IDs: `r3`=`2026-05-13T18:10:47+00:00`, `r4`=`2026-05-13T20:10:03+00:00`, `r5`=`2026-05-17T16:05:11+00:00`, `r6`=`2026-05-17T18:49:44+00:00`, `r7`=`2026-05-17T19:46:32+00:00`

### python_hermes_xml

| prompt | r3 | r4 | r5 | r6 | r7 |
|---|---:|---:|---:|---:|---:|
| what time is it | 2.923 | 2.917 | 2.914 | 2.932 | 2.936 |
| calculate 47 times 23 plus 12 | 0.660 | 0.666 | 0.678 | 0.668 | 0.673 |
| list the workspace | 0.503 | 0.507 | 0.511 | 0.511 | 0.518 |
| make a file called bench.txt with the message ... | 1.115 | 1.125 | 1.135 | 1.128 | 1.147 |
| read bench.txt out loud | 2.923 | 2.912 | 2.955 | 2.953 | 2.992 |
| search the web for recent news about local llm... | 9.476 | 5.549 | 5.319 | 5.263 | 7.222 |
| tell me a one sentence story about a robot | 0.476 | 0.480 | 0.497 | 0.491 | 0.546 |
| delete bench.txt | 0.839 | 0.866 | 0.876 | 0.868 | 0.882 |
| what is the cpu and disk status of this machin... | 0.482 | 0.500 | 0.504 | 0.498 | 0.505 |
| what time is it in shanghai | 0.549 | 0.549 | 0.600 | 0.554 | 0.573 |
| search the web for trending youtube topics abo... | 9.826 | 5.022 | 5.118 | 4.885 | 4.828 |
| write a 4 sentence youtube intro script about ... | 2.181 | 2.398 | 2.587 | 2.408 | 2.609 |
| append a closing line to youtube_intro.txt ask... | 1.294 | 1.296 | 1.340 | 1.293 | 1.360 |
| narrate youtube_intro.txt out loud as if you a... | 27.973 | 30.009 | 27.926 | 30.813 | 27.699 |
| come up with a catchy youtube title for a vide... | 3.829 | 3.913 | 3.921 | 2.013 | 3.902 |
| delete youtube_intro.txt | 0.934 | 0.951 | 0.963 | 0.924 | 0.973 |
| remember that my preferred youtube video lengt... | 0.732 | 0.746 | 0.759 | 0.694 | 0.769 |
| what video length do I prefer? | 0.531 | 0.542 | 0.546 | 0.541 | 0.555 |
| what do you know about me? | 0.217 | 0.219 | 0.224 | 0.476 | 0.223 |
| forget my video length preference | 0.521 | 0.533 | 0.541 | 0.532 | 0.546 |

Run IDs: `r3`=`2026-05-13T18:10:47+00:00`, `r4`=`2026-05-13T20:10:03+00:00`, `r5`=`2026-05-17T16:05:11+00:00`, `r6`=`2026-05-17T18:49:44+00:00`, `r7`=`2026-05-17T19:46:32+00:00`

### python_pydantic_ai

| prompt | r5 | r6 | r7 | r8 | r9 |
|---|---:|---:|---:|---:|---:|
| what time is it | 1.922 | 1.494 | 2.847 | 2.866 | 2.865 |
| calculate 47 times 23 plus 12 | 0.667 | 0.436 | 0.472 | 0.462 | 0.461 |
| list the workspace | 0.886 | 0.882 | 0.931 | 0.937 | 1.287 |
| make a file called bench.txt with the message ... | 0.733 | 0.503 | 0.533 | 0.534 | 0.535 |
| read bench.txt out loud | 3.214 | 3.153 | 2.741 | 2.728 | 2.755 |
| search the web for recent news about local llm... | 4.075 | 3.779 | 3.677 | 3.370 | 5.441 |
| tell me a one sentence story about a robot | 0.400 | 0.390 | 0.419 | 0.421 | 0.408 |
| delete bench.txt | 0.558 | 0.326 | 0.339 | 0.351 | 0.341 |
| what is the cpu and disk status of this machin... | 1.687 | 0.633 | 0.243 | 0.245 | 0.245 |
| what time is it in shanghai | 0.699 | 0.327 | 0.367 | 0.362 | 0.346 |
| search the web for trending youtube topics abo... | 3.682 | 4.265 | 4.851 | 7.224 | 6.212 |
| write a 4 sentence youtube intro script about ... | 1.669 | 1.330 | 1.452 | 3.130 | 3.050 |
| append a closing line to youtube_intro.txt ask... | 0.843 | 0.607 | 0.649 | 0.592 | 0.592 |
| narrate youtube_intro.txt out loud as if you a... | 25.271 | 26.028 | 32.349 | 0.904 | 0.895 |
| come up with a catchy youtube title for a vide... | 0.326 | 0.338 | 2.815 | 0.318 | 0.320 |
| delete youtube_intro.txt | 0.631 | 0.360 | 0.374 | 0.557 | 0.558 |
| remember that my preferred youtube video lengt... | 0.725 | 0.505 | 0.476 | 0.173 | 0.173 |
| what video length do I prefer? | 0.473 | 0.220 | 3.917 | 0.650 | 0.650 |
| what do you know about me? | 0.759 | 0.216 | 1.330 | 0.722 | 0.720 |
| forget my video length preference | 0.708 | 0.298 | 0.309 | 0.566 | 0.567 |

Run IDs: `r5`=`2026-05-14T02:47:47+00:00`, `r6`=`2026-05-14T05:13:40+00:00`, `r7`=`2026-05-17T16:05:11+00:00`, `r8`=`2026-05-17T18:49:44+00:00`, `r9`=`2026-05-17T19:46:32+00:00`

## Headlines

- Latest fastest: **python_pydantic_ai** (28.42s total, 1.421s avg).
- Latest slowest: **python_custom_json** (66.05s total, 3.303s avg).
- Latest gap: 1.882s/prompt (132.4% slower).
- Best-record holder (lowest avg across personal bests): **python_pydantic_ai** (0.921s avg).

## Per-prompt total seconds

| prompt | tool | python_custom_json | python_hermes_xml | python_pydantic_ai |
|---|---|---:|---:|---:|
| what time is it | `get_time` | 1.359 | 2.936 | 2.865 |
| calculate 47 times 23 plus 12 | `calculate` | 1.107 | 0.673 | 0.461 |
| list the workspace | `list_directory` | 0.654 | 0.518 | 1.287 |
| make a file called bench.txt with the message he... | `create_file` | 1.726 | 1.147 | 0.535 |
| read bench.txt out loud | `speak_file` | 3.479 | 2.992 | 2.755 |
| search the web for recent news about local llms | `web_search` | 7.302 | 7.222 | 5.441 |
| tell me a one sentence story about a robot | `(free-text)` | 1.841 | 0.546 | 0.408 |
| delete bench.txt | `delete_file` | 1.082 | 0.882 | 0.341 |
| what is the cpu and disk status of this machine | `system_status` | 0.900 | 0.505 | 0.245 |
| what time is it in shanghai | `get_time` | 0.768 | 0.573 | 0.346 |
| search the web for trending youtube topics about... | `web_search` | 4.661 | 4.828 | 6.212 |
| write a 4 sentence youtube intro script about a ... | `create_file` | 5.808 | 2.609 | 3.050 |
| append a closing line to youtube_intro.txt askin... | `append_file` | 2.273 | 1.360 | 0.592 |
| narrate youtube_intro.txt out loud as if you are... | `speak_file` | 28.330 | 27.699 | 0.895 |
| come up with a catchy youtube title for a video ... | `(free-text)` | 0.330 | 3.902 | 0.320 |
| delete youtube_intro.txt | `delete_file` | 1.246 | 0.973 | 0.558 |
| remember that my preferred youtube video length ... | `remember` | 1.184 | 0.769 | 0.173 |
| what video length do I prefer? | `recall` | 0.741 | 0.555 | 0.650 |
| what do you know about me? | `list_facts` | 0.528 | 0.223 | 0.720 |
| forget my video length preference | `forget` | 0.736 | 0.546 | 0.567 |
| **TOTAL** | | **66.05** | **61.46** | **28.42** |
| **AVG / prompt** | | **3.303** | **3.073** | **1.421** |

## Per-tool average seconds (across the latest run)

Each row groups prompts by the tool they were expected to call. `(free-text)` means no tool — model answered directly.

| tool | n prompts | python_custom_json avg | python_hermes_xml avg | python_pydantic_ai avg |
|---|---:|---:|---:|---:|
| `append_file` | 1 | 2.273 | 1.360 | 0.592 |
| `calculate` | 1 | 1.107 | 0.673 | 0.461 |
| `create_file` | 2 | 3.767 | 1.878 | 1.792 |
| `delete_file` | 2 | 1.164 | 0.927 | 0.450 |
| `forget` | 1 | 0.736 | 0.546 | 0.567 |
| `get_time` | 2 | 1.063 | 1.754 | 1.606 |
| `list_directory` | 1 | 0.654 | 0.518 | 1.287 |
| `list_facts` | 1 | 0.528 | 0.223 | 0.720 |
| `recall` | 1 | 0.741 | 0.555 | 0.650 |
| `remember` | 1 | 1.184 | 0.769 | 0.173 |
| `speak_file` | 2 | 15.905 | 15.345 | 1.825 |
| `system_status` | 1 | 0.900 | 0.505 | 0.245 |
| `web_search` | 2 | 5.981 | 6.025 | 5.827 |
| `(free-text)` | 2 | 1.086 | 2.224 | 0.364 |

## Headlines

- Fastest framework on this run: **python_pydantic_ai** (28.42s total, 1.421s avg).
- Slowest: **python_custom_json** (66.05s total, 3.303s avg).
- Gap: 1.882s/prompt (132.4% slower).

See `benchmark/BENCH_RESULTS.md` for the historical view and per-mode breakdown (default / mcp / think / memory / mcp+think+memory).