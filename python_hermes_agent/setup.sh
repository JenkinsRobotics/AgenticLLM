#!/usr/bin/env bash
# One-shot setup for the python_hermes_agent demo:
#   - clones NousResearch/hermes-agent into ./upstream/ (if missing)
#   - pip installs it into the project venv (editable, base extras only)
#   - links cli-config.yaml into ~/.hermes/ so the next `hermes` run
#     uses our local-Gemma settings
#
# Re-runnable: skips clone if upstream/ exists; reinstall is harmless.
set -euo pipefail

cd "$(dirname "$0")"
PROJECT_ROOT="$(cd .. && pwd)"
VENV="$PROJECT_ROOT/.venv"

if [ ! -d upstream/.git ]; then
  echo "[hermes-setup] cloning NousResearch/hermes-agent..."
  git clone --depth 1 https://github.com/NousResearch/hermes-agent.git upstream
else
  echo "[hermes-setup] upstream/ already cloned — skipping git clone."
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "[hermes-setup] missing $VENV — run the project bootstrap first." >&2
  exit 1
fi

echo "[hermes-setup] installing hermes-agent into $VENV..."
"$VENV/bin/pip" install -e upstream

mkdir -p "$HOME/.hermes"
if [ -L "$HOME/.hermes/cli-config.yaml" ] || [ -f "$HOME/.hermes/cli-config.yaml" ]; then
  echo "[hermes-setup] ~/.hermes/cli-config.yaml already exists — leaving it alone."
  echo "              to use our config: ln -sf '$PWD/cli-config.yaml' ~/.hermes/cli-config.yaml"
else
  ln -s "$PWD/cli-config.yaml" "$HOME/.hermes/cli-config.yaml"
  echo "[hermes-setup] linked $PWD/cli-config.yaml -> ~/.hermes/cli-config.yaml"
fi

echo ""
echo "Done. Next steps:"
echo "  1. Start the local LLM server:    ./start_llm.sh"
echo "  2. Run a one-shot prompt:         .venv/bin/hermes chat -Q -q 'what time is it'"
echo "  3. Or run our bench-style demo:   .venv/bin/python python_hermes_agent/run_prompt.py 'what time is it'"
