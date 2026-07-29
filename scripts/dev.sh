#!/usr/bin/env bash
set -euo pipefail

echo "=== J.A.R.V.I.S. Development Environment ==="

if [ ! -f .env ]; then
    echo "No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "Edit .env with your settings before running."
fi

if ! command -v graphify &> /dev/null; then
    echo "Installing graphifyy (codebase knowledge graph)..."
    pip install graphifyy 2>/dev/null
    graphify install --project --platform opencode 2>/dev/null
fi

docker compose up --build -d
echo "Services starting. Check status with: docker compose ps"
