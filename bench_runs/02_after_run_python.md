# Four-way agent benchmark

All four agents driven by the same local Gemma 4 26B-A4B Q4_K_M weights. The first three load the model in-process; `python_hermes_agent` drives it over HTTP via `llama_cpp.server`.

## Per-prompt total seconds

| prompt | python_pydantic_ai |
|---|---:|
| what time is it | 1.70 |
| calculate 47 times 23 plus 12 | 0.45 |
| tell me a one sentence story about a robot | 0.46 |
| search the web for recent news about local llms | 4.13 |
| list files in the workspace directory | 0.77 |
| **TOTAL** | **7.52** |
| **AVG / prompt** | **1.50** |

## Per-prompt answers

### `what time is it`

| agent | answer |
|---|---|
| python_pydantic_ai | 2026-05-15 09:05:31 AM PDT |

### `calculate 47 times 23 plus 12`

| agent | answer |
|---|---|
| python_pydantic_ai | 1093 |

### `tell me a one sentence story about a robot`

| agent | answer |
|---|---|
| python_pydantic_ai | The robot spent its final battery cycle watching the sunset, finally understanding why humans wrote so much p… |

### `search the web for recent news about local llms`

| agent | answer |
|---|---|
| python_pydantic_ai | Recent news and discussions regarding local LLMs highlight the accelerating community development and increas… |

### `list files in the workspace directory`

| agent | answer |
|---|---|
| python_pydantic_ai | self_test (directory), dogs_vs_robots_script.md (file) |
