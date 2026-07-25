#!/usr/bin/env bash
# Maakt een distribueerbaar tar-archief van de app (zonder lokale rommel).
# Gebruik: ./deploy/package.sh [uitvoerpad.tgz]
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=${1:-transcribe_service-$(git rev-parse --short HEAD 2>/dev/null || echo dist).tgz}

# Sluit uit: git, secrets, data, caches, venvs, build-output.
tar --exclude='.git' \
    --exclude='.env' \
    --exclude='.env.bak.*' \
    --exclude='data' \
    --exclude='*/__pycache__' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='.venv' --exclude='venv' \
    --exclude='node_modules' \
    -czf "$OUT" \
    docker-compose.yml Caddyfile .env.example PROMPTS.md README.md LICENSE \
    backend frontend deploy docs

echo "Archief geschreven: $OUT"
echo "Op de prod-machine:  tar xzf $(basename "$OUT") && cd <map> && ./deploy/install.sh"
