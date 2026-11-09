@echo off
REM Starts backend (port 8000) and frontend (port 5173) in two new windows.
pushd "%~dp0"
if not exist backend\.venv\Scripts\python.exe (
  echo [ERROR] backend\.venv not found. See README.md
  pause
  exit /b 1
)
if not exist frontend\node_modules (
  echo [ERROR] frontend\node_modules not found. Run: cd frontend ^&^& npm install
  pause
  exit /b 1
)
start "backend" cmd /k "cd /d backend && .venv\Scripts\python.exe -m uvicorn main:app --port 8000"
start "frontend" cmd /k "cd /d frontend && npm run dev"
echo.
echo Backend  : http://localhost:8000/docs
echo Frontend : http://localhost:5173
echo Wait about 15 seconds for the backend to finish warming up, then open the Frontend address.
echo Keep the two new windows open. Close them to stop the servers.
popd
pause
