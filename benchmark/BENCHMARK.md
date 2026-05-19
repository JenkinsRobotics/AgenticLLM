# Benchmark

Last run: `2026-05-18T15:48:09+00:00` · frameworks: python_jaeger, python_custom_json, python_hermes_xml, python_pydantic_ai, python_hermes_agent

Regenerate with `python bench.py`. History: `bench_history.jsonl` (one row per framework × prompt × run). Raw payload: `bench_results.json`.

## 1. Best record per framework (lowest latency ever)

Each cell = the fastest result that framework has *ever* achieved on this prompt across all runs in `bench_history.jsonl`. Useful as a personal best target.

| prompt | tool | python_jaeger best | python_custom_json best | python_hermes_xml best | python_pydantic_ai best | python_hermes_agent best |
|---|---|---:|---:|---:|---:|---:|
| what time is it | `get_time` | 0.225 | 1.290 | 2.895 | 0.019 | 39.396 |
| what time is it in shanghai | `get_time` | 0.343 | 0.747 | 0.538 | 0.006 | 6.059 |
| calculate 47 times 23 plus 12 | `calculate` | 0.461 | 1.101 | 0.651 | 0.006 | 3.210 |
| calculate the square root of 12345 | `calculate` | 0.410 | 1.080 | 0.631 | 0.419 | 77.096 |
| list the workspace | `list_directory` | 1.150 | 0.627 | 0.503 | 0.005 | 92.438 |
| make a file called bench.txt with the message h... | `create_file` | 0.551 | 1.537 | 1.101 | 0.006 | 98.960 |
| read bench.txt out loud | `speak_file` | 9.819 | 3.288 | 2.912 | 0.006 | 105.582 |
| search the web for recent news about local llms | `web_search` | 4.386 | 4.999 | 4.517 | 0.006 | 101.163 |
| what is the current weather in Seattle | `get_weather` | 1.560 | 1.256 | 1.102 | 1.328 | 105.417 |
| tell me a one sentence story about a robot | `(free-text)` | 0.481 | 1.095 | 0.476 | 0.006 | 103.807 |
| in three words, what is the capital of France | `(free-text)` | 0.186 | 0.508 | 0.190 | 0.137 | 103.514 |
| delete bench.txt | `delete_file` | 0.339 | 0.877 | 0.839 | 0.006 | 104.039 |
| what is the cpu and disk status of this machine | `system_status` | 0.245 | 0.881 | 0.482 | 0.006 | 109.561 |
| search the web for trending youtube topics abou... | `web_search` | 3.766 | 1.290 | 4.285 | 0.006 | 103.918 |
| write a 4 sentence youtube intro script about a... | `create_file` | 1.596 | 5.428 | 2.168 | 0.006 | 110.332 |
| append a closing line to youtube_intro.txt aski... | `append_file` | 0.651 | 2.135 | 1.265 | 0.005 | 104.428 |
| narrate youtube_intro.txt out loud as if you ar... | `speak_file` | 27.776 | 2.342 | 24.184 | 0.005 | 107.436 |
| come up with a catchy youtube title for a video... | `(free-text)` | 2.715 | 0.319 | 0.525 | 0.005 | 117.457 |
| delete youtube_intro.txt | `delete_file` | 0.387 | 1.197 | 0.923 | 0.005 | 96.915 |
| remember that my preferred youtube video length... | `remember` | 0.527 | 1.089 | 0.583 | 0.006 | 103.204 |
| what video length do I prefer? | `recall` | 0.350 | 0.704 | 0.464 | 0.005 | 94.012 |
| what do you know about me? | `list_facts` | 0.227 | 0.503 | 0.215 | 0.004 | 101.770 |
| forget my video length preference | `forget` | 0.344 | 0.680 | 0.267 | 0.005 | 95.492 |
| **best-of-bests total** | | **58.50** | **34.97** | **51.72** | **2.01** | **2085.20** |
| **best-of-bests avg** | | **2.543** | **1.521** | **2.249** | **0.087** | **90.661** |

## 2. Latest run — per-prompt totals

| prompt | tool | python_jaeger | python_custom_json | python_hermes_xml | python_pydantic_ai | python_hermes_agent |
|---|---|---:|---:|---:|---:|---:|
| what time is it | `get_time` | 0.225 | 1.623 | 2.895 | 0.218 | 41.379 |
| what time is it in shanghai | `get_time` | 0.343 | 0.839 | 0.554 | 0.336 | 6.059 |
| calculate 47 times 23 plus 12 | `calculate` | 0.461 | 1.238 | 0.651 | 0.442 | 3.210 |
| calculate the square root of 12345 | `calculate` | 0.410 | 1.158 | 0.631 | 0.419 | 81.206 |
| list the workspace | `list_directory` | 1.150 | 0.688 | 0.504 | 1.163 | 92.438 |
| make a file called bench.txt with the message h... | `create_file` | 0.551 | 1.771 | 1.101 | 0.514 | 98.960 |
| read bench.txt out loud | `speak_file` | 9.819 | 9.585 | 11.634 | 9.416 | 105.582 |
| search the web for recent news about local llms | `web_search` | 4.386 | 6.125 | 6.248 | 5.065 | 101.163 |
| what is the current weather in Seattle | `get_weather` | 1.560 | 1.299 | 1.102 | 1.458 | 105.417 |
| tell me a one sentence story about a robot | `(free-text)` | 0.482 | 1.736 | 0.485 | 0.401 | 103.807 |
| in three words, what is the capital of France | `(free-text)` | 0.186 | 0.673 | 0.190 | 0.182 | 103.514 |
| delete bench.txt | `delete_file` | 0.339 | 1.141 | 0.851 | 0.332 | 104.039 |
| what is the cpu and disk status of this machine | `system_status` | 0.245 | 0.917 | 0.906 | 0.643 | 109.561 |
| search the web for trending youtube topics abou... | `web_search` | 3.766 | 7.633 | 4.306 | 2.056 | 106.237 |
| write a 4 sentence youtube intro script about a... | `create_file` | 1.596 | 7.057 | 2.287 | 1.011 | 110.332 |
| append a closing line to youtube_intro.txt aski... | `append_file` | 0.651 | 2.382 | 1.276 | 0.629 | 111.304 |
| narrate youtube_intro.txt out loud as if you ar... | `speak_file` | 27.776 | 31.291 | 31.478 | 16.916 | 107.436 |
| come up with a catchy youtube title for a video... | `(free-text)` | 2.715 | 11.486 | 3.767 | 3.294 | 117.457 |
| delete youtube_intro.txt | `delete_file` | 0.393 | 1.290 | 0.923 | 0.371 | 96.915 |
| remember that my preferred youtube video length... | `remember` | 0.527 | 1.159 | 0.732 | 0.518 | 103.204 |
| what video length do I prefer? | `recall` | 0.350 | 0.791 | 0.516 | 0.343 | 94.012 |
| what do you know about me? | `list_facts` | 0.227 | 0.530 | 0.215 | 0.225 | 101.770 |
| forget my video length preference | `forget` | 0.344 | 0.752 | 0.508 | 0.336 | 95.492 |
| **TOTAL** | | **58.50** | **93.16** | **73.76** | **46.29** | **2100.49** |
| **AVG / prompt** | | **2.544** | **4.051** | **3.207** | **2.012** | **91.326** |

## 3. Per-tool average seconds (latest run)

| tool | n prompts | python_jaeger avg | python_custom_json avg | python_hermes_xml avg | python_pydantic_ai avg | python_hermes_agent avg |
|---|---:|---:|---:|---:|---:|---:|
| `append_file` | 1 | 0.651 | 2.382 | 1.276 | 0.629 | 111.304 |
| `calculate` | 2 | 0.435 | 1.198 | 0.641 | 0.430 | 42.208 |
| `create_file` | 2 | 1.073 | 4.414 | 1.694 | 0.762 | 104.646 |
| `delete_file` | 2 | 0.366 | 1.215 | 0.887 | 0.351 | 100.477 |
| `forget` | 1 | 0.344 | 0.752 | 0.508 | 0.336 | 95.492 |
| `get_time` | 2 | 0.284 | 1.231 | 1.724 | 0.277 | 23.719 |
| `get_weather` | 1 | 1.560 | 1.299 | 1.102 | 1.458 | 105.417 |
| `list_directory` | 1 | 1.150 | 0.688 | 0.504 | 1.163 | 92.438 |
| `list_facts` | 1 | 0.227 | 0.530 | 0.215 | 0.225 | 101.770 |
| `recall` | 1 | 0.350 | 0.791 | 0.516 | 0.343 | 94.012 |
| `remember` | 1 | 0.527 | 1.159 | 0.732 | 0.518 | 103.204 |
| `speak_file` | 2 | 18.798 | 20.438 | 21.556 | 13.166 | 106.509 |
| `system_status` | 1 | 0.245 | 0.917 | 0.906 | 0.643 | 109.561 |
| `web_search` | 2 | 4.076 | 6.879 | 5.277 | 3.561 | 103.700 |
| `(free-text)` | 3 | 1.127 | 4.632 | 1.481 | 1.292 | 108.259 |

## 4. Per-framework historical trend (last 5 runs)

Each framework's latencies across the most recent runs. Spot regressions and improvements over time.

### python_jaeger

| prompt | r1 | r2 |
|---|---:|---:|
| what time is it | 0.230 | 0.225 |
| what time is it in shanghai | 0.369 | 0.343 |
| calculate 47 times 23 plus 12 | 0.483 | 0.461 |
| calculate the square root of 12345 | 0.444 | 0.410 |
| list the workspace | 1.189 | 1.150 |
| make a file called bench.txt with the message h... | 0.569 | 0.551 |
| read bench.txt out loud | 11.939 | 9.819 |
| search the web for recent news about local llms | 4.840 | 4.386 |
| what is the current weather in Seattle | 1.810 | 1.560 |
| tell me a one sentence story about a robot | 0.481 | 0.482 |
| in three words, what is the capital of France | 0.186 | 0.186 |
| delete bench.txt | 0.341 | 0.339 |
| what is the cpu and disk status of this machine | 0.247 | 0.245 |
| search the web for trending youtube topics abou... | 3.827 | 3.766 |
| write a 4 sentence youtube intro script about a... | 1.617 | 1.596 |
| append a closing line to youtube_intro.txt aski... | 0.676 | 0.651 |
| narrate youtube_intro.txt out loud as if you ar... | 28.407 | 27.776 |
| come up with a catchy youtube title for a video... | 2.770 | 2.715 |
| delete youtube_intro.txt | 0.387 | 0.393 |
| remember that my preferred youtube video length... | 0.538 | 0.527 |
| what video length do I prefer? | 0.355 | 0.350 |
| what do you know about me? | 0.240 | 0.227 |
| forget my video length preference | 0.360 | 0.344 |

Run IDs: `r1`=`2026-05-18T08:15:25+00:00`, `r2`=`2026-05-18T15:48:09+00:00`

### python_custom_json

| prompt | r1 | r2 | r3 | r4 | r5 |
|---|---:|---:|---:|---:|---:|
| what time is it | 1.330 | 1.440 | 1.411 | 1.322 | 1.623 |
| what time is it in shanghai | 0.779 | 0.800 | 0.747 | 0.823 | 0.839 |
| calculate 47 times 23 plus 12 | 1.101 | 1.166 | 1.116 | 1.255 | 1.238 |
| calculate the square root of 12345 | 1.127 | 1.177 | 1.122 | 1.193 | 1.158 |
| list the workspace | 0.646 | 0.660 | 0.644 | 0.686 | 0.688 |
| make a file called bench.txt with the message h... | 1.672 | 1.739 | 1.653 | 1.797 | 1.771 |
| read bench.txt out loud | 3.502 | 3.473 | 3.348 | 10.489 | 9.585 |
| search the web for recent news about local llms | 8.319 | 6.914 | 6.526 | 8.587 | 6.125 |
| what is the current weather in Seattle | 1.658 | 1.256 | 1.504 | 1.718 | 1.299 |
| tell me a one sentence story about a robot | 1.158 | 1.618 | 1.865 | 1.095 | 1.736 |
| in three words, what is the capital of France | 0.721 | 0.510 | 0.629 | 0.674 | 0.673 |
| delete bench.txt | 0.877 | 1.091 | 1.091 | 0.943 | 1.141 |
| what is the cpu and disk status of this machine | 0.924 | 0.992 | 0.881 | 0.929 | 0.917 |
| search the web for trending youtube topics abou... | 1.290 | 5.402 | 4.910 | 1.330 | 7.633 |
| write a 4 sentence youtube intro script about a... | 8.896 | 6.966 | 8.658 | 8.979 | 7.057 |
| append a closing line to youtube_intro.txt aski... | 2.337 | 2.197 | 2.251 | 2.283 | 2.382 |
| narrate youtube_intro.txt out loud as if you ar... | 2.420 | 34.509 | 2.475 | 2.342 | 31.291 |
| come up with a catchy youtube title for a video... | 5.067 | 0.326 | 5.085 | 5.417 | 11.486 |
| delete youtube_intro.txt | 1.249 | 1.284 | 1.221 | 1.292 | 1.290 |
| remember that my preferred youtube video length... | 1.268 | 1.237 | 1.222 | 1.204 | 1.159 |
| what video length do I prefer? | 1.372 | 0.747 | 1.357 | 1.368 | 0.791 |
| what do you know about me? | 1.552 | 0.532 | 1.561 | 1.521 | 0.530 |
| forget my video length preference | 1.099 | 0.747 | 1.075 | 1.071 | 0.752 |

Run IDs: `r1`=`2026-05-17T20:38:30+00:00`, `r2`=`2026-05-17T20:54:00+00:00`, `r3`=`2026-05-18T03:40:53+00:00`, `r4`=`2026-05-18T08:15:25+00:00`, `r5`=`2026-05-18T15:48:09+00:00`

### python_hermes_xml

| prompt | r1 | r2 | r3 | r4 | r5 |
|---|---:|---:|---:|---:|---:|
| what time is it | 2.936 | 2.930 | 2.912 | 2.938 | 2.895 |
| what time is it in shanghai | 0.568 | 0.569 | 0.554 | 0.582 | 0.554 |
| calculate 47 times 23 plus 12 | 0.692 | 0.683 | 0.668 | 0.694 | 0.651 |
| calculate the square root of 12345 | 0.663 | 0.658 | 0.644 | 0.670 | 0.631 |
| list the workspace | 0.527 | 0.519 | 0.511 | 0.532 | 0.504 |
| make a file called bench.txt with the message h... | 1.144 | 1.149 | 1.128 | 1.158 | 1.101 |
| read bench.txt out loud | 2.946 | 3.197 | 3.034 | 9.309 | 11.634 |
| search the web for recent news about local llms | 5.205 | 5.892 | 6.134 | 5.149 | 6.248 |
| what is the current weather in Seattle | 1.169 | 1.132 | 1.159 | 1.105 | 1.102 |
| tell me a one sentence story about a robot | 0.508 | 0.553 | 0.567 | 0.539 | 0.485 |
| in three words, what is the capital of France | 0.197 | 0.196 | 0.194 | 0.196 | 0.190 |
| delete bench.txt | 0.877 | 0.899 | 0.873 | 0.884 | 0.851 |
| what is the cpu and disk status of this machine | 0.503 | 0.944 | 0.854 | 0.875 | 0.906 |
| search the web for trending youtube topics abou... | 4.285 | 5.464 | 5.797 | 4.834 | 4.306 |
| write a 4 sentence youtube intro script about a... | 2.358 | 2.600 | 2.236 | 2.474 | 2.287 |
| append a closing line to youtube_intro.txt aski... | 1.331 | 1.373 | 1.342 | 1.305 | 1.276 |
| narrate youtube_intro.txt out loud as if you ar... | 24.184 | 27.729 | 27.791 | 28.597 | 31.478 |
| come up with a catchy youtube title for a video... | 4.195 | 3.875 | 3.760 | 3.444 | 3.767 |
| delete youtube_intro.txt | 0.957 | 0.937 | 0.957 | 0.946 | 0.923 |
| remember that my preferred youtube video length... | 0.763 | 0.731 | 0.754 | 0.719 | 0.732 |
| what video length do I prefer? | 0.550 | 0.523 | 0.543 | 0.750 | 0.516 |
| what do you know about me? | 0.223 | 0.222 | 0.223 | 1.092 | 0.215 |
| forget my video length preference | 0.537 | 0.542 | 0.538 | 0.267 | 0.508 |

Run IDs: `r1`=`2026-05-17T20:38:30+00:00`, `r2`=`2026-05-17T20:55:46+00:00`, `r3`=`2026-05-18T03:42:35+00:00`, `r4`=`2026-05-18T08:15:25+00:00`, `r5`=`2026-05-18T15:48:09+00:00`

### python_pydantic_ai

| prompt | r1 | r2 | r3 | r4 | r5 |
|---|---:|---:|---:|---:|---:|
| what time is it | 3.652 | 3.652 | 3.674 | 0.224 | 0.218 |
| what time is it in shanghai | 0.338 | 0.339 | 0.336 | 0.337 | 0.336 |
| calculate 47 times 23 plus 12 | 0.449 | 0.449 | 0.453 | 0.448 | 0.442 |
| calculate the square root of 12345 | 0.426 | 0.442 | 0.430 | 0.423 | 0.419 |
| list the workspace | 1.185 | 1.199 | 1.210 | 1.179 | 1.163 |
| make a file called bench.txt with the message h... | 0.522 | 0.547 | 0.553 | 0.514 | 0.514 |
| read bench.txt out loud | 2.856 | 2.867 | 2.842 | 9.202 | 9.416 |
| search the web for recent news about local llms | 6.979 | 6.969 | 6.946 | 6.972 | 5.065 |
| what is the current weather in Seattle | 1.550 | 1.709 | 1.689 | 1.463 | 1.458 |
| tell me a one sentence story about a robot | 0.457 | 0.408 | 0.403 | 0.401 | 0.401 |
| in three words, what is the capital of France | 0.195 | 0.187 | 0.181 | 0.184 | 0.182 |
| delete bench.txt | 0.340 | 0.347 | 0.332 | 0.339 | 0.332 |
| what is the cpu and disk status of this machine | 0.647 | 0.656 | 0.654 | 0.645 | 0.643 |
| search the web for trending youtube topics abou... | 5.211 | 5.700 | 4.003 | 4.257 | 2.056 |
| write a 4 sentence youtube intro script about a... | 1.397 | 0.985 | 1.429 | 1.409 | 1.011 |
| append a closing line to youtube_intro.txt aski... | 0.593 | 0.670 | 0.653 | 0.662 | 0.629 |
| narrate youtube_intro.txt out loud as if you ar... | 24.302 | 16.966 | 26.232 | 26.623 | 16.916 |
| come up with a catchy youtube title for a video... | 2.754 | 4.068 | 3.060 | 2.949 | 3.294 |
| delete youtube_intro.txt | 0.381 | 0.379 | 0.370 | 0.393 | 0.371 |
| remember that my preferred youtube video length... | 0.529 | 0.541 | 0.513 | 0.547 | 0.518 |
| what video length do I prefer? | 0.366 | 0.360 | 0.315 | 0.365 | 0.343 |
| what do you know about me? | 0.236 | 0.230 | 0.224 | 0.234 | 0.225 |
| forget my video length preference | 0.354 | 0.353 | 0.336 | 0.356 | 0.336 |

Run IDs: `r1`=`2026-05-18T03:08:33+00:00`, `r2`=`2026-05-18T03:29:41+00:00`, `r3`=`2026-05-18T03:44:02+00:00`, `r4`=`2026-05-18T08:15:25+00:00`, `r5`=`2026-05-18T15:48:09+00:00`

### python_hermes_agent

| prompt | r1 | r2 |
|---|---:|---:|
| what time is it | 39.396 | 41.379 |
| what time is it in shanghai | 6.616 | 6.059 |
| calculate 47 times 23 plus 12 | 71.498 | 3.210 |
| calculate the square root of 12345 | 77.096 | 81.206 |
| list the workspace | 94.799 | 92.438 |
| make a file called bench.txt with the message h... | 111.055 | 98.960 |
| read bench.txt out loud | 120.018 | 105.582 |
| search the web for recent news about local llms | 118.000 | 101.163 |
| what is the current weather in Seattle | 114.703 | 105.417 |
| tell me a one sentence story about a robot | 127.887 | 103.807 |
| in three words, what is the capital of France | 127.507 | 103.514 |
| delete bench.txt | 109.704 | 104.039 |
| what is the cpu and disk status of this machine | 113.457 | 109.561 |
| search the web for trending youtube topics abou... | 103.918 | 106.237 |
| write a 4 sentence youtube intro script about a... | 113.709 | 110.332 |
| append a closing line to youtube_intro.txt aski... | 104.428 | 111.304 |
| narrate youtube_intro.txt out loud as if you ar... | 115.539 | 107.436 |
| come up with a catchy youtube title for a video... | 138.974 | 117.457 |
| delete youtube_intro.txt | 113.583 | 96.915 |
| remember that my preferred youtube video length... | 113.348 | 103.204 |
| what video length do I prefer? | 106.076 | 94.012 |
| what do you know about me? | 115.422 | 101.770 |
| forget my video length preference | 114.638 | 95.492 |

Run IDs: `r1`=`2026-05-18T08:15:25+00:00`, `r2`=`2026-05-18T15:48:09+00:00`

## Headlines

- Latest fastest: **python_pydantic_ai** (46.29s total, 2.012s avg).
- Latest slowest: **python_hermes_agent** (2100.49s total, 91.326s avg).
- Latest gap: 89.313s/prompt (4438.0% slower).
- Best-record holder (lowest avg across personal bests): **python_pydantic_ai** (0.087s avg).

