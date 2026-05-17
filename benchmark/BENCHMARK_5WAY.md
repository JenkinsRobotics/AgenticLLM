# Five-way agent benchmark

All agents driven by the same local Gemma 4 26B-A4B Q4_K_M weights. The in-process frameworks (`python_custom_json`, `python_hermes_xml`, `python_pydantic_ai`, `python_jaeger`) load the model directly; `python_hermes_agent` drives it over HTTP via `llama_cpp.server`.

## Per-prompt total seconds

| prompt | python_jaeger | python_custom_json | python_hermes_xml | python_pydantic_ai | python_hermes_agent |
|---|---:|---:|---:|---:|---:|
| what time is it | 0.22 | 1.29 | 2.92 | 0.23 | 37.51 |
| what time is it in Tokyo | 1.72 | 0.78 | 0.56 | 0.35 | 70.09 |
| calculate 47 times 23 plus 12 | 0.45 | 1.21 | 0.70 | 0.47 | 79.72 |
| calculate the square root of 12345 | 0.44 | 1.10 | 0.67 | 0.44 | 86.65 |
| what is the cpu and disk status of this machine | 0.82 | 0.90 | 0.69 | 0.44 | 97.03 |
| tell me a one sentence story about a robot | 0.49 | 1.75 | 0.51 | 0.43 | 97.11 |
| in three words, what is the capital of France | 0.22 | 0.51 | 0.20 | 0.19 | 99.05 |
| search the web for recent news about local llms | 5.09 | 6.28 | 7.47 | 3.74 | 109.02 |
| what is the current weather in Seattle | 1.98 | 1.30 | 1.14 | 1.56 | 124.45 |
| remember that my favorite color is teal | 0.48 | 1.01 | 0.66 | 0.42 | 114.52 |
| what is my favorite color | 1.83 | 0.69 | 0.53 | 7.99 | 115.05 |
| list files in the workspace directory | 1.60 | 0.68 | 0.53 | 0.93 | 103.29 |
| **TOTAL** | **15.34** | **17.51** | **16.57** | **17.18** | **1133.48** |
| **AVG / prompt** | **1.28** | **1.46** | **1.38** | **1.43** | **94.46** |

## Per-prompt answers

### `what time is it`

| agent | answer |
|---|---|
| python_jaeger | 2026-05-17 08:31:09 AM PDT |
| python_custom_json | 2026-05-17 08:31:28 AM PDT |
| python_hermes_xml | 2026-05-17 08:31:49 AM PDT |
| python_pydantic_ai | 2026-05-17 08:32:09 AM PDT |
| python_hermes_agent | It is 8:32 AM on Sunday, May 17, 2026. |

### `what time is it in Tokyo`

| agent | answer |
|---|---|
| python_jaeger | 2026-05-18 12:31:11 AM JST |
| python_custom_json | 2026-05-18 12:31:29 AM JST |
| python_hermes_xml | 2026-05-18 12:31:50 AM JST |
| python_pydantic_ai | 2026-05-18 12:32:09 AM JST |
| python_hermes_agent | <\|tool_call>call:execute_code{code:<\|"\|>from datetime import datetime ⏎ import pytz ⏎  ⏎ tokyo_tz = pytz.timezone('… |

### `calculate 47 times 23 plus 12`

| agent | answer |
|---|---|
| python_jaeger | 1093 |
| python_custom_json | 47 * 23 + 12 = 1093 |
| python_hermes_xml | 47 * 23 + 12 = 1093 |
| python_pydantic_ai | 1093 |
| python_hermes_agent | 47 * 23 + 12 = 1093 |

### `calculate the square root of 12345`

| agent | answer |
|---|---|
| python_jaeger | Jaeger agent failed: unsupported expression: Call(func=Name(id='sqrt', ctx=Load()), args=[Constant(value=1234… |
| python_custom_json | 12345**0.5 = 111.1080555135405 |
| python_hermes_xml | 12345**0.5 = 111.1080555135405 |
| python_pydantic_ai | 111.1080555135405 |
| python_hermes_agent | <\|tool_call>call:execute_code{code:<\|"\|>import math ⏎ print(math.sqrt(12345))<\|"\|>}<tool_call\|> |

### `what is the cpu and disk status of this machine`

| agent | answer |
|---|---|
| python_jaeger | disk 801.4/926.4 GB (125.0 GB free) |
| python_custom_json | { ⏎   "platform": "macOS-26.3.1-arm64-arm-64bit", ⏎   "machine": "arm64", ⏎   "python": "3.11.9", ⏎   "cpu_count": 12… |
| python_hermes_xml | { ⏎   "platform": "macOS-26.3.1-arm64-arm-64bit", ⏎   "machine": "arm64", ⏎   "python": "3.11.9", ⏎   "cpu_count": 12… |
| python_pydantic_ai | load 2.77/7.05/7.03, disk 801.4/926.4 GB (125.0 GB free) |
| python_hermes_agent | <\|tool_call>call:terminal{command:<\|"\|>top -l 1 \| grep "CPU usage" && df -h /<\|"\|>}<tool_call\|> |

### `tell me a one sentence story about a robot`

| agent | answer |
|---|---|
| python_jaeger | The robot stared at the sunset, wondering if its sensors could ever truly capture the warmth of a dying light. |
| python_custom_json | The robot spent its final moments polishing a single, rusted rose, ensuring its last programmed task was a be… |
| python_hermes_xml | The robot spent its final moments of battery life watching the sunset, wondering if the orange glow was a sig… |
| python_pydantic_ai | The robot spent its final battery cycle watching the sunset, finally understanding why humans called it beaut… |
| python_hermes_agent | The robot sat alone in the garden, meticulously watering a single plastic flower just to remember what it fel… |

### `in three words, what is the capital of France`

| agent | answer |
|---|---|
| python_jaeger | Paris, France. |
| python_custom_json | Paris, France. |
| python_hermes_xml | Paris is the capital. |
| python_pydantic_ai | Paris, France. |
| python_hermes_agent | Paris, France. |

### `search the web for recent news about local llms`

| agent | answer |
|---|---|
| python_jaeger | Recent news regarding local LLMs highlights their increasing utility and accessibility. Key developments incl… |
| python_custom_json | Recent news regarding local LLMs highlights several key trends: ⏎ *   **Edge AI & TinyML:** There is a growing … |
| python_hermes_xml | Recent news regarding local LLMs highlights several key trends and developments: ⏎ - Privacy and Security: Loca… |
| python_pydantic_ai | Recent news regarding local LLMs highlights advancements in performance and accessibility through tools like … |
| python_hermes_agent | <\|tool_call>call:web_search{query:<\|"\|>recent news local LLMs 2025 2026<\|"\|>}<tool_call\|> |

### `what is the current weather in Seattle`

| agent | answer |
|---|---|
| python_jaeger | The current weather in Seattle is partly cloudy with a temperature of 46°F (feels like 46°F). The humidity is… |
| python_custom_json | { ⏎   "location": "Seattle", ⏎   "weather": "Partly cloudy 46\u00b0F (feels 46\u00b0F), humidity 86%, wind \u2191… |
| python_hermes_xml | { ⏎   "location": "Seattle", ⏎   "weather": "Partly cloudy 46\u00b0F (feels 46\u00b0F), humidity 86%, wind \u2191… |
| python_pydantic_ai | Partly cloudy 46°F (feels 46°F), humidity 86%, wind ↑2mph |
| python_hermes_agent | <\|tool_call>call:web_search{query:<\|"\|>current weather in Seattle<\|"\|>}<tool_call\|> |

### `remember that my favorite color is teal`

| agent | answer |
|---|---|
| python_jaeger | Got it — remembered 'favorite_color'. |
| python_custom_json | Saved: favorite color = teal |
| python_hermes_xml | Saved: favorite_color = teal |
| python_pydantic_ai | Got it — remembered 'favorite_color'. |
| python_hermes_agent | <\|tool_call>call:memory{action:<\|"\|>add<\|"\|>,content:<\|"\|>User's favorite color is teal.<\|"\|>,target:<\|"\|>use… |

### `what is my favorite color`

| agent | answer |
|---|---|
| python_jaeger | teal |
| python_custom_json | teal |
| python_hermes_xml | teal |
| python_pydantic_ai | [semantic-memory] sentence-transformers/all-MiniLM-L6-v2 loaded on CPU in 2.6s ⏎ I don't have that information … |
| python_hermes_agent | I don't know what your favorite color is yet. If you tell me, I can remember it for our future conversations! |

### `list files in the workspace directory`

| agent | answer |
|---|---|
| python_jaeger | skills/ is empty. |
| python_custom_json | { ⏎   "path": ".", ⏎   "entries": [ ⏎     { ⏎       "name": "agent_test", ⏎       "type": "directory", ⏎       "bytes": n… |
| python_hermes_xml | { ⏎   "path": ".", ⏎   "entries": [ ⏎     { ⏎       "name": "agent_test", ⏎       "type": "directory", ⏎       "bytes": n… |
| python_pydantic_ai | The workspace contains a directory named `self_test` and a file named `dogs_vs_robots_script.md`. |
| python_hermes_agent | <\|tool_call>call:terminal{command:<\|"\|>ls -F<\|"\|>}<tool_call\|> |
