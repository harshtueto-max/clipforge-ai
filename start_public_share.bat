@echo off
setlocal
title ClipForge AI - Public Cloud Share Tunnel
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo ClipForge AI is not set up yet. Running setup first...
  call setup.bat
  if not exist ".venv\Scripts\python.exe" exit /b 1
)

echo ======================================================================
echo   ClipForge AI - Public Share Mode (Sandboxed + HTTPS Tunnel)
echo ======================================================================
echo Restarting backend with CLIPFORGE_PUBLIC_CLOUD=1 safety guards...
".venv\Scripts\python.exe" scripts\launcher.py stop >nul 2>&1
set CLIPFORGE_PUBLIC_CLOUD=1
".venv\Scripts\python.exe" scripts\launcher.py start
if errorlevel 1 (
  echo.
  echo ClipForge AI could not start. See TROUBLESHOOTING.md
  pause
  exit /b 1
)

set "CF_EXE="
where cloudflared >nul 2>&1
if not errorlevel 1 (
  set "CF_EXE=cloudflared"
) else (
  set "CF_DIR=%LOCALAPPDATA%\ClipForgeAI\bin"
  if not exist "%LOCALAPPDATA%\ClipForgeAI\bin" mkdir "%LOCALAPPDATA%\ClipForgeAI\bin"
  set "CF_EXE=%LOCALAPPDATA%\ClipForgeAI\bin\cloudflared.exe"
  if not exist "%LOCALAPPDATA%\ClipForgeAI\bin\cloudflared.exe" (
    echo.
    echo Downloading Cloudflare Quick Tunnel client ^(one-time, ~35 MB^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile '%LOCALAPPDATA%\ClipForgeAI\bin\cloudflared.exe'"
    if not exist "%LOCALAPPDATA%\ClipForgeAI\bin\cloudflared.exe" (
      echo Failed to download cloudflared.exe. Check your internet connection.
      pause
      exit /b 1
    )
  )
)

echo.
echo ======================================================================
echo   Starting public HTTPS tunnel to http://127.0.0.1:8765 ...
echo   Copy the https://....trycloudflare.com URL printed below!
echo   Anyone can:
echo     1. Open that https://....trycloudflare.com URL directly, OR
echo     2. Open https://clipforge-ai-one-alpha.vercel.app and paste it
echo        into the "Engine URL" button in the top bar.
echo   Press Ctrl+C to close the public tunnel when finished.
echo ======================================================================
echo.
"%CF_EXE%" tunnel --url http://127.0.0.1:8765 --no-autoupdate
