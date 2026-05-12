# Setup

## Python Environment

Use Python 3.10-3.12 for this project.

Create and activate the virtual environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the headless agentic text-mode tool test after starting a llama.cpp server:

```bash
python main.py "what time is it"
python main.py --mode natural "create notes/hello.txt with a short hello message"
```

Interactive mode:

```bash
python main.py
```

Test the safe Python tools without starting the LLM server:

```bash
python main.py --self-test
```

The CLI expects an OpenAI-compatible llama.cpp server at:

```text
http://127.0.0.1:8080
```

Override it with:

```bash
python main.py --server http://127.0.0.1:8080 "list the workspace"
```

## Local Model Requirement

The harness expects the Gemma GGUF model at:

```text
/Users/jonathanjenkins/.lmstudio/models/lmstudio-community/gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf
```

If the model lives somewhere else, pass `--model-path` to `main.py` (or update
`DEFAULT_MODEL_PATH` in `agent_test/llm_client.py`).

## Verification

After dependencies are installed, run the safe-tool self-test (no model required):

```bash
.venv/bin/python main.py --self-test
```
