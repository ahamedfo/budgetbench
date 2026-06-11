#!/usr/bin/env bash
# Start BudgetBench: FastAPI backend (:8000) + Next.js dashboard (:3000).
# First run only: ./run.sh --setup  (creates venv, installs, seeds demo data)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

if [[ "${1:-}" == "--setup" ]]; then
  echo "==> Backend venv + deps"
  uv venv --directory "$BACKEND" .venv --python 3.11
  uv pip install --directory "$BACKEND" --python "$BACKEND/.venv/bin/python" -e "$BACKEND"
  uv pip install --directory "$BACKEND" --python "$BACKEND/.venv/bin/python" pytest pytest-asyncio
  echo "==> Seed departments + budgets (+ Planning Analytics mock)"
  (cd "$BACKEND" && "$BACKEND/.venv/bin/python" -m scripts.seed 2026-06)
  echo "==> Frontend deps"
  (cd "$FRONTEND" && npm install --no-audit --no-fund)
  echo "Setup complete. Run ./run.sh to start."
  exit 0
fi

echo "==> Backend  → http://localhost:8000"
(cd "$BACKEND" && "$BACKEND/.venv/bin/python" -m uvicorn src.server:app --port 8000) &
BACK_PID=$!
echo "==> Frontend → http://localhost:3000"
(cd "$FRONTEND" && npm run dev) &
FRONT_PID=$!

trap 'kill $BACK_PID $FRONT_PID 2>/dev/null' EXIT INT TERM
echo "Open http://localhost:3000  (Ctrl-C to stop both)"
wait
