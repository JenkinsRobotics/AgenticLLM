# Four-way agent benchmark

All four agents driven by the same local Gemma 4 26B-A4B Q4_K_M weights. The first three load the model in-process; `python_hermes_agent` drives it over HTTP via `llama_cpp.server`.

## Per-prompt total seconds

| prompt | python_custom_json | python_hermes_xml | python_pydantic_ai | python_hermes_agent |
|---|---:|---:|---:|---:|
| what time is it | 1.30 | 2.88 | 1.51 | 3.34 |
| calculate 47 times 23 plus 12 | 1.22 | 0.66 | 0.44 | 4.44 |
| tell me a one sentence story about a robot | 1.82 | 0.48 | 0.39 | 2.48 |
| search the web for recent news about local llms | 7.11 | 4.72 | 3.36 | 1.86 |
| list files in the workspace directory | 0.69 | 0.51 | 0.88 | 2.12 |
| **TOTAL** | **12.14** | **9.26** | **6.58** | **14.24** |
| **AVG / prompt** | **2.43** | **1.85** | **1.32** | **2.85** |

## Per-prompt answers

### `what time is it`

| agent | answer |
|---|---|
| python_custom_json | 2026-05-15 08:34:13 AM PDT |
| python_hermes_xml | 2026-05-15 08:34:29 AM PDT |
| python_pydantic_ai | 2026-05-15 08:34:40 AM PDT |
| python_hermes_agent | I do not have access to a real-time clock or your local system time, so I cannot tell you exactly what time i… |

### `calculate 47 times 23 plus 12`

| agent | answer |
|---|---|
| python_custom_json | 47 * 23 + 12 = 1093 |
| python_hermes_xml | 47 * 23 + 12 = 1093 |
| python_pydantic_ai | 1093 |
| python_hermes_agent | To calculate **47 × 23 + 12**, follow the order of operations (multiplication before addition): ⏎  ⏎ 1.  **Multip… |

### `tell me a one sentence story about a robot`

| agent | answer |
|---|---|
| python_custom_json | The robot spent its final moments polishing a single, rusted rose, ensuring its last programmed task was a be… |
| python_hermes_xml | The robot spent its final moments of battery life watching the sunset, wondering if the orange glow was a sig… |
| python_pydantic_ai | The robot spent its final battery cycle watching the sunset, finally understanding why humans called it beaut… |
| python_hermes_agent | ers |

### `search the web for recent news about local llms`

| agent | answer |
|---|---|
| python_custom_json | Recent news regarding local LLMs highlights significant advancements in performance and accessibility for 202… |
| python_hermes_xml | Recent news regarding local LLMs highlights several key developments: there are emerging stacks capable of ac… |
| python_pydantic_ai | Recent news regarding local LLMs highlights the continued evolution of tools like `llama.cpp` and Ollama, wit… |
| python_hermes_agent | (empty) |

### `list files in the workspace directory`

| agent | answer |
|---|---|
| python_custom_json | { ⏎   "path": ".", ⏎   "entries": [ ⏎     { ⏎       "name": "agent_test", ⏎       "type": "directory", ⏎       "bytes": n… |
| python_hermes_xml | { ⏎   "path": ".", ⏎   "entries": [ ⏎     { ⏎       "name": "agent_test", ⏎       "type": "directory", ⏎       "bytes": n… |
| python_pydantic_ai | The workspace contains a directory named `self_test` and a file named `dogs_vs_robots_script.md`. |
| python_hermes_agent | (empty) |
