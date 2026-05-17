# Benchmark

Last run: `2026-05-13T20:10:03+00:00` · frameworks: python_custom_json, python_hermes_xml, python_pydantic_ai

Regenerate with `python benchmark/bench.py && python benchmark/bench.py --write-results`.
Detail history: [BENCH_RESULTS.md](BENCH_RESULTS.md).

## 1. Best record per framework (lowest latency ever)

Each cell = the fastest result that framework has *ever* achieved on this prompt across all default-mode runs in `bench_history.jsonl`. Useful as a personal best target.

| prompt | tool | python_custom_json best | python_hermes_xml best | python_pydantic_ai best |
|---|---|---:|---:|---:|
| what time is it | `get_time` | 1.290 | 2.909 | 1.745 |
| calculate 47 times 23 plus 12 | `calculate` | 1.110 | 0.660 | 0.643 |
| list the workspace | `list_directory` | 0.629 | 0.503 | 0.519 |
| make a file called bench.txt with the message he... | `create_file` | 1.610 | 1.115 | 0.750 |
| read bench.txt out loud | `speak_file` | 3.295 | 2.912 | 2.956 |
| search the web for recent news about local llms | `web_search` | 6.116 | 4.517 | 5.440 |
| tell me a one sentence story about a robot | `(free-text)` | 1.696 | 0.476 | 0.398 |
| delete bench.txt | `delete_file` | 1.054 | 0.839 | 0.534 |
| what is the cpu and disk status of this machine | `system_status` | 0.891 | 0.482 | 1.084 |
| what time is it in shanghai | `get_time` | 0.750 | 0.538 | 0.616 |
| search the web for trending youtube topics about... | `web_search` | 4.536 | 4.697 | 4.489 |
| write a 4 sentence youtube intro script about a ... | `create_file` | 5.428 | 2.181 | 1.644 |
| append a closing line to youtube_intro.txt askin... | `append_file` | 2.135 | 1.294 | 0.790 |
| narrate youtube_intro.txt out loud as if you are... | `speak_file` | 26.535 | 27.925 | 22.780 |
| come up with a catchy youtube title for a video ... | `(free-text)` | 0.319 | 3.732 | 0.320 |
| delete youtube_intro.txt | `delete_file` | 1.197 | 0.929 | 0.612 |
| remember that my preferred youtube video length ... | `remember` | 1.096 | 0.730 | 0.715 |
| what video length do I prefer? | `recall` | 0.737 | 0.531 | 0.424 |
| what do you know about me? | `list_facts` | 0.503 | 0.217 | 0.700 |
| forget my video length preference | `forget` | 0.680 | 0.521 | 0.631 |
| **best-of-bests total** | | **61.61** | **57.71** | **47.79** |
| **best-of-bests avg** | | **3.080** | **2.886** | **2.389** |

## 2. Latest run — per-prompt totals

| prompt | tool | python_custom_json | python_hermes_xml | python_pydantic_ai |
|---|---|---:|---:|---:|
| what time is it | `get_time` | 1.393 | 2.917 | 1.810 |
| calculate 47 times 23 plus 12 | `calculate` | 1.110 | 0.666 | 0.673 |
| list the workspace | `list_directory` | 0.639 | 0.507 | 0.775 |
| make a file called bench.txt with the message he... | `create_file` | 1.610 | 1.125 | 0.750 |
| read bench.txt out loud | `speak_file` | 3.493 | 2.912 | 2.956 |
| search the web for recent news about local llms | `web_search` | 6.116 | 5.549 | 6.095 |
| tell me a one sentence story about a robot | `(free-text)` | 1.717 | 0.480 | 0.401 |
| delete bench.txt | `delete_file` | 1.066 | 0.866 | 0.568 |
| what is the cpu and disk status of this machine | `system_status` | 0.894 | 0.500 | 1.308 |
| what time is it in shanghai | `get_time` | 0.813 | 0.549 | 0.705 |
| search the web for trending youtube topics about... | `web_search` | 6.471 | 5.022 | 4.489 |
| write a 4 sentence youtube intro script about a ... | `create_file` | 6.038 | 2.398 | 1.736 |
| append a closing line to youtube_intro.txt askin... | `append_file` | 2.209 | 1.296 | 0.859 |
| narrate youtube_intro.txt out loud as if you are... | `speak_file` | 28.189 | 30.009 | 25.314 |
| come up with a catchy youtube title for a video ... | `(free-text)` | 0.320 | 3.913 | 0.320 |
| delete youtube_intro.txt | `delete_file` | 1.235 | 0.951 | 0.632 |
| remember that my preferred youtube video length ... | `remember` | 1.141 | 0.746 | 0.737 |
| what video length do I prefer? | `recall` | 0.740 | 0.542 | 0.530 |
| what do you know about me? | `list_facts` | 0.525 | 0.219 | 0.751 |
| forget my video length preference | `forget` | 0.704 | 0.533 | 0.699 |
| **TOTAL** | | **66.42** | **61.70** | **52.11** |
| **AVG / prompt** | | **3.321** | **3.085** | **2.605** |

## 3. Per-tool average seconds (latest run)

| tool | n prompts | python_custom_json avg | python_hermes_xml avg | python_pydantic_ai avg |
|---|---:|---:|---:|---:|
| `append_file` | 1 | 2.209 | 1.296 | 0.859 |
| `calculate` | 1 | 1.110 | 0.666 | 0.673 |
| `create_file` | 2 | 3.824 | 1.762 | 1.243 |
| `delete_file` | 2 | 1.150 | 0.908 | 0.600 |
| `forget` | 1 | 0.704 | 0.533 | 0.699 |
| `get_time` | 2 | 1.103 | 1.733 | 1.257 |
| `list_directory` | 1 | 0.639 | 0.507 | 0.775 |
| `list_facts` | 1 | 0.525 | 0.219 | 0.751 |
| `recall` | 1 | 0.740 | 0.542 | 0.530 |
| `remember` | 1 | 1.141 | 0.746 | 0.737 |
| `speak_file` | 2 | 15.841 | 16.461 | 14.135 |
| `system_status` | 1 | 0.894 | 0.500 | 1.308 |
| `web_search` | 2 | 6.293 | 5.286 | 5.292 |
| `(free-text)` | 2 | 1.019 | 2.196 | 0.361 |

## 4. Per-framework historical trend (last 5 runs)

Each framework's latencies across the most recent default-mode runs. Spot regressions and improvements over time.

### python_custom_json

| prompt | r1 | r2 | r3 | r4 |
|---|---:|---:|---:|---:|
| what time is it | 1.402 | 1.290 | 1.378 | 1.393 |
| calculate 47 times 23 plus 12 | 1.183 | 1.116 | 1.124 | 1.110 |
| list the workspace | 0.645 | 0.629 | 0.646 | 0.639 |
| make a file called bench.txt with the message ... | 1.698 | 1.622 | 1.769 | 1.610 |
| read bench.txt out loud | 3.321 | 3.295 | 3.416 | 3.493 |
| search the web for recent news about local llm... | 7.813 | 7.688 | 11.435 | 6.116 |
| tell me a one sentence story about a robot | 1.751 | 1.918 | 1.696 | 1.717 |
| delete bench.txt | 1.063 | 1.124 | 1.054 | 1.066 |
| what is the cpu and disk status of this machin... | 0.891 | 0.898 | 0.937 | 0.894 |
| what time is it in shanghai | 0.798 | 0.750 | 0.776 | 0.813 |
| search the web for trending youtube topics abo... | 5.863 | 4.536 | 9.503 | 6.471 |
| write a 4 sentence youtube intro script about ... | 5.428 | 5.819 | 5.791 | 6.038 |
| append a closing line to youtube_intro.txt ask... | 2.156 | 2.171 | 2.135 | 2.209 |
| narrate youtube_intro.txt out loud as if you a... | 26.535 | 28.238 | 30.537 | 28.189 |
| come up with a catchy youtube title for a vide... | 0.319 | 0.322 | 0.320 | 0.320 |
| delete youtube_intro.txt | 1.198 | 1.197 | 1.327 | 1.235 |
| remember that my preferred youtube video lengt... | 1.096 | 1.144 | 1.132 | 1.141 |
| what video length do I prefer? | 0.740 | 0.737 | 0.785 | 0.740 |
| what do you know about me? | 0.503 | 0.511 | 0.547 | 0.525 |
| forget my video length preference | 0.680 | 0.736 | 0.726 | 0.704 |

Run IDs: `r1`=`2026-05-13T02:41:41+00:00`, `r2`=`2026-05-13T02:53:59+00:00`, `r3`=`2026-05-13T18:10:47+00:00`, `r4`=`2026-05-13T20:10:03+00:00`

### python_hermes_xml

| prompt | r1 | r2 | r3 | r4 |
|---|---:|---:|---:|---:|
| what time is it | 2.909 | 2.936 | 2.923 | 2.917 |
| calculate 47 times 23 plus 12 | 0.666 | 0.665 | 0.660 | 0.666 |
| list the workspace | 0.508 | 0.507 | 0.503 | 0.507 |
| make a file called bench.txt with the message ... | 1.124 | 1.116 | 1.115 | 1.125 |
| read bench.txt out loud | 2.924 | 2.946 | 2.923 | 2.912 |
| search the web for recent news about local llm... | 5.299 | 4.517 | 9.476 | 5.549 |
| tell me a one sentence story about a robot | 0.505 | 0.518 | 0.476 | 0.480 |
| delete bench.txt | 0.842 | 0.864 | 0.839 | 0.866 |
| what is the cpu and disk status of this machin... | 0.482 | 0.491 | 0.482 | 0.500 |
| what time is it in shanghai | 0.538 | 0.554 | 0.549 | 0.549 |
| search the web for trending youtube topics abo... | 5.658 | 4.697 | 9.826 | 5.022 |
| write a 4 sentence youtube intro script about ... | 2.397 | 2.218 | 2.181 | 2.398 |
| append a closing line to youtube_intro.txt ask... | 1.295 | 1.354 | 1.294 | 1.296 |
| narrate youtube_intro.txt out loud as if you a... | 29.749 | 27.925 | 27.973 | 30.009 |
| come up with a catchy youtube title for a vide... | 3.732 | 3.899 | 3.829 | 3.913 |
| delete youtube_intro.txt | 0.929 | 0.955 | 0.934 | 0.951 |
| remember that my preferred youtube video lengt... | 0.730 | 0.752 | 0.732 | 0.746 |
| what video length do I prefer? | 0.534 | 0.543 | 0.531 | 0.542 |
| what do you know about me? | 0.478 | 0.222 | 0.217 | 0.219 |
| forget my video length preference | 0.535 | 0.535 | 0.521 | 0.533 |

Run IDs: `r1`=`2026-05-13T02:41:41+00:00`, `r2`=`2026-05-13T02:53:59+00:00`, `r3`=`2026-05-13T18:10:47+00:00`, `r4`=`2026-05-13T20:10:03+00:00`

### python_pydantic_ai

| prompt | r1 | r2 | r3 | r4 |
|---|---:|---:|---:|---:|
| what time is it | 1.750 | 1.745 | 1.810 | 1.810 |
| calculate 47 times 23 plus 12 | 0.847 | 0.643 | 0.668 | 0.673 |
| list the workspace | 0.520 | 0.519 | 0.631 | 0.775 |
| make a file called bench.txt with the message ... | 0.971 | 0.766 | 0.754 | 0.750 |
| read bench.txt out loud | 3.159 | 3.051 | 3.009 | 2.956 |
| search the web for recent news about local llm... | 7.390 | 5.440 | 7.910 | 6.095 |
| tell me a one sentence story about a robot | 0.527 | 0.402 | 0.398 | 0.401 |
| delete bench.txt | 0.597 | 0.534 | 0.569 | 0.568 |
| what is the cpu and disk status of this machin... | 2.226 | 1.177 | 1.084 | 1.308 |
| what time is it in shanghai | 0.711 | 0.616 | 0.698 | 0.705 |
| search the web for trending youtube topics abo... | 10.239 | 5.499 | 8.290 | 4.489 |
| write a 4 sentence youtube intro script about ... | 1.920 | 1.644 | 1.695 | 1.736 |
| append a closing line to youtube_intro.txt ask... | 1.015 | 0.790 | 0.878 | 0.859 |
| narrate youtube_intro.txt out loud as if you a... | 27.653 | 22.780 | 25.541 | 25.314 |
| come up with a catchy youtube title for a vide... | 4.661 | 0.361 | 0.327 | 0.320 |
| delete youtube_intro.txt | 0.668 | 0.612 | 0.626 | 0.632 |
| remember that my preferred youtube video lengt... | 0.955 | 0.715 | 0.729 | 0.737 |
| what video length do I prefer? | 0.940 | 0.424 | 0.524 | 0.530 |
| what do you know about me? | 1.279 | 0.700 | 0.782 | 0.751 |
| forget my video length preference | 0.635 | 0.631 | 0.685 | 0.699 |

Run IDs: `r1`=`2026-05-13T02:41:41+00:00`, `r2`=`2026-05-13T02:53:59+00:00`, `r3`=`2026-05-13T18:10:47+00:00`, `r4`=`2026-05-13T20:10:03+00:00`

## Headlines

- Latest fastest: **python_pydantic_ai** (52.11s total, 2.605s avg).
- Latest slowest: **python_custom_json** (66.42s total, 3.321s avg).
- Latest gap: 0.716s/prompt (27.5% slower).
- Best-record holder (lowest avg across personal bests): **python_pydantic_ai** (2.389s avg).

## Per-prompt total seconds

| prompt | tool | python_custom_json | python_hermes_xml | python_pydantic_ai |
|---|---|---:|---:|---:|
| what time is it | `get_time` | 1.393 | 2.917 | 1.810 |
| calculate 47 times 23 plus 12 | `calculate` | 1.110 | 0.666 | 0.673 |
| list the workspace | `list_directory` | 0.639 | 0.507 | 0.775 |
| make a file called bench.txt with the message he... | `create_file` | 1.610 | 1.125 | 0.750 |
| read bench.txt out loud | `speak_file` | 3.493 | 2.912 | 2.956 |
| search the web for recent news about local llms | `web_search` | 6.116 | 5.549 | 6.095 |
| tell me a one sentence story about a robot | `(free-text)` | 1.717 | 0.480 | 0.401 |
| delete bench.txt | `delete_file` | 1.066 | 0.866 | 0.568 |
| what is the cpu and disk status of this machine | `system_status` | 0.894 | 0.500 | 1.308 |
| what time is it in shanghai | `get_time` | 0.813 | 0.549 | 0.705 |
| search the web for trending youtube topics about... | `web_search` | 6.471 | 5.022 | 4.489 |
| write a 4 sentence youtube intro script about a ... | `create_file` | 6.038 | 2.398 | 1.736 |
| append a closing line to youtube_intro.txt askin... | `append_file` | 2.209 | 1.296 | 0.859 |
| narrate youtube_intro.txt out loud as if you are... | `speak_file` | 28.189 | 30.009 | 25.314 |
| come up with a catchy youtube title for a video ... | `(free-text)` | 0.320 | 3.913 | 0.320 |
| delete youtube_intro.txt | `delete_file` | 1.235 | 0.951 | 0.632 |
| remember that my preferred youtube video length ... | `remember` | 1.141 | 0.746 | 0.737 |
| what video length do I prefer? | `recall` | 0.740 | 0.542 | 0.530 |
| what do you know about me? | `list_facts` | 0.525 | 0.219 | 0.751 |
| forget my video length preference | `forget` | 0.704 | 0.533 | 0.699 |
| **TOTAL** | | **66.42** | **61.70** | **52.11** |
| **AVG / prompt** | | **3.321** | **3.085** | **2.605** |

## Per-tool average seconds (across the latest run)

Each row groups prompts by the tool they were expected to call. `(free-text)` means no tool — model answered directly.

| tool | n prompts | python_custom_json avg | python_hermes_xml avg | python_pydantic_ai avg |
|---|---:|---:|---:|---:|
| `append_file` | 1 | 2.209 | 1.296 | 0.859 |
| `calculate` | 1 | 1.110 | 0.666 | 0.673 |
| `create_file` | 2 | 3.824 | 1.762 | 1.243 |
| `delete_file` | 2 | 1.150 | 0.908 | 0.600 |
| `forget` | 1 | 0.704 | 0.533 | 0.699 |
| `get_time` | 2 | 1.103 | 1.733 | 1.257 |
| `list_directory` | 1 | 0.639 | 0.507 | 0.775 |
| `list_facts` | 1 | 0.525 | 0.219 | 0.751 |
| `recall` | 1 | 0.740 | 0.542 | 0.530 |
| `remember` | 1 | 1.141 | 0.746 | 0.737 |
| `speak_file` | 2 | 15.841 | 16.461 | 14.135 |
| `system_status` | 1 | 0.894 | 0.500 | 1.308 |
| `web_search` | 2 | 6.293 | 5.286 | 5.292 |
| `(free-text)` | 2 | 1.019 | 2.196 | 0.361 |

## Headlines

- Fastest framework on this run: **python_pydantic_ai** (52.11s total, 2.605s avg).
- Slowest: **python_custom_json** (66.42s total, 3.321s avg).
- Gap: 0.716s/prompt (27.5% slower).

See `benchmark/BENCH_RESULTS.md` for the historical view and per-mode breakdown (default / mcp / think / memory / mcp+think+memory).