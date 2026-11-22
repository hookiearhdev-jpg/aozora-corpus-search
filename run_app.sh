#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

echo "============================================================"
echo "  青空文庫「中納言風」短単位コーパス検索 Webアプリ 起動"
echo "  FastAPI : http://127.0.0.1:8000 (Docs: /docs)"
echo "  Next.js : http://localhost:3000"
echo "============================================================"

cleanup() {
  echo ""
  echo "サーバーを停止しています..."
  kill "${API_PID:-}" "${WEB_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [ -x ".venv/Scripts/uvicorn.exe" ]; then
  UVICORN=".venv/Scripts/uvicorn.exe"
elif [ -x ".venv/bin/uvicorn" ]; then
  UVICORN=".venv/bin/uvicorn"
else
  UVICORN="uvicorn"
fi

"$UVICORN" src.api.main:app --host 127.0.0.1 --port 8000 --reload &
API_PID=$!

(cd "$ROOT_DIR/src/frontend_next" && npm run dev) &
WEB_PID=$!

wait
