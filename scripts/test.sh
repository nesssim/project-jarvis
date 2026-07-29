#!/usr/bin/env bash
set -euo pipefail

export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/shared/src:$(pwd)/services/orchestrator/src:$(pwd)/services/stt/src:$(pwd)/services/tts/src:$(pwd)/services/memory/src:$(pwd)/services/tools/src"

echo "=== Running tests ==="
python -m pytest tests/ \
    --cov=shared \
    --cov=services \
    --cov-report=term-missing \
    --cov-fail-under=80 \
    -v "$@"
echo "All tests passed."
