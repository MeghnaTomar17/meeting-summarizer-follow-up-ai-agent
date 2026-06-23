#!/usr/bin/env bash
# MannerAI — first-time setup on macOS/Linux (venv + dependencies)
# Usage: ./scripts/setup.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "MannerAI Meetings Platform — setup"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 not found. Install Python 3.12+ first." >&2
  exit 1
fi

echo "Using $(python3 --version)"

if [[ ! -d ".venv" ]]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — review before running services."
else
  echo ".env already exists — skipped."
fi

echo ""
echo "Setup complete."
echo "  Activate:  source .venv/bin/activate"
echo "  Gateway:   ./scripts/run-service.sh gateway"
echo "  Health:    curl http://localhost:8000/health"
