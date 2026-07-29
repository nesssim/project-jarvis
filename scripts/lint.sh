#!/usr/bin/env bash
set -euo pipefail

echo "=== Running linters ==="
echo "--- ruff ---"
ruff check shared/src/ services/ tests/
echo "--- black (check) ---"
black --check shared/src/ services/ tests/
echo "--- mypy ---"
mypy shared/src/ services/orchestrator/src/ services/stt/src/ services/tts/src/ services/memory/src/ services/tools/src/ --ignore-missing-imports
echo "All linters passed."
