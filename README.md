# ClipForge AI

**From Long Videos to High-Retention Shorts.**

ClipForge AI is a locally running, Windows-first AI video clipping and editing studio. Give it a long video (podcast,
interview, talk, webinar, commentary, gaming, documentary…) and it transcribes, listens to and watches the **whole** video,
finds the strongest self-contained moments, ranks them with an explainable editorial score, builds a first edit
(trim, dead-air removal, smart vertical reframing, word-timed captions, music bed, sparing SFX, voice processing) and lets you
refine everything in a timeline editor before rendering validated MP4s with FFmpeg.

All media processing runs on your computer. No cloud account, no paid API, no uploads. Optional AI providers
(local Ollama or cloud LLMs) can be enabled for deeper semantic review; they only ever receive transcript text and timestamps
(and still frames only if you explicitly allow it).

---

## Quick start (Windows 10 / 11, 64-bit)

1. Double-click **`setup.bat`** (first run only). It:
   * finds Python 3.10–3.12 (offers to install 3.12 with winget),
   * checks FFmpeg (offers `winget install Gyan.FFmpeg`),
   * creates `.venv` and installs pinned Python packages (`backend/requirements.txt` + `requirements.lock`),
   * detects an NVIDIA GPU and offers the optional CUDA runtime (~1 GB) for fast transcription,
   * builds the UI once (needs Node.js; offers to install Node LTS),
   * generates the built-in royalty-free audio library,
   * offers to download the starter Whisper model **base (145 MB)** and the YuNet face detector (0.2 MB).
2. Double-click **`start.bat`**. It checks dependencies, starts the backend on `http://127.0.0.1:8765`
   (localhost only) and opens your browser.
3. Click **New Project**, drop in a video (or pick a local file / paste a YouTube URL you are authorized to download),
   choose durations and a preset, and press **Analyze**.
4. Review the ranked clips → **Edit** → **Export**. Exports go to `%USERPROFILE%\Videos\ClipForge Exports` (configurable).
5. **`stop.bat`** shuts the server down.

Updating: replace the source folder (keep `.venv` if you like), run `setup.bat` again (it re-installs pinned packages and
rebuilds the UI if `frontend/dist` is missing — delete `frontend/dist` to force a rebuild). Your projects, settings and models live in
`%LOCALAPPDATA%\ClipForgeAI` and are preserved.

## Models and downloads

Nothing large is downloaded without asking. Sizes and RAM/VRAM requirements are shown in **Settings → AI Models** before download.

| Model | Download | RAM (CPU) | VRAM (GPU) | Notes |
|---|---|---|---|---|
| Whisper tiny | 75 MB | ~1 GB | ~1 GB | fastest, lowest accuracy |
| Whisper base | 145 MB | ~1.5 GB | ~1 GB | **default starter** |
| Whisper small | 484 MB | ~2.5 GB | ~2 GB | recommended with a 4 GB+ NVIDIA GPU |
| Whisper medium | 1.5 GB | ~5 GB | ~3.5 GB | |
| Whisper large-v3 | 3.1 GB | ~8 GB | ~5 GB | best accuracy, GPU recommended |
| Whisper large-v3-turbo | 1.6 GB | ~6 GB | ~3.5 GB | near-best, faster |
| YuNet face detector | 0.2 MB | – | – | optional; Haar cascades are the bundled fallback |
| Ollama LLMs (optional) | 2–5 GB | 4–8 GB | – | requires https://ollama.com; pulled from Settings |

Silero VAD ships inside faster-whisper; scene detection (PySceneDetect), audio analysis (librosa), sentiment (VADER),
diarization (MFCC clustering) and topic segmentation (TF-IDF TextTiling) need no downloads.

## Recommended hardware

* **Minimum:** 4-core CPU, 8 GB RAM, 10 GB free disk, any GPU. CPU transcription with `base` runs roughly 5–10× real time.
* **Recommended:** 6–8 core CPU, 16 GB RAM, NVIDIA GPU with 4 GB+ VRAM (CUDA) → `small`/`medium` on GPU, NVENC rendering.
* Measured on the development machine (Ryzen 5 7535HS, 16 GB, RTX 2050 4 GB): a 22-minute 1080p podcast was transcribed
  with Whisper *small* on CUDA in **118 s**; the complete analysis (transcription, VAD, audio, diarization, scenes, face tracking,
  discovery, auto-edit) finished in ~5 min; a 56 s 1080×1920 export with captions, music and ducking rendered in **14 s** (NVENC).
* AMD/Intel GPUs: transcription uses the CPU (CTranslate2 supports only CUDA); FFmpeg hardware encoders are used only if they pass
  a real test encode — otherwise x264/x265 are used.

## How clip discovery works

1. **Audio extraction** (FFmpeg → 16 kHz mono analysis copy; the original is never modified).
2. **Transcription** with Faster-Whisper: word timestamps, language ID, VAD filtering, sentence segmentation, pauses.
3. **Voice analysis**: Silero VAD speech activity, loudness/pitch features, excitement peaks, possible laughter,
   long pauses, approximate speaker diarization (anonymous "Speaker 1/2…", never identities).
4. **Visual analysis** on a low-res analysis proxy: PySceneDetect scene cuts, YuNet/Haar face detection at a controlled
   sample rate (1–4 fps by quality setting), face tracking, motion/subject position, speaker-to-screen-position estimation.
5. **Semantic analysis**: TextTiling topic segmentation, keywords, hook/story/advice/education/opinion/humor/emotion
   linguistic patterns, VADER sentiment, dangling-reference detection (clips must stand alone).
6. **Candidate generation** for every duration target: windows that start at good sentence boundaries (topic changes, pauses,
   speaker turns, no "and/so/he…" openings) and end on complete thoughts.
7. **Scoring (0–100)** in seven dimensions with configurable weights — Hook 20, Story completeness 20, Engagement 15,
   Emotion 15, Information 10, Standalone context 10, A/V quality 10 — each with a written explanation.
   *This is an estimated editorial quality score, not a virality guarantee.*
8. **Duplicate suppression** (temporal overlap + transcript similarity, within and across durations) and **ranking**
   (Best overall, Highest hook, Best story, Most informative, Funniest, Most emotional, Best standalone).
9. **Optional AI review**: an enabled provider re-rates the top candidates, writes titles/hooks and may move boundaries to
   neighbouring sentences (validated against the duration limits). Failures fall back to local results.
10. **Auto-edit**: padded boundaries, dead-air removal, smooth face-tracked reframing (dead-zone + velocity limit + scene-aware),
    optional split-screen for two-person wide shots, punch-in zooms at cut points, captions, preset music with ducking, and at most a
    few SFX — all stored as an editable, non-destructive timeline.

## Editor

Left: clips of the project · Center: preview with live crop/caption overlay and safe areas · Bottom: timeline (video segments, cut
regions, scene marks, waveform, captions, music, SFX, playhead, zoom) · Right: Clip / Format & Reframe / Captions / Audio / Preset /
Export panels. Trim, split, delete/restore segments, move edit points, frame stepping, undo/redo, caption text/timing/style edits,
manual reframing, music/SFX placement, voice enhance / noise reduction / loudness — all persisted automatically.

## Export

FFmpeg renders MP4 (H.264 or H.265; NVENC when it works, x264/x265 otherwise) at 720p/1080p/4K, 24/25/30/50/60 fps, CRF-style
quality or a fixed bitrate, AAC audio, EBU R128 loudness normalisation. Single or batch exports go through a render queue
with live progress, cancellation and retry. **An export is only marked completed after FFprobe confirms the streams,
resolution and duration.**

## Privacy & security

* Backend binds to `127.0.0.1`; requests with non-local Host headers are rejected (DNS-rebinding protection).
* File operations are restricted to the app data, projects and export folders; filenames are sanitized; uploads are
  streamed to disk; local-path imports are read-only references or copies.
* Cloud AI is **off by default**, requires an explicit privacy acknowledgement per provider and is blocked entirely in
  **Offline mode**. API keys are encrypted with Windows DPAPI and never returned to the browser.
* No telemetry. Settings → Danger zone deletes all local data.

## Development

```
.venv\Scripts\python.exe -m pytest backend\tests -q          # unit + integration tests
.venv\Scripts\python.exe scripts\e2e_smoke.py <video> --targets 30,60   # full pipeline against a running server
cd backend && ..\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8765 --reload
cd frontend && npm.cmd run dev                                # UI dev server on :5173 (proxies /api, /ws)
```

API documentation: `http://127.0.0.1:8765/docs` (OpenAPI) and [docs/API.md](docs/API.md).
Architecture notes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Problems: [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Known limitations

* Speaker diarization is an approximate MFCC-clustering method (no neural speaker embeddings); it can merge similar voices.
* Active-speaker detection is heuristic (speaker ↔ screen position learned from single-face shots); there is no lip-sync model.
* Local semantic understanding is feature/pattern based; deeper understanding of meaning, irony or context needs the optional
  LLM review (Ollama locally, or a cloud provider you enable).
* Laughter detection is heuristic and labelled "possible laughter".
* Transcription GPU acceleration requires NVIDIA CUDA; other GPUs use the CPU.
* The built-in music/SFX library is procedurally synthesized (CC0) — functional but simple; import your own licensed audio for
  production music.
* YouTube import depends on yt-dlp and YouTube's current behaviour; protected/sign-in/DRM videos are intentionally not supported.
