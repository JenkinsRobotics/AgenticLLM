# Four-way agent benchmark

All four agents driven by the same local Gemma 4 26B-A4B Q4_K_M weights. The first three load the model in-process; `python_hermes_agent` drives it over HTTP via `llama_cpp.server`.

## Per-prompt total seconds

| prompt | python_custom_json | python_hermes_xml | python_pydantic_ai | python_hermes_agent |
|---|---:|---:|---:|---:|
| what time is it | 1.30 | 2.88 | 2.46 | 3.10 |
| calculate 47 times 23 plus 12 | 1.17 | 0.66 | 0.44 | 2.51 |
| tell me a one sentence story about a robot | 1.72 | 0.49 | 0.45 | 1.96 |
| search the web for recent news about local llms | 6.78 | 5.50 | 5.49 | 1.74 |
| list files in the workspace directory | 0.66 | 0.52 | 0.93 | 1.74 |
| **TOTAL** | **11.63** | **10.04** | **9.78** | **11.04** |
| **AVG / prompt** | **2.33** | **2.01** | **1.96** | **2.21** |

## Per-prompt answers

### `what time is it`

| agent | answer |
|---|---|
| python_custom_json | 2026-05-15 11:59:20 PM PDT |
| python_hermes_xml | 2026-05-15 11:59:35 PM PDT |
| python_pydantic_ai | 2026-05-15 11:59:47 PM PDT |
| python_hermes_agent | I do not have access to a real-time clock or your local system time, so I cannot tell you exactly what time i… |

### `calculate 47 times 23 plus 12`

| agent | answer |
|---|---|
| python_custom_json | 47 * 23 + 12 = 1093 |
| python_hermes_xml | 47 * 23 + 12 = 1093 |
| python_pydantic_ai | 1093 |
| python_hermes_agent | (empty) |

### `tell me a one sentence story about a robot`

| agent | answer |
|---|---|
| python_custom_json | The robot spent its final moments polishing a single, rusted rose, ensuring its last programmed task was a be… |
| python_hermes_xml | The robot spent its final moments of battery life watching the sunset, wondering if the orange glow was a sig… |
| python_pydantic_ai | The robot spent its final battery cycle watching the sunset, finally understanding why humans wrote so much p… |
| python_hermes_agent | (empty) |

### `search the web for recent news about local llms`

| agent | answer |
|---|---|
| python_custom_json | Recent news regarding local LLMs highlights several key trends: ⏎ *   **Edge AI & TinyML:** There is a growing … |
| python_hermes_xml | Recent news and discussions around local LLMs highlight a significant rise in their popularity due to acceler… |
| python_pydantic_ai | Recent news and trends in local LLMs include: ⏎ *   **Hardware Optimization:** Significant focus on maximizing … |
| python_hermes_agent | (empty) |

### `list files in the workspace directory`

| agent | answer |
|---|---|
| python_custom_json | { ⏎   "path": ".", ⏎   "entries": [ ⏎     { ⏎       "name": "agent_test", ⏎       "type": "directory", ⏎       "bytes": n… |
| python_hermes_xml | { ⏎   "path": ".", ⏎   "entries": [ ⏎     { ⏎       "name": "agent_test", ⏎       "type": "directory", ⏎       "bytes": n… |
| python_pydantic_ai | The workspace contains a directory named `self_test` and a file named `dogs_vs_robots_script.md`. |
| python_hermes_agent | (empty) |
