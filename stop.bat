@echo off
title ClipForge AI - Stop
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Nothing to stop - ClipForge AI is not installed.
  exit /b 0
)
".venv\Scripts\python.exe" scripts\launcher.py stop
timeout /t 2 >nul
