@echo off
setlocal EnableExtensions

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "HOST=127.0.0.1"
set "PORT=8765"
set "URL=http://%HOST%:%PORT%/"
set "API=%URL%api/snapshot"

cd /d "%ROOT%" || (
  echo Could not open CryptCore folder: %ROOT%
  pause
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on PATH.
  echo Install Python or launch Crypt from a terminal where python is available.
  pause
  exit /b 1
)

echo Checking Crypt WebUI at %URL%
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing '%API%' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; exit 1"

if errorlevel 1 (
  echo Starting Crypt WebUI backend...
  start "Crypt WebUI Backend" /D "%ROOT%" cmd /k python main.py --cwd "%ROOT%" webui --host %HOST% --port %PORT%

  echo Waiting for backend to become ready...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$url = '%API%'; $deadline = (Get-Date).AddSeconds(30); do { try { $r = Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 700 } while ((Get-Date) -lt $deadline); exit 1"
  if errorlevel 1 (
    echo Crypt WebUI did not become ready on %URL%
    echo Leave the backend window open if it contains an error, then fix that message.
    pause
    exit /b 1
  )
) else (
  echo Crypt WebUI backend is already running.
)

echo Opening %URL%
start "" "%URL%"
exit /b 0
