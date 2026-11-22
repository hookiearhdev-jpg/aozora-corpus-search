@echo off
chcp 65001 > nul
setlocal

set "ROOT_DIR=%~dp0"
cd /d "%ROOT_DIR%"

echo ============================================================
echo   青空文庫「中納言風」短単位コーパス検索 Webアプリ 起動
echo   FastAPI : http://127.0.0.1:8000 (Docs: /docs)
echo   Next.js : http://localhost:3000
echo ============================================================

start "Aozora FastAPI Backend" cmd /k ""%ROOT_DIR%.venv\Scripts\uvicorn.exe" src.api.main:app --host 127.0.0.1 --port 8000 --reload"
start "Aozora Next.js Frontend" cmd /k "cd /d "%ROOT_DIR%src\frontend_next" && npm run dev"

echo.
echo 両サーバーを別ウィンドウで起動しました。
echo ブラウザで http://localhost:3000 を開いてください。
endlocal
