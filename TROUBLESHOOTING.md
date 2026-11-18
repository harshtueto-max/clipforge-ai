# Troubleshooting ClipForge AI

Logs live in `%LOCALAPPDATA%\ClipForgeAI\logs\` (`clipforge.log` = application, `server-console.log` = server output).
Settings → *Danger zone* has buttons to open the data and log folders.

## Startup

| Symptom | Fix |
|---|---|
| `start.bat` says *dependencies are missing* | Run `setup.bat` again. It installs/repairs Python packages, FFmpeg and the UI build. |
| Browser shows *Frontend not built* | Run `setup.bat` (needs Node.js once) or `cd frontend && npm.cmd ci && npm.cmd run build`. |
| Port 8765 already in use | Run `stop.bat`. To use another port: `set CLIPFORGE_PORT=8800` before `start.bat`. |
| `npm.ps1 cannot be loaded because running scripts is disabled` | Use `npm.cmd` instead of `npm` (the scripts already do). |
| Page loads but every request fails | Make sure you open `http://127.0.0.1:8765` (requests with a non-local Host header are rejected by design). |

## FFmpeg

* `FFmpeg/FFprobe not found on PATH` → install with `winget install Gyan.FFmpeg` (setup.bat offers this) and **open a new terminal / re-run start.bat** so PATH refreshes.
* Exports fail with *Subtitle* / *libass* errors → your FFmpeg build lacks libass. Use the gyan.dev *full* build.

## Speech recognition (Faster-Whisper)

* **`DLL load failed ... An Application Control policy has blocked this file`** – Windows *Smart App Control* blocks
  unsigned / low-reputation native libraries. ClipForge pins `ctranslate2==4.6.0` and `SQLAlchemy 2.0.x` (pure-Python fallback)
  because newer builds were blocked in testing. If another file is blocked, check *Windows Security → App & browser control → Smart App Control*.
  ClipForge never tries to bypass this policy.
* *Whisper model 'X' is not installed* → Settings → AI Models → Download (sizes and RAM needs are listed), or `scripts\download_model.py base`.
* Transcription is slow → use a smaller model (base/small), install the optional GPU runtime (setup.bat asks when an NVIDIA GPU is detected),
  or set Settings → Transcription → Device = Auto/CUDA.
* `CUDA ... cuBLAS 12 runtime is missing` → re-run setup.bat and accept *GPU runtime*, or `pip install -r backend\requirements-gpu.txt`.
  ClipForge automatically falls back to CPU if CUDA fails.
* AMD / Intel GPUs: transcription runs on CPU (CTranslate2 only supports CUDA). Rendering can still use the GPU encoders if FFmpeg supports them.
* Out-of-memory with medium/large models → pick a model whose RAM/VRAM requirement (shown in Settings → AI Models) fits your machine.

## Analysis

* *No speech was detected* → the video has no (or very quiet) dialogue. ClipForge's discovery is transcript-driven.
* Speakers look wrong → diarization is an approximate, local MFCC clustering method. Disable it (Settings → Transcription) or set *max speakers*.
* Face tracking misses faces → install the YuNet detector (Settings → AI Models). Without it OpenCV Haar cascades are used.
* An analysis was interrupted (app closed / crash) → it shows as *interrupted* in the processing queue; press **Retry**.
  Completed stages (audio, transcript, audio analysis, vision) are cached and not repeated.

## Export / render

* Export failed → open the job in the queue to see the FFmpeg error. Common causes: source file moved (re-import), disk full, invalid output folder.
* Hardware encoding (NVENC) problems → Settings → General → Hardware encoding = Off. Failed hardware encodes automatically retry with x264/x265.
* Every export is validated with FFprobe (streams, resolution, duration). An export is only marked *completed* after validation passes.

## YouTube import

* Only for content you own or are authorized to download. ClipForge does not bypass sign-in, age gates, DRM or other access controls.
  If a URL fails, download the video through an authorized route and import the local file.
* YouTube changes frequently; update the downloader with `.venv\Scripts\python.exe -m pip install -U yt-dlp`.

## AI providers

* Cloud providers are off by default, require a privacy acknowledgement and are blocked entirely in Offline mode.
* *connection failed* → check the base URL / API key / internet; analysis automatically falls back to local scoring.
* Ollama not reachable → install from https://ollama.com and run it; then pull a model from Settings → AI Models.

## Reset

* Settings → Danger zone → *Delete all local data* removes projects, analysis, database records and stored API keys
  (optionally exports and models). You can also delete `%LOCALAPPDATA%\ClipForgeAI` manually while the app is stopped.
