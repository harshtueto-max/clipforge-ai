@echo off
title ClipForge AI
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ClipForge AI is not set up yet. Running setup first...
  call setup.bat
  if not exist ".venv\Scripts\python.exe" exit /b 1
)
".venv\Scripts\python.exe" scripts\launcher.py start
if errorlevel 1 (
  echo.
  echo ClipForge AI could not start. See TROUBLESHOOTING.md
  pause
  exit /b 1
)
timeout /t 4 >nul
