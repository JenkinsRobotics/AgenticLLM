# Four-way agent benchmark

All four agents driven by the same local Gemma 4 26B-A4B Q4_K_M weights. The first three load the model in-process; `python_hermes_agent` drives it over HTTP via `llama_cpp.server`.

## Per-prompt total seconds

| prompt | python_pydantic_ai |
|---|---:|
| what time is it | 0.23 |
| calculate 47 times 23 plus 12 | 0.44 |
| tell me a one sentence story about a robot | 0.40 |
| search the web for recent news about local llms | 4.21 |
| list files in the workspace directory | 0.90 |
| **TOTAL** | **6.18** |
| **AVG / prompt** | **1.24** |

## Per-prompt answers

### `what time is it`

| agent | answer |
|---|---|
| python_pydantic_ai | 2026-05-16 06:14:02 PM PDT |

### `calculate 47 times 23 plus 12`

| agent | answer |
|---|---|
| python_pydantic_ai | 1093 |

### `tell me a one sentence story about a robot`

| agent | answer |
|---|---|
| python_pydantic_ai | The robot spent its final battery cycle watching the sunset, finally understanding why humans called it beaut… |

### `search the web for recent news about local llms`

| agent | answer |
|---|---|
| python_pydantic_ai | Recent news and discussions regarding local LLMs highlight a significant rise in community development and th… |

### `list files in the workspace directory`

| agent | answer |
|---|---|
| python_pydantic_ai | The workspace contains a directory named `self_test` and a file named `dogs_vs_robots_script.md`. |
