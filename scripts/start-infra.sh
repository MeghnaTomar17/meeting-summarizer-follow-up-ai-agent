#!/usr/bin/env bash
# Start PostgreSQL, Redis, and Qdrant only (for local venv development)
# Usage: ./scripts/start-infra.sh

set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f ".env" ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker not found. Install Docker or start data stores manually." >&2
  exit 1
fi

echo "Starting postgres, redis, qdrant..."
docker compose up -d postgres redis qdrant

echo ""
echo "Infrastructure ready on localhost:"
echo "  PostgreSQL  localhost:5432"
echo "  Redis       localhost:6379"
echo "  Qdrant      localhost:6333"
