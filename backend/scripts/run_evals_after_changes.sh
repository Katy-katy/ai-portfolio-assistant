#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

CHANGED_FILES="$(git diff --name-only HEAD -- app/agent.py app/multi_agent.py knowledge || true)"

if [[ -z "$CHANGED_FILES" ]]; then
  echo "No prompt/knowledge changes detected. Skipping eval run."
  exit 0
fi

echo "Detected prompt/knowledge changes:"
echo "$CHANGED_FILES"
echo "Running golden eval suite..."

uv run python scripts/run_evals.py "$@"
