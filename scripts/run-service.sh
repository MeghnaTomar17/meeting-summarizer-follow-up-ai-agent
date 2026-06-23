#!/usr/bin/env bash
# MannerAI — run a backend service locally in venv
# Usage: ./scripts/run-service.sh gateway|meeting|ai|search|worker

set -euo pipefail

SERVICE="${1:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "$ROOT/.venv/bin/python" ]]; then
  echo "Virtual env not found. Run ./scripts/setup.sh first." >&2
  exit 1
fi

case "$SERVICE" in
  gateway) DIR="backend/gateway-service"; MODULE="app.main:app"; PORT=8000 ;;
  meeting) DIR="backend/meeting-service"; MODULE="app.main:app"; PORT=8001 ;;
  ai)      DIR="backend/ai-service";      MODULE="main:app";      PORT=8002 ;;
  search)  DIR="backend/search-service";  MODULE="main:app";      PORT=8003 ;;
  worker)  DIR="backend/worker-service";  MODULE="main:app";      PORT=8004 ;;
  *)
    echo "Usage: $0 gateway|meeting|ai|search|worker" >&2
    exit 1
    ;;
esac

export PYTHONPATH="$ROOT/backend"
cd "$ROOT/$DIR"

echo "Starting ${SERVICE}-service on port ${PORT}..."
exec "$ROOT/.venv/bin/python" -m uvicorn "$MODULE" --host 0.0.0.0 --port "$PORT" --reload
