#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python)}"

export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/shared/src:$(pwd)/services/orchestrator/src:$(pwd)/services/stt/src:$(pwd)/services/tts/src:$(pwd)/services/memory/src:$(pwd)/services/tools/src"

echo "=== Running tests ==="
"$PYTHON_BIN" -m pytest tests/ \
    --cov=shared \
    --cov=services \
    --cov-report=term-missing \
    --cov-fail-under=80 \
    -v "$@"
echo "All tests passed."
