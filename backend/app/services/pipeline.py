"""Job handlers: media import, YouTube download, full analysis pipeline, clip discovery, auto-edit, render, model downloads."""
from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Any

import numpy as np

from .. import config
from ..db import session_scope
from ..events import hub
from ..jobs import JobContext, manager
from ..models import (AIProvider, AudioAsset, CandidateClip, CaptionTrack, ExportJob, Job, Preset, Project, Scene, SourceMedia,
                      Speaker, Timeline, Transcript, utcnow)
from ..security import sanitize_filename
from . import (audio_analysis, audio_library, autoedit, diarization, discovery, llm, media, renderer, semantic, storage,
               transcription, vision)
from .presets import BUILTIN_PRESETS

log = logging.getLogger("clipforge.pipeline")


def _set_project(project_id: str, **fields) -> None:
    with session_scope() as s:
        p = s.get(Project, project_id)
        if p:
            for k, v in fields.items():
                setattr(p, k, v)
            hub.publish("project", {"id": p.id, "status": p.status})


def _media_for(project_id: str) -> tuple[Project, SourceMedia]:
    with session_scope() as s:
        p = s.get(Project, project_id)
        if p is None:
            raise RuntimeError("Project not found")
        m = s.query(SourceMedia).filter(SourceMedia.project_id == project_id).order_by(SourceMedia.created_at.desc()).first()
        if m is None:
            raise RuntimeError("Project has no source media - import a video first")
        s.expunge(p)
        s.expunge(m)
        return p, m


# ------------------------------------------------------------------ import
def handle_import(ctx: JobContext) -> dict[str, Any]:
    pid = ctx.project_id
    prm = ctx.params
    folder = storage.project_folder(pid)
    storage.ensure_layout(folder)
    art = storage.Artifacts(folder)
    src = Path(prm["path"])
    mode = prm.get("mode", "copy")  # copy | reference | uploaded
    _set_project(pid, status="importing")
    ctx.progress(0.02, "probe", "Reading media metadata")
    info = media.probe(src)
    if not info["has_video"] and not info["has_audio"]:
        raise media.MediaError("File contains no audio or video streams")
    if info["duration"] <= 0:
        raise media.MediaError("Could not determine media duration")
    free = shutil.disk_usage(folder).free
    if mode == "copy":
        need = src.stat().st_size * 1.05 + 200e6
        if free < need:
            raise OSError(f"Insufficient disk space: need {need / 1e9:.1f} GB, have {free / 1e9:.1f} GB")
        dst = folder / "media" / sanitize_filename(src.name, default="source.mp4")
        ctx.progress(0.05, "copy", "Copying source into project")
        _copy_with_progress(src, dst, ctx, 0.05, 0.4)
        path = dst
    else:
        path = src
    ctx.progress(0.42, "thumbnail", "Generating thumbnail")
    thumb = None
    if info["has_video"]:
        thumb = media.thumbnail(path, folder / "thumbs" / "project.jpg", at=min(info["duration"] * 0.1, 30.0))
    if info["has_audio"]:
        ctx.progress(0.45, "audio", "Extracting analysis audio (16 kHz mono)")
        media.extract_audio(path, art.wav, ctx=ctx, duration=info["duration"],
                            progress=lambda p: ctx.progress(0.45 + 0.45 * p, "audio", "Extracting audio"))
        ctx.progress(0.92, "waveform", "Computing waveform")
        media.waveform_peaks(art.wav, art.waveform)
    with session_scope() as s:
        m = SourceMedia(project_id=pid, original_name=prm.get("original_name") or src.name, path=str(path), is_reference=(mode == "reference"),
                        source_url=prm.get("source_url"), size_bytes=path.stat().st_size, duration=info["duration"], width=info["width"],
                        height=info["height"], fps=info["fps"], video_codec=info["video_codec"], audio_codec=info["audio_codec"],
                        has_audio=info["has_audio"], has_video=info["has_video"], probe=info, thumbnail=str(thumb) if thumb else None,
                        waveform=str(art.waveform) if info["has_audio"] else None)
        s.add(m)
        p = s.get(Project, pid)
        p.status = "ready"
        p.thumbnail = str(thumb) if thumb else None
        s.flush()
        mid = m.id
    hub.publish("project", {"id": pid, "status": "ready"})
    s_settings = config.get_settings()
    want_proxy = s_settings.get("proxy_mode", "auto")
    if info["has_video"] and (want_proxy == "always" or (want_proxy == "auto" and media.needs_proxy(path, info))):
        manager.submit("proxy", pid, {"media_id": mid})
    if prm.get("auto_analyze"):
        manager.submit("analysis", pid, prm.get("analysis_params") or {})
    return {"media_id": mid, "duration": info["duration"], "width": info["width"], "height": info["height"]}


def _copy_with_progress(src: Path, dst: Path, ctx: JobContext, p0: float, p1: float) -> None:
    total = src.stat().st_size or 1
    done = 0
    tmp = dst.with_suffix(dst.suffix + ".part")
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        while True:
            buf = fi.read(8 * 1024 * 1024)
            if not buf:
                break
            fo.write(buf)
            done += len(buf)
            ctx.progress(p0 + (p1 - p0) * done / total, "copy", f"Copying {done / 1e6:.0f}/{total / 1e6:.0f} MB")
    tmp.replace(dst)


def import_failed(job_id: str, status: str, info: dict) -> None:
    if status != "completed" and info.get("project_id"):
        with session_scope() as s:
            p = s.get(Project, info["project_id"])
            if p and p.status == "importing":
                has_media = s.query(SourceMedia).filter(SourceMedia.project_id == p.id).count() > 0
                p.status = "ready" if has_media else ("error" if status == "failed" else "new")


def handle_proxy(ctx: JobContext) -> dict[str, Any]:
    _, m = _media_for(ctx.project_id)
    art = storage.Artifacts(storage.project_folder(ctx.project_id))
    art.preview_proxy.parent.mkdir(parents=True, exist_ok=True)
    media.make_proxy(m.path, art.preview_proxy, m.duration, ctx, lambda p: ctx.progress(p, "proxy", "Creating preview proxy"))
    with session_scope() as s:
        mm = s.get(SourceMedia, m.id)
        mm.proxy_path = str(art.preview_proxy)
    hub.publish("project", {"id": ctx.project_id, "status": "proxy_ready"})
    return {"proxy": str(art.preview_proxy)}


# ------------------------------------------------------------------ YouTube
def handle_download(ctx: JobContext) -> dict[str, Any]:
    if config.get_settings().get("offline_mode"):
        raise RuntimeError("Offline mode is enabled - YouTube import is unavailable. Import a local file instead.")
    import yt_dlp

    pid = ctx.project_id
    folder = storage.project_folder(pid)
    storage.ensure_layout(folder)
    url = ctx.params["url"]
    out_tmpl = str(folder / "media" / "%(id)s.%(ext)s")
    state = {"file": None}

    def hook(d):
        if ctx.cancelled:
            raise yt_dlp.utils.DownloadCancelled("cancelled")
        if d.get("status") == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if tot:
                ctx.progress(0.9 * d.get("downloaded_bytes", 0) / tot, "download", f"Downloading {d.get('downloaded_bytes', 0) / 1e6:.0f}/{tot / 1e6:.0f} MB")
        elif d.get("status") == "finished":
            state["file"] = d.get("filename")

    opts = {
        "outtmpl": out_tmpl, "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/bv*+ba/b", "merge_output_format": "mp4",
        "noplaylist": True, "quiet": True, "no_warnings": True, "progress_hooks": [hook], "restrictfilenames": True,
        "ffmpeg_location": str(Path(media.ffmpeg_bin() or "ffmpeg").parent) if media.ffmpeg_bin() else None,
    }
    ctx.progress(0.01, "download", "Contacting YouTube")
    try:
        with yt_dlp.YoutubeDL({k: v for k, v in opts.items() if v is not None}) as ydl:
            info = ydl.extract_info(url, download=True)
            path = Path(ydl.prepare_filename(info)).with_suffix(".mp4")
            if not path.exists():
                cands = sorted((folder / "media").glob(f"{info['id']}.*"), key=lambda p: p.stat().st_size, reverse=True)
                path = cands[0] if cands else None
    except yt_dlp.utils.DownloadCancelled:
        ctx.check_cancel()
        raise
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc)
        if "Sign in" in msg or "login" in msg.lower() or "age" in msg.lower():
            raise RuntimeError("This video requires sign-in or age verification. ClipForge does not bypass access controls - "
                               "download it yourself (if you are authorized) and import the local file.") from exc
        if "DRM" in msg:
            raise RuntimeError("This video is DRM-protected and cannot be downloaded.") from exc
        raise RuntimeError(f"YouTube download failed: {msg[-400:]}. You can import a local file instead.") from exc
    if not path or not path.exists():
        raise RuntimeError("Download finished but the output file was not found")
    title = info.get("title") or path.stem
    with session_scope() as s:
        p = s.get(Project, pid)
        if p and p.name.startswith("YouTube import"):
            p.name = title[:200]
    ctx.params.update({"path": str(path), "mode": "uploaded", "original_name": f"{title}.mp4", "source_url": url})
    sub = handle_import(ctx)
    return {**sub, "title": title}


# ------------------------------------------------------------------ analysis
STAGES = [("audio", 0.04), ("transcribe", 0.45), ("audio_analysis", 0.08), ("diarization", 0.06), ("vision", 0.25),
          ("semantic", 0.03), ("discovery", 0.06), ("autoedit", 0.03)]


class StageProgress:
    def __init__(self, ctx: JobContext):
        self.ctx = ctx
        self.offsets = {}
        acc = 0.0
        for name, w in STAGES:
            self.offsets[name] = (acc, w)
            acc += w

    def __call__(self, stage: str, frac: float, msg: str | None = None):
        a, w = self.offsets[stage]
        self.ctx.progress(a + w * max(0.0, min(1.0, frac)), stage, msg)


def handle_analysis(ctx: JobContext) -> dict[str, Any]:
    pid = ctx.project_id
    prm = ctx.params
    settings = config.get_settings()
    proj, m = _media_for(pid)
    folder = storage.project_folder(pid)
    storage.ensure_layout(folder)
    art = storage.Artifacts(folder)
    sp = StageProgress(ctx)
    force = bool(prm.get("force"))
    popts = proj.options or {}
    model_name = prm.get("whisper_model") or popts.get("whisper_model") or settings["whisper_model"]
    quality = prm.get("analysis_quality") or popts.get("analysis_quality") or settings["analysis_quality"]
    if not prm.get("language") and popts.get("language"):
        prm["language"] = popts["language"]
    _set_project(pid, status="analyzing")
    summary: dict[str, Any] = {"stages": {}}
    t_all = time.time()
    if not m.has_audio:
        raise RuntimeError("This media has no audio track - speech-based clip discovery needs audio")

    # 1. audio
    sp("audio", 0, "Extracting audio")
    if force or not art.wav.exists():
        media.extract_audio(m.path, art.wav, ctx=ctx, duration=m.duration, progress=lambda p: sp("audio", p, "Extracting audio"))
        media.waveform_peaks(art.wav, art.waveform)
    summary["stages"]["audio"] = "ok"

    # 2. transcription
    req_lang = (prm.get("language") or popts.get("language") or settings.get("transcription_language") or "auto").strip()
    tr = storage.read_json(art.transcript)
    if force or not tr or tr.get("model") != model_name or tr.get("language_mode", "auto") != req_lang:
        st = transcription.engine_status()
        if not st["available"]:
            raise RuntimeError(f"Speech recognition engine could not be loaded: {st['error']}")
        if not transcription.is_installed(model_name):
            raise RuntimeError(f"Whisper model '{model_name}' is not installed. Open Settings > AI Models and download it "
                               f"({transcription.WHISPER_MODELS.get(model_name, {}).get('size_mb')} MB).")
        sp("transcribe", 0.0, f"Loading Whisper '{model_name}' ({req_lang})")
        t0 = time.time()
        tr = transcription.transcribe(art.wav, m.duration, model_name, settings.get("whisper_device", "auto"), req_lang,
                                      progress=lambda p, msg: sp("transcribe", p, msg), ctx=ctx)
        tr["elapsed_s"] = round(time.time() - t0, 1)
        transcription.unload_models()  # free GPU VRAM immediately for vision & NVENC export
        storage.write_json(art.transcript, tr)
        # invalidate downstream caches
        for pth in (art.diarization, art.semantic):
            pth.unlink(missing_ok=True)
    if not tr["words"]:
        raise RuntimeError("No speech was detected in this video, so there is nothing to clip from the transcript")
    summary["stages"]["transcribe"] = {"model": tr["model"], "device": tr.get("device"), "language": tr["language"],
                                       "language_mode": tr.get("language_mode", req_lang),
                                       "words": len(tr["words"]), "sentences": len(tr["sentences"]), "elapsed_s": tr.get("elapsed_s")}
    with session_scope() as s:
        s.query(Transcript).filter(Transcript.project_id == pid).delete()
        s.add(Transcript(project_id=pid, language=tr["language"], language_probability=tr["language_probability"], model=tr["model"],
                         device=tr.get("device", "cpu"), word_count=len(tr["words"]), sentence_count=len(tr["sentences"]), path=str(art.transcript)))

    # 3. audio analysis
    sp("audio_analysis", 0.0, "Analyzing voice activity and intensity")
    audio_data, sr = media.load_wav(art.wav)
    au = storage.read_json(art.audio)
    if force or not au or not art.audio_frames.exists():
        au = audio_analysis.analyze(audio_data, sr, tr["words"], progress=lambda p, msg: sp("audio_analysis", p, msg))
        frames = au.pop("_frames")
        np.savez_compressed(art.audio_frames, **frames)
        storage.write_json(art.audio, au)
    frames = dict(np.load(art.audio_frames))
    summary["stages"]["audio_analysis"] = {"speech_ratio": au["speech_ratio"], "laughter_events": len(au["laughter"]),
                                           "excitement_peaks": len(au["excitement"]), "long_pauses": len(au["long_pauses"])}

    # 4. diarization
    dia = storage.read_json(art.diarization)
    if force or not dia:
        if settings.get("enable_diarization", True):
            sp("diarization", 0.1, "Estimating speakers")
            try:
                dia = diarization.diarize(audio_data, sr, au["vad"], tr["words"], tr["sentences"], int(settings.get("max_speakers", 4)))
            except Exception as exc:  # noqa: BLE001
                log.warning("diarization failed: %s", exc)
                dia = diarization._single(tr["words"], tr["sentences"], f"diarization failed: {exc}")
        else:
            dia = diarization._single(tr["words"], tr["sentences"], "disabled in settings")
        storage.write_json(art.diarization, dia)
        storage.write_json(art.transcript, tr)  # now includes speaker labels
    del audio_data
    with session_scope() as s:
        s.query(Speaker).filter(Speaker.project_id == pid).delete()
        for spk in dia["speakers"]:
            s.add(Speaker(project_id=pid, label=spk["label"], speaking_time=spk["speaking_time"], turns=spk["turns"], method=dia["method"]))
    summary["stages"]["diarization"] = {"speakers": dia["num_speakers"], "method": dia["method"], "note": dia.get("note")}

    # 5. vision
    vis = storage.read_json(art.vision)
    scenes = storage.read_json(art.scenes)
    q = vision.QUALITY.get(quality, vision.QUALITY["balanced"])
    if m.has_video and (force or not vis or not scenes or vis.get("quality") != quality):
        sp("vision", 0.0, "Preparing analysis frames")
        if force or not art.vision_proxy.exists():
            vision.make_analysis_proxy(m.path, art.vision_proxy, m.duration, q["width"], ctx, lambda p: sp("vision", 0.35 * p, "Decoding video for analysis"))
        sp("vision", 0.35, "Detecting scenes (PySceneDetect)")
        scenes = vision.detect_scenes(art.vision_proxy, q["scene_threshold"], ctx, lambda p: sp("vision", 0.35 + 0.25 * p, "Detecting scenes"))
        storage.write_json(art.scenes, scenes)
        sp("vision", 0.6, "Detecting and tracking faces")
        vis = vision.sample_frames(art.vision_proxy, q["sample_fps"], ctx, lambda p: sp("vision", 0.6 + 0.4 * p, "Face & subject tracking"))
        vis["quality"] = quality
        vis["speaker_positions"] = {str(k): v for k, v in vision.speaker_positions(vis["samples"], tr["sentences"]).items()}
        vis["scene_stats"] = vision.summarize(vis["samples"], scenes)
        storage.write_json(art.vision, vis)
    elif not m.has_video:
        vis, scenes = {"samples": [], "tracks": [], "speaker_positions": {}, "scene_stats": []}, [{"s": 0.0, "e": m.duration}]
    with session_scope() as s:
        s.query(Scene).filter(Scene.project_id == pid).delete()
        for st_ in vis.get("scene_stats") or [{"index": k, "s": sc["s"], "e": sc["e"], "face_count": 0} for k, sc in enumerate(scenes)]:
            s.add(Scene(project_id=pid, index=st_["index"], start=st_["s"], end=st_["e"], face_count=st_["face_count"]))
    face_frac = float(np.mean([1.0 if x["faces"] else 0.0 for x in vis["samples"]])) if vis.get("samples") else 0.0
    summary["stages"]["vision"] = {"scenes": len(scenes), "samples": len(vis.get("samples", [])), "face_tracks": len(vis.get("tracks", [])),
                                   "face_visible_ratio": round(face_frac, 3), "detector": vis.get("detector")}

    # 6. semantic
    sp("semantic", 0.0, "Understanding topics and structure")
    bundle = build_bundle(tr, au, frames, dia, vis, scenes, m)
    storage.write_json(art.semantic, {"topic_bounds": bundle.topic_bounds, "keywords": bundle.keywords,
                                      "topics": len(bundle.topic_bounds)})
    summary["stages"]["semantic"] = {"topics": len(bundle.topic_bounds), "keywords": bundle.keywords[:15]}

    # 7-8. discovery + auto edit
    res = run_discovery(ctx, pid, bundle, prm, vis, scenes, m, sp)
    summary["stages"]["discovery"] = res
    summary["elapsed_s"] = round(time.time() - t_all, 1)
    _set_project(pid, status="analyzed", analysis_summary=summary)
    return summary


def build_bundle(tr, au, frames, dia, vis, scenes, m) -> discovery.Bundle:
    b = discovery.Bundle(duration=m.duration, words=tr["words"], sentences=tr["sentences"], audio_frames=frames,
                         vad=au.get("vad", []), laughter=au.get("laughter", []), face_samples=vis.get("samples", []), scenes=scenes,
                         num_speakers=int(dia.get("num_speakers", 1)), has_video=bool(m.has_video))
    return discovery.prepare(b)


def load_bundle(project_id: str) -> tuple[discovery.Bundle, dict, list, SourceMedia, dict]:
    _, m = _media_for(project_id)
    art = storage.Artifacts(storage.project_folder(project_id))
    tr = storage.read_json(art.transcript)
    if not tr:
        raise RuntimeError("Project has not been analyzed yet")
    au = storage.read_json(art.audio, {"vad": [], "laughter": []})
    frames = dict(np.load(art.audio_frames)) if art.audio_frames.exists() else None
    dia = storage.read_json(art.diarization, {"num_speakers": 1})
    vis = storage.read_json(art.vision, {"samples": [], "speaker_positions": {}})
    scenes = storage.read_json(art.scenes, [{"s": 0, "e": m.duration}])
    return build_bundle(tr, au, frames, dia, vis, scenes, m), vis, scenes, m, tr


def handle_rediscover(ctx: JobContext) -> dict[str, Any]:
    pid = ctx.project_id
    bundle, vis, scenes, m, _ = load_bundle(pid)
    sp = StageProgress(ctx)
    _set_project(pid, status="analyzing")
    res = run_discovery(ctx, pid, bundle, ctx.params, vis, scenes, m, sp)
    with session_scope() as s:
        p = s.get(Project, pid)
        summ = dict(p.analysis_summary or {})
        summ.setdefault("stages", {})["discovery"] = res
        p.analysis_summary = summ
        p.status = "analyzed"
    hub.publish("project", {"id": pid, "status": "analyzed"})
    return res


def _enabled_provider() -> llm.ProviderConfig | None:
    with session_scope() as s:
        rows = s.query(AIProvider).filter(AIProvider.enabled == True).all()  # noqa: E712
        for r in rows:
            cfgp = llm.ProviderConfig(r.id, r.name, r.kind, r.base_url or "", r.model, r.enabled, r.is_local, r.send_frames, r.privacy_acknowledged)
            try:
                llm.check_allowed(cfgp)
                return cfgp
            except llm.ProviderError as exc:
                log.info("provider %s skipped: %s", r.name, exc)
    return None


def run_discovery(ctx: JobContext, pid: str, bundle: discovery.Bundle, prm: dict, vis: dict, scenes: list, m: SourceMedia, sp) -> dict[str, Any]:
    settings = config.get_settings()
    with session_scope() as s:
        proj = s.get(Project, pid)
        popts = dict(proj.options or {})
    targets = prm.get("duration_targets") or popts.get("duration_targets") or settings["duration_targets"]
    tolerance = float(prm.get("duration_tolerance") or popts.get("duration_tolerance") or settings["duration_tolerance"])
    weights = prm.get("score_weights") or popts.get("score_weights") or settings["score_weights"]
    max_per = int(prm.get("max_clips_per_target") or popts.get("max_clips_per_target") or settings["max_clips_per_target"])
    prefs = prm.get("preferences") or popts.get("preferences") or settings.get("discovery_preferences", {})
    preset_id = prm.get("preset_id") or popts.get("preset_id") or settings.get("default_preset", "podcast_pro")
    aspect = prm.get("aspect") or popts.get("aspect") or settings.get("default_aspect", "9:16")
    sp("discovery", 0.05, "Generating and scoring candidate moments")
    cands = discovery.discover(bundle, [float(t) for t in targets], tolerance, weights, max_per, prefs,
                               progress=lambda p: sp("discovery", 0.05 + 0.5 * p, "Scoring candidates"))
    source = "local"
    llm_note = None
    use_llm = prm.get("use_ai_provider", True)
    provider = _enabled_provider() if use_llm else None
    if provider and cands:
        sp("discovery", 0.6, f"Deep semantic review with {provider.name}")
        try:
            used = refine_with_llm(provider, bundle, cands, tolerance, weights, ctx)
            source = f"local+{provider.kind}"
            llm_note = f"Refined by {provider.name} ({provider.model}); tokens in/out {used['input_tokens']}/{used['output_tokens']}"
        except Exception as exc:  # noqa: BLE001
            llm_note = f"AI provider failed, local analysis used: {exc}"
            log.warning(llm_note)
    sp("discovery", 0.9, "Saving recommendations")
    # replace previous untouched suggestions; keep accepted / edited clips
    with session_scope() as s:
        old = s.query(CandidateClip).filter(CandidateClip.project_id == pid, CandidateClip.status == "suggested").all()
        for c in old:
            tlrow = s.query(Timeline).filter(Timeline.clip_id == c.id).first()
            if tlrow is None or tlrow.version <= 1:
                s.delete(c)
        s.flush()
        kept = [{"start": k.start, "end": k.end} for k in s.query(CandidateClip).filter(CandidateClip.project_id == pid).all()]
        cands = [c for c in cands if not any(discovery.iou(c, k) > 0.8 for k in kept)]
        preset_cfg = _preset_cfg(s, preset_id)
        music_cache: dict[str, Any] = {}
        new_ids = []
        for c in cands:
            row = CandidateClip(project_id=pid, target_duration=c["target_duration"], start=c["start"], end=c["end"], score=c["score"],
                                scores=c["scores"], explanations=c["explanations"], title=c["title"], category=c["category"], hook=c["hook"],
                                description=c["description"], reason=c["reason"], transcript=c["transcript"], speakers=c["speakers"],
                                tags=c.get("tags", []), fits_duration=bool(c.get("fits_duration", True)), analysis_source=c.get("source", source),
                                rank=c.get("rank", 0), status="suggested")
            s.add(row)
            s.flush()
            new_ids.append(row.id)
    sp("autoedit", 0.0, "Creating first-pass edits")
    for k, cid in enumerate(new_ids):
        create_auto_edit(cid, preset_id, aspect, bundle=bundle, vis=vis, scenes=scenes, m=m)
        sp("autoedit", (k + 1) / max(1, len(new_ids)), f"Auto-edited {k + 1}/{len(new_ids)} clips")
    hub.publish("clips", {"project_id": pid})
    return {"candidates": len(cands), "targets": targets, "tolerance": tolerance, "source": source, "llm": llm_note,
            "unfit_targets": [t for t in targets if not any(c["target_duration"] == float(t) and c.get("fits_duration") for c in cands)]}


def refine_with_llm(provider: llm.ProviderConfig, bundle: discovery.Bundle, cands: list[dict], tolerance: float, weights: dict, ctx) -> dict:
    total = {"input_tokens": 0, "output_tokens": 0}
    for k, c in enumerate(cands):
        c["cid"] = f"c{k}"
    kw = ", ".join(bundle.keywords[:20])
    batch = 4
    for off in range(0, len(cands), batch):
        ctx.check_cancel()
        group = cands[off: off + batch]
        user = llm.USER_TEMPLATE.format(keywords=kw, blocks=llm.build_blocks(group, bundle.sentences, tolerance))
        out, usage = llm.chat_json(provider, llm.SYSTEM_PROMPT, user)
        total["input_tokens"] += usage.get("input_tokens", 0)
        total["output_tokens"] += usage.get("output_tokens", 0)
        by_id = {str(x.get("id")): x for x in out.get("clips", []) if isinstance(x, dict)}
        for c in group:
            r = by_id.get(c["cid"])
            if not r:
                continue
            # optional boundary refinement, validated against duration limits
            try:
                si, ei = int(r.get("start_index", c["i"])), int(r.get("end_index", c["j"]))
                if (si, ei) != (c["i"], c["j"]) and 0 <= si <= ei < len(bundle.sentences):
                    d = bundle.sentences[ei]["e"] - bundle.sentences[si]["s"]
                    T = c["target_duration"]
                    if T * (1 - tolerance) <= d <= T * (1 + tolerance):
                        local = discovery.score_window(bundle, si, ei, weights)
                        c.update({k2: local[k2] for k2 in ("start", "end", "duration", "i", "j", "scores", "explanations")})
                        c["transcript"] = discovery.clip_text(bundle, si, ei)
            except (TypeError, ValueError):
                pass
            for dim in ("hook", "story", "engagement", "emotion", "information", "standalone"):
                v = r.get(dim)
                if isinstance(v, (int, float)):
                    c["scores"][dim] = round(0.4 * c["scores"][dim] + 0.6 * discovery.clamp(float(v)), 1)
            c["score"] = round(discovery.weighted_total(c["scores"], weights), 1)
            if isinstance(r.get("title"), str) and r["title"].strip():
                c["title"] = r["title"].strip()[:90]
            if isinstance(r.get("hook_line"), str) and r["hook_line"].strip():
                c["hook"] = r["hook_line"].strip()[:200]
            if isinstance(r.get("description"), str) and r["description"].strip():
                c["description"] = r["description"].strip()[:400]
            if r.get("category") in discovery.CATEGORIES:
                c["category"] = r["category"]
            if isinstance(r.get("reason"), str) and r["reason"].strip():
                c["reason"] = f"AI review: {r['reason'].strip()[:300]} | Local: {c['reason']}"
            c["source"] = f"local+{provider.kind}"
    discovery.assign_tags(cands)
    with session_scope() as s:
        row = s.get(AIProvider, provider.id)
        if row:
            u = dict(row.usage or {})
            u["input_tokens"] = u.get("input_tokens", 0) + total["input_tokens"]
            u["output_tokens"] = u.get("output_tokens", 0) + total["output_tokens"]
            u["requests"] = u.get("requests", 0) + (len(cands) + batch - 1) // batch
            row.usage = u
    return total


def _preset_cfg(s, preset_id: str) -> dict:
    row = s.get(Preset, preset_id)
    if row:
        return dict(row.config or {})
    return dict(BUILTIN_PRESETS.get(preset_id, BUILTIN_PRESETS["podcast_pro"])["config"])


def create_auto_edit(clip_id: str, preset_id: str, aspect: str, bundle=None, vis=None, scenes=None, m=None, reset: bool = True) -> None:
    with session_scope() as s:
        c = s.get(CandidateClip, clip_id)
        if c is None:
            return
        pid = c.project_id
        clip = {"start": c.start, "end": c.end, "category": c.category}
    if bundle is None:
        bundle, vis, scenes, m, _ = load_bundle(pid)
    spk_pos = {int(k): v for k, v in (vis.get("speaker_positions") or {}).items()}
    with session_scope() as s:
        pcfg = _preset_cfg(s, preset_id)
        music = audio_library.recommend_music(s, clip["category"], pcfg.get("music", {}).get("moods", []))
        sfx = audio_library.recommend_sfx(s, clip["category"])
        music_id, sfx_id = (music.id if music else None), (sfx.id if sfx else None)
    tl, cap_style, items = autoedit.build_timeline(
        clip, bundle.words, bundle.sentences, vis, scenes, spk_pos, m.width, m.height,
        preset_id, pcfg, music_id, sfx_id, aspect, m.fps or 30,
        vad=bundle.vad, laughter=bundle.laughter, duration=m.duration,
    )
    tl["keywords"] = bundle.keywords[:30]
    folder = storage.project_folder(pid)
    thumb = None
    if m.has_video:
        try:
            hook_t = clip["start"] + min(2.0, (clip["end"] - clip["start"]) / 3)
            thumb = str(media.thumbnail(m.path, folder / "thumbs" / f"clip_{clip_id}.jpg", at=hook_t, width=360))
        except Exception as exc:  # noqa: BLE001
            log.warning("clip thumbnail failed: %s", exc)
    with session_scope() as s:
        row = s.query(Timeline).filter(Timeline.clip_id == clip_id).first()
        if row is None:
            s.add(Timeline(clip_id=clip_id, data=tl, version=1))
        elif reset:
            row.data = tl
            row.version = row.version + 1
        cap = s.query(CaptionTrack).filter(CaptionTrack.clip_id == clip_id).first()
        if cap is None:
            s.add(CaptionTrack(clip_id=clip_id, style=cap_style, items=items))
        elif reset:
            cap.style, cap.items = cap_style, items
        c = s.get(CandidateClip, clip_id)
        if thumb:
            c.thumbnail = thumb


# ------------------------------------------------------------------ render
def handle_render(ctx: JobContext) -> dict[str, Any]:
    export_id = ctx.params["export_id"]
    with session_scope() as s:
        ex = s.get(ExportJob, export_id)
        if ex is None:
            raise RuntimeError("Export record missing")
        ex.status = "running"
        ex.error = None
        clip = s.get(CandidateClip, ex.clip_id)
        if clip is None:
            raise RuntimeError("Clip no longer exists")
        tlrow = s.query(Timeline).filter(Timeline.clip_id == clip.id).first()
        cap = s.query(CaptionTrack).filter(CaptionTrack.clip_id == clip.id).first()
        m = s.query(SourceMedia).filter(SourceMedia.project_id == clip.project_id).order_by(SourceMedia.created_at.desc()).first()
        if tlrow is None or m is None:
            raise RuntimeError("Clip has no timeline or source media")
        tl = dict(tlrow.data)
        tl["export"] = {**tl.get("export", {}), **(ex.settings or {})}
        cap_style = dict(cap.style) if cap else {"id": "podcast_pro"}
        cap_items = list(cap.items) if cap and (ex.settings or {}).get("captions", True) else []
        assets = {a.id: p for a in s.query(AudioAsset).all() if (p := audio_library.resolve_asset_path(a))}
        src = {"path": m.path, "width": m.width, "height": m.height, "has_video": m.has_video, "has_audio": m.has_audio}
        out_dir = Path(ex.settings.get("output_dir") or config.exports_dir())
        title = clip.title or "clip"
        project_id = clip.project_id
        analysis_running = s.query(Job).filter(Job.kind == "analysis", Job.status == "running").count() > 0
    if not analysis_running:
        transcription.unload_models()
    if not Path(src["path"]).exists():
        raise RuntimeError(f"Source media not found at {src['path']} (was it moved or deleted?)")
    out_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(out_dir).free
    if free < 500e6:
        raise OSError(f"Insufficient disk space in export folder ({free / 1e6:.0f} MB free)")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    fname = sanitize_filename(f"{title[:60]} - {tl.get('aspect', '9x16').replace(':', 'x')} - {stamp}.mp4", default="clip.mp4")
    work = storage.project_folder(project_id) / "renders" / export_id
    ctx.progress(0.01, "render", "Building render graph")
    try:
        info = renderer.render(tl, cap_style, cap_items, src, out_dir / fname, work, assets, set(tl.get("keywords", [])),
                               config.get_settings().get("hardware_encoding", "auto"), ctx,
                               lambda p: ctx.progress(0.02 + 0.93 * p, "render", f"Rendering {p * 100:.0f}%"))
        ctx.progress(0.97, "validate", "Validating output with FFprobe")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    with session_scope() as s:
        ex = s.get(ExportJob, export_id)
        ex.status = "completed"
        ex.output_path = info["path"]
        ex.probe = info
        ex.finished_at = utcnow()
    hub.publish("export", {"id": export_id, "status": "completed"})
    return {"path": info["path"], "duration": info["duration"], "size_bytes": info["size_bytes"], "encoder": info["encoder"]}


def render_finished(job_id: str, status: str, info: dict) -> None:
    if status == "completed":
        return
    export_id = (info.get("params") or {}).get("export_id")
    if not export_id:
        return
    with session_scope() as s:
        ex = s.get(ExportJob, export_id)
        if ex:
            ex.status = status
            ex.error = info.get("error")
            ex.finished_at = utcnow()
    hub.publish("export", {"id": export_id, "status": status})


def analysis_finished(job_id: str, status: str, info: dict) -> None:
    if status != "completed" and info.get("project_id"):
        with session_scope() as s:
            p = s.get(Project, info["project_id"])
            if p and p.status == "analyzing":
                has_clips = s.query(CandidateClip).filter(CandidateClip.project_id == p.id).count() > 0
                p.status = "analyzed" if has_clips else "ready"
        hub.publish("project", {"id": info["project_id"], "status": "updated"})


# ------------------------------------------------------------------ model downloads
def handle_model_download(ctx: JobContext) -> dict[str, Any]:
    kind, name = ctx.params["kind"], ctx.params["name"]
    if kind == "whisper":
        spec = transcription.WHISPER_MODELS[name]
        free = shutil.disk_usage(config.MODELS_DIR).free
        if free < spec["size_mb"] * 1e6 * 1.3:
            raise OSError(f"Insufficient disk space for {name}: need {spec['size_mb'] * 1.3:.0f} MB, have {free / 1e6:.0f} MB")
        transcription.download_model(name, lambda p, msg: ctx.progress(p, "download", msg), ctx)
        return {"installed": True, "path": str(transcription.model_dir(name))}
    if kind == "vision" and name == "yunet":
        ctx.progress(0.1, "download", "Downloading YuNet face detector")
        vision.download_yunet()
        return {"installed": True, "path": str(vision.YUNET_PATH)}
    if kind == "ollama":
        with session_scope() as s:
            row = s.query(AIProvider).filter(AIProvider.kind == "ollama").first()
            url = (row.base_url if row and row.base_url else llm.PROVIDER_KINDS["ollama"]["default_url"]).rstrip("/")
        import httpx
        import json as _json

        with httpx.stream("POST", f"{url}/api/pull", json={"model": name, "stream": True}, timeout=None) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                ctx.check_cancel()
                if not line:
                    continue
                d = _json.loads(line)
                if d.get("error"):
                    raise RuntimeError(d["error"])
                if d.get("total"):
                    ctx.progress(d.get("completed", 0) / d["total"], "download", d.get("status"))
        return {"installed": True}
    raise ValueError(f"Unknown model {kind}/{name}")


def register_handlers() -> None:
    manager.register("import", handle_import, import_failed)
    manager.register("download", handle_download, import_failed)
    manager.register("proxy", handle_proxy)
    manager.register("analysis", handle_analysis, analysis_finished)
    manager.register("rediscover", handle_rediscover, analysis_finished)
    manager.register("render", handle_render, render_finished)
    manager.register("model_download", handle_model_download)
