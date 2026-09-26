# Starts the FastAPI backend and the Next.js frontend in two windows.
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path "$root\backend\.venv")) {
  Write-Host "Creating Python virtual environment..."
  python -m venv "$root\backend\.venv"
  & "$root\backend\.venv\Scripts\pip" install -r "$root\backend\requirements.txt"
}
if (-not (Test-Path "$root\frontend\node_modules")) {
  Write-Host "Installing frontend dependencies..."
  Push-Location "$root\frontend"; npm install; Pop-Location
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev -- --port 3001"
Write-Host "Backend:  http://127.0.0.1:8000/api/health"
Write-Host "Frontend: http://localhost:3001"
