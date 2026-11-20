#!/usr/bin/env bash
# Avvio demo (macOS/Linux): installa le dipendenze, compila il frontend e avvia su http://localhost:8000
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q -r backend/requirements.txt
if [ ! -d frontend/dist ] || [ "${REBUILD:-0}" = "1" ]; then
  (cd frontend && npm install --no-audit --no-fund && npm run build)
fi
echo "Demo su http://localhost:8000  (LLM atteso su http://localhost:11434/v1 — modificabile in Impostazioni)"
cd backend && exec uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8000}"
