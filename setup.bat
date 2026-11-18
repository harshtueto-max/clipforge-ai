@echo off
setlocal EnableExtensions EnableDelayedExpansion
title ClipForge AI - Setup
cd /d "%~dp0"
echo ============================================================
echo   ClipForge AI - Windows setup
echo   From Long Videos to High-Retention Shorts
echo ============================================================
echo.

rem ---------------------------------------------------------------- Python
set "PYEXE="
for %%V in (3.12 3.11 3.10) do (
  if not defined PYEXE (
    py -%%V -c "import sys" >nul 2>&1 && set "PYEXE=py -%%V"
  )
)
if not defined PYEXE (
  python -c "import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,12) else 1)" >nul 2>&1 && set "PYEXE=python"
)
if not defined PYEXE (
  echo [!] Python 3.10 - 3.12 was not found.
  where winget >nul 2>&1 || (echo     Install Python 3.12 from https://www.python.org/downloads/ and re-run setup.bat & pause & exit /b 1)
  choice /M "    Install Python 3.12 now with winget"
  if errorlevel 2 (echo Setup cancelled. & pause & exit /b 1)
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
  set "PYEXE=py -3.12"
)
echo [OK] Python: %PYEXE%

rem ---------------------------------------------------------------- FFmpeg
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo [!] FFmpeg was not found on PATH. ClipForge needs FFmpeg for all media processing.
  where winget >nul 2>&1 || (echo     Install FFmpeg from https://www.gyan.dev/ffmpeg/builds/ and add its bin folder to PATH. & pause & exit /b 1)
  choice /M "    Install FFmpeg (Gyan.FFmpeg, ~100 MB) with winget"
  if errorlevel 2 (echo Setup cancelled. & pause & exit /b 1)
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
  echo     FFmpeg installed. If the next step cannot find it, close this window and run setup.bat again ^(PATH refresh^).
) else (
  echo [OK] FFmpeg found
)

rem ---------------------------------------------------------------- Python environment
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo Creating Python virtual environment in .venv ...
  %PYEXE% -m venv .venv || (echo [X] Could not create virtual environment & pause & exit /b 1)
)
echo.
echo Installing Python packages (first run downloads ~600 MB) ...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt -c backend\requirements.lock
if errorlevel 1 (echo [X] Package installation failed - see messages above. & pause & exit /b 1)
echo [OK] Python packages installed

rem ---------------------------------------------------------------- Optional NVIDIA GPU runtime
where nvidia-smi >nul 2>&1
if not errorlevel 1 (
  echo.
  for /f "tokens=*" %%G in ('nvidia-smi --query-gpu^=name^,memory.total --format^=csv^,noheader 2^>nul') do echo [i] NVIDIA GPU detected: %%G
  choice /M "    Install CUDA runtime libraries for GPU transcription (~1 GB download, recommended)"
  if not errorlevel 2 (
    ".venv\Scripts\python.exe" -m pip install -r backend\requirements-gpu.txt
  )
) else (
  echo [i] No NVIDIA GPU detected - transcription will run on the CPU ^(supported, just slower^).
)

rem ---------------------------------------------------------------- Frontend
if exist "frontend\dist\index.html" (
  echo [OK] Frontend build present
) else (
  where node >nul 2>&1
  if errorlevel 1 (
    echo [!] Node.js is needed once to build the user interface.
    where winget >nul 2>&1 || (echo     Install Node.js LTS from https://nodejs.org and re-run setup.bat & pause & exit /b 1)
    choice /M "    Install Node.js LTS with winget"
    if errorlevel 2 (echo Setup cancelled. & pause & exit /b 1)
    winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
    echo     Node.js installed. Close this window and run setup.bat again so PATH is refreshed.
    pause & exit /b 0
  )
  echo Building the user interface ...
  pushd frontend
  call npm.cmd ci || call npm.cmd install
  call npm.cmd run build
  popd
  if not exist "frontend\dist\index.html" (echo [X] Frontend build failed & pause & exit /b 1)
  echo [OK] Frontend built
)

rem ---------------------------------------------------------------- Audio library + models
echo.
echo Preparing the built-in royalty-free audio library ...
pushd backend
"..\.venv\Scripts\python.exe" -m app.services.audio_synth
popd

echo.
echo Speech recognition needs a Whisper model. Recommended starter: "base" (145 MB download, ~1.5 GB RAM).
echo Larger models (small 484 MB, medium 1.5 GB, large-v3 3.1 GB) can be installed later in Settings ^> AI Models.
choice /M "    Download the 'base' model now"
if not errorlevel 2 ".venv\Scripts\python.exe" scripts\download_model.py base
".venv\Scripts\python.exe" scripts\download_model.py yunet

echo.
".venv\Scripts\python.exe" scripts\launcher.py check
echo.
echo ============================================================
echo   Setup complete. Double-click start.bat to launch ClipForge AI.
echo ============================================================
pause
endlocal
