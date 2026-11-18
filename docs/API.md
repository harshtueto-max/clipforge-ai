# ClipForge AI – Backend API

Base URL `http://127.0.0.1:8765`. Interactive OpenAPI documentation with request/response schemas: **`/docs`** (Swagger UI)
and `/openapi.json`. All request bodies are validated with Pydantic models (`backend/app/schemas.py`).
Errors are returned as `{"detail": "..."}` with an appropriate 4xx/5xx status.

## Real-time events

`GET ws://127.0.0.1:8765/ws` – server pushes JSON messages `{"type": ..., "data": ...}`:

| type | data |
|---|---|
| `job` | full job object (id, kind, status, progress 0-1, stage, message, error, params, result, timestamps) on every change |
| `project` | `{id, status}` when a project changes state |
| `clips` | `{project_id}` when recommendations were (re)generated |
| `export` | `{id, status}` when an export finishes/fails |

Job kinds: `import`, `download` (YouTube), `proxy`, `analysis`, `rediscover`, `render`, `model_download`.
Statuses: `queued → running → completed | failed | cancelled`; jobs running during a shutdown become `interrupted` and can be retried.

## Endpoints

### System & settings
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | liveness |
| GET | `/api/system/status` | live CPU/RAM/GPU/disk, hardware summary, offline mode, active jobs |
| GET | `/api/system/dependencies` | dependency checklist with fix hints |
| GET/PUT | `/api/settings` | read / update persistent settings (`SettingsUpdate`) |
| POST | `/api/system/dialog` | native file/folder picker `{kind: file|folder|audio}` |
| POST | `/api/system/open-folder?which=exports|projects|data|logs` | open in Explorer |
| DELETE | `/api/system/data?confirm=DELETE&include_exports=&include_models=` | delete all local data |

### Projects & media
| Method | Path | Purpose |
|---|---|---|
| GET/POST | `/api/projects` | list / create `{name, options}` |
| GET/PATCH/DELETE | `/api/projects/{id}` | details (media, summary, counts) / rename+options / delete (`?delete_exports=`) |
| GET | `/api/projects/{id}/thumbnail` | JPEG |
| POST | `/api/projects/{id}/upload` | streaming raw-body upload, header `X-Filename`, `?auto_analyze=` → `{job_id}` |
| POST | `/api/projects/{id}/import-path` | `{path, copy_file, auto_analyze}` → `{job_id}` |
| POST | `/api/projects/{id}/import-youtube` | `{url, confirm_rights: true}` → `{job_id}` |
| GET | `/api/projects/{id}/media/stream` | Range-enabled stream of the preview proxy (or `?source=true`) |
| GET | `/api/projects/{id}/waveform?start=&end=&points=` | peak envelope |
| GET | `/api/projects/{id}/transcript?start=&end=` | words (`i,w,s,e,p,spk`) and sentences |
| PUT | `/api/projects/{id}/transcript/words` | corrections `[{i, w}]` (timing preserved) |
| GET | `/api/projects/{id}/analysis` | summary, speakers, turns, scenes, laughter, excitement, pauses, topics, keywords |
| POST | `/api/projects/{id}/analyze` | full analysis (`AnalyzeRequest`: force, whisper_model, language, analysis_quality, duration_targets, duration_tolerance, score_weights, max_clips_per_target, preferences, preset_id, aspect, use_ai_provider) |
| POST | `/api/projects/{id}/rediscover` | discovery + auto-edit only, re-using cached analysis |
| GET | `/api/projects/{id}/clips?status=&category=&min_score=&target=&speaker=&sort=` | recommendations |

### Clips & editor
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/clips?status=&category=&min_score=&q=&sort=` | clip library across projects |
| GET/PATCH/DELETE | `/api/clips/{id}` | details / status, title, category, fits_duration / delete |
| GET | `/api/clips/{id}/thumbnail` | JPEG |
| POST | `/api/clips/batch` | `{ids, action: accept|reject|reset|delete|export, export_settings}` |
| POST | `/api/clips/{id}/regenerate` | alternative boundaries for the same moment (409 if none) |
| POST | `/api/clips/{id}/duplicate` | alternate version with copied timeline/captions |
| GET | `/api/clips/{id}/editor` | clip, timeline, captions, media, words, sentences, scenes, audio assets, caption styles |
| PUT | `/api/clips/{id}/timeline` | `{data, base_version}` → `{version, output_duration}` |
| PUT | `/api/clips/{id}/captions` | `{style, items}` |
| POST | `/api/clips/{id}/captions/rebuild` | `{style_id?, words_per_caption?}` from transcript words |
| POST | `/api/clips/{id}/apply-preset` | `{preset_id, aspect?}` (rebuilds the automatic edit) |
| POST | `/api/clips/{id}/reframe` | `{mode: auto|single|split|center|manual, aspect?, smoothness}` |
| POST | `/api/clips/{id}/rescore` | score the current (edited) range |
| POST | `/api/clips/{id}/export` | `ExportSettings` → `{export_id, job_id}` |
| GET | `/api/clips/{id}/exports` | export history of the clip |

### Exports & jobs
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/exports?project_id=&status=` | export history |
| GET/DELETE | `/api/exports/{id}` | details (incl. FFprobe validation) / delete (`?delete_file=`) |
| POST | `/api/exports/{id}/retry`, `/cancel`, `/reveal` | queue control / show in Explorer |
| GET | `/api/exports/{id}/file?download=` | the MP4 |
| GET | `/api/jobs?active=&project_id=&kind=` | job list |
| GET/DELETE | `/api/jobs/{id}` | job / delete finished job |
| POST | `/api/jobs/{id}/cancel`, `/api/jobs/{id}/retry` | cancel / resume (cached stages are skipped) |

### Library, presets, AI
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/audio?kind=&category=`, `/api/audio/categories` | music & SFX |
| GET | `/api/audio/{id}/file` | audio file |
| POST | `/api/audio/import?kind=&category=&name=&license_note=&confirm_rights=true` | raw-body upload with `X-Filename` |
| DELETE | `/api/audio/{id}` | delete user asset |
| GET/POST | `/api/presets` | list / create custom preset |
| PUT/DELETE | `/api/presets/{id}` | edit / delete custom preset; `POST /api/presets/{id}/duplicate` |
| GET | `/api/caption-styles`, `/api/fonts` | caption style definitions, installed fonts |
| GET | `/api/models` | Whisper/YuNet/Ollama models, hardware, CUDA status, recommendation |
| POST | `/api/models/download` | `{kind: whisper|vision|ollama, name}` → `{job_id}` |
| DELETE | `/api/models/{kind}/{name}` | remove a model |
| GET | `/api/ai/provider-kinds`, `/api/ai/privacy-summary` | provider catalogue, what is / isn't sent |
| GET/POST | `/api/ai/providers` | list / add (`api_key` is write-only) |
| PUT/DELETE | `/api/ai/providers/{id}` | update (enable requires acknowledgement; blocked in offline mode) / delete |
| POST | `/api/ai/providers/{id}/acknowledge`, `/test` | privacy acknowledgement / connection test (latency, models, usage) |
| GET | `/api/ai/providers/{id}/models` | model list from provider |

## Timeline document (`timeline.data`)

```jsonc
{
  "start": 1237.21, "end": 1297.97,            // source-time clip bounds
  "cuts": [{"s": 1250.1, "e": 1250.9, "auto": true}],   // removed ranges (source time)
  "aspect": "9:16",
  "reframe": {"mode": "auto", "keyframes": [{"t": 1237.5, "x": 0.41, "y": 0.45, "cut": true}],
              "layouts": [{"s": 0, "e": 0, "layout": "split", "top": {"x":0.3,"y":0.4}, "bottom": {"x":0.7,"y":0.4}}],
              "offset": {"x": 0, "y": 0}, "smoothness": 0.75},
  "zooms": [{"s": 1260.2, "e": 1268.0, "scale": 1.1}],
  "music": {"asset_id": "…", "recommended_id": "…", "volume": 0.1, "fade_in": 1, "fade_out": 1.5, "ducking": true, "offset": 0},
  "sfx": [{"id": "…", "asset_id": "…", "t": 1260.05, "volume": 0.35}],
  "audio": {"enhance_voice": true, "denoise": false, "loudness": -14, "voice_gain_db": 0},
  "export": {"resolution": "1080p", "fps": 30, "codec": "h264", "quality": "high"},
  "preset_id": "podcast_pro", "keywords": ["…"]
}
```
Caption items: `{id, start, end, text ("\n" = manual line break), words: [{w, s, e}], style: {per-item overrides}}`.
