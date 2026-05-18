# models/

**Local-only directory for LLM weights.** Symlinks or copies of large GGUF
files live here so the framework can resolve `<repo>/models/<name>.gguf`
without depending on absolute paths in your home directory.

Nothing in this directory is committed to git — see [.gitignore](.gitignore).
The contents are per-machine, set up either by symlink (recommended) or by
copy / download.

## What's here on this machine

| File | Source | How it got here |
|---|---|---|
| `gemma-4-26B-A4B-it-Q4_K_M.gguf` | LM Studio download | Symlink → `~/.lmstudio/models/lmstudio-community/gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf` |

## Why a symlink

The Gemma 4 26B-A4B Q4_K_M GGUF is **16 GB**. We do NOT want:
- Two copies on disk (16 GB + 16 GB = 32 GB)
- The file inside `.git/` (would block `git push`; LFS would charge for it)
- Different absolute paths hardcoded across `agent_doctor.py`, the per-framework
  `plugins/voice_loop.py`, `bench_worker.py`, and each instance's `config.yaml`

The symlink gives us a stable path inside the repo (`<repo>/models/<name>.gguf`)
that resolves to the canonical LM Studio file on disk. Zero disk overhead,
no git impact.

## Setting up on a fresh clone

```bash
# Option A — symlink to your LM Studio download (recommended)
ln -s ~/.lmstudio/models/lmstudio-community/gemma-4-26B-A4B-it-GGUF/gemma-4-26B-A4B-it-Q4_K_M.gguf \
      models/gemma-4-26B-A4B-it-Q4_K_M.gguf

# Option B — symlink to wherever you keep GGUFs
ln -s /path/to/your/gemma.gguf models/gemma-4-26B-A4B-it-Q4_K_M.gguf

# Option C — copy (uses 16GB local disk; not recommended unless your GGUF
# is on a remote drive and you want a local copy)
cp /path/to/your/gemma.gguf models/
```

## Pointing code at the local file

The frameworks currently resolve the model path from a few places:

| Resolver | Default | Override |
|---|---|---|
| `python_jaeger` | `<instance>/config.yaml` `model.model_path` | edit the YAML |
| `python_pydantic_ai`, `python_hermes_xml`, `python_custom_json` | hardcoded `DEFAULT_MODEL_PATH` constant | env var `HERMES_LLM_MODEL` |
| `agent_doctor.py`, `bench_worker.py` | hardcoded LM Studio path | env var `HERMES_LLM_MODEL` |

To make every framework prefer the local `models/` directory:

```bash
export HERMES_LLM_MODEL="$(pwd)/models/gemma-4-26B-A4B-it-Q4_K_M.gguf"
```

A future cleanup pass will:
1. Rename `HERMES_LLM_MODEL` → `AGENTICLLM_MODEL_PATH` (the current name predates the multi-framework split and is confusingly hermes-specific)
2. Have every framework prefer `<repo>/models/<name>.gguf` automatically if present, falling back to the LM Studio default

For now the env var is the cleanest knob.

## Adding other model files later

This directory is the right home for any GGUF / safetensors / weights you
want to share across multiple frameworks. Examples that may land here:

- Different Gemma quants (Q5_K_M, Q8_0) for quality comparisons
- Alternative base models (Llama 3.3, Qwen 2.5)
- Speculative-decoding draft models

For **plugin-specific** model files (Whisper weights, Kokoro voices,
MoonDream2), keep them inside the plugin folder or declare external paths
in `plugin.yaml`. See [docs/VOCABULARY.md → Where models and assets live on disk](../docs/VOCABULARY.md).

For **NN-trained skill weights**, bundle them inside the skill folder
(`<instance>/skills/<name>_vN/weights/`). The skill IS the weights + inference
code together — they version as one unit.
