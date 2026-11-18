"""Integration / end-to-end tests that exercise the real pipeline: FFmpeg import, Faster-Whisper transcription,
VAD, scene detection, clip discovery, auto-edit, caption burn-in, FFmpeg render + FFprobe validation, persistence,
and failure modes (invalid media, missing FFmpeg, missing model, offline mode, failed cloud provider, interrupted jobs,
insufficient disk space).

A short sample video with real synthesized speech is generated locally with Windows SAPI text-to-speech + FFmpeg,
so the tests need no downloads beyond an installed Whisper model (tiny/base/small).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.services import media, transcription

SCRIPT = (
    "Here's the thing most people get wrong about productivity. They think working longer hours means getting more done. "
    "But the research says something very different. In one study of ten thousand office workers, people who took regular breaks "
    "finished more tasks than people who never stopped. "
    "So what should you actually do? Work in focused blocks of fifty minutes, then rest for ten. "
    "That's the whole secret. It sounds simple, but it changed everything for me. "
    "Now let me tell you a story. When I started my first company, I worked every single night until two in the morning. "
    "I was exhausted, I made terrible decisions, and we almost ran out of money. "
    "The lesson is clear. Rest is not the opposite of work. Rest is part of the work."
)

AVAILABLE_MODEL = next((m for m in ("tiny", "base", "small") if transcription.is_installed(m)), None)
needs_ffmpeg = pytest.mark.skipif(not media.ffmpeg_bin(), reason="FFmpeg not installed")
needs_model = pytest.mark.skipif(AVAILABLE_MODEL is None, reason="No Whisper model installed (run scripts/download_model.py base)")


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("media")
    wav = d / "speech.wav"
    if os.name != "nt":
        pytest.skip("SAPI speech synthesis requires Windows")
    ps = (
        "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Rate = 1; "
        f"$s.SetOutputToWaveFile('{wav}'); $s.Speak(@'\n{SCRIPT}\n'@); $s.Dispose()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=180)
    assert wav.exists() and wav.stat().st_size > 10000
    out = d / "sample talk.mp4"
    dur = media.probe(wav)["duration"]
    subprocess.run([media.ffmpeg_bin(), "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size=1280x720:rate=30:duration={dur:.2f}",
                    "-i", str(wav), "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out)],
                   check=True, timeout=300)
    return out


def wait(client: TestClient, job_id: str, timeout: float = 900) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] in ("completed", "failed", "cancelled", "interrupted"):
            return j
        time.sleep(0.5)
    raise AssertionError("job timeout")


@pytest.fixture(scope="module")
def client():
    from app.main import app

    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------------ full pipeline
@needs_ffmpeg
@needs_model
def test_full_pipeline_import_analyze_edit_export_reopen(client, sample_video):
    client.put("/api/settings", json={"whisper_model": AVAILABLE_MODEL, "analysis_quality": "fast", "copy_imports": True})
    pid = client.post("/api/projects", json={"name": "Integration"}).json()["id"]
    # import (copy into project)
    r = client.post(f"/api/projects/{pid}/import-path", json={"path": str(sample_video), "copy_file": True})
    assert r.status_code == 200, r.text
    j = wait(client, r.json()["job_id"])
    assert j["status"] == "completed", j["error"]
    proj = client.get(f"/api/projects/{pid}").json()
    assert proj["status"] == "ready" and proj["media"]["width"] == 1280 and proj["media"]["has_audio"]
    assert client.get(f"/api/projects/{pid}/thumbnail").status_code == 200
    wf = client.get(f"/api/projects/{pid}/waveform?points=100").json()
    assert len(wf["peaks"]) == 100 and max(wf["peaks"]) > 0
    # streaming supports HTTP range requests (no full load in browser)
    rs = client.get(f"/api/projects/{pid}/media/stream", headers={"Range": "bytes=0-1023"})
    assert rs.status_code == 206 and len(rs.content) == 1024

    # analysis
    r = client.post(f"/api/projects/{pid}/analyze", json={"duration_targets": [20, 30], "duration_tolerance": 0.35, "use_ai_provider": False})
    assert r.status_code == 200, r.text
    j = wait(client, r.json()["job_id"], timeout=1800)
    assert j["status"] == "completed", j["error"]
    st = j["result"]["stages"]
    assert st["transcribe"]["words"] > 50 and st["transcribe"]["language"] == "en"
    assert st["vision"]["scenes"] >= 1
    tr = client.get(f"/api/projects/{pid}/transcript").json()
    assert "productivity" in " ".join(w["w"].lower() for w in tr["words"])
    assert all(tr["words"][k]["s"] <= tr["words"][k + 1]["s"] for k in range(len(tr["words"]) - 1))

    clips = client.get(f"/api/projects/{pid}/clips").json()
    assert clips, "discovery should produce at least one clip"
    best = clips[0]
    assert 0 < best["score"] <= 100 and best["title"] and best["reason"]
    assert all(set(c["scores"]) >= {"hook", "story", "engagement", "emotion", "information", "standalone", "av_quality"} for c in clips)
    assert best["transcript"] and best["transcript"].split()[0].lower() in tr["words"][0]["w"].lower() + " " + " ".join(
        w["w"].lower() for w in tr["words"])

    # editor: automatic first edit exists and is editable
    ed = client.get(f"/api/clips/{best['id']}/editor").json()
    tl = ed["timeline"]
    assert tl["aspect"] == "9:16" and ed["captions"]["items"]
    tl["end"] = round(tl["end"] - 0.3, 3)
    tl["cuts"] = tl["cuts"] + [{"s": tl["start"] + 2.0, "e": tl["start"] + 2.5}]
    tl["music"]["volume"] = 0.07
    r = client.put(f"/api/clips/{best['id']}/timeline", json={"data": tl, "base_version": ed["timeline_version"]})
    assert r.status_code == 200, r.text
    caps = ed["captions"]
    caps["items"][0]["text"] = caps["items"][0]["text"].upper()
    assert client.put(f"/api/clips/{best['id']}/captions", json=caps).status_code == 200
    # undo-able ops and regeneration helpers
    assert client.post(f"/api/clips/{best['id']}/rescore").status_code == 200
    dup = client.post(f"/api/clips/{best['id']}/duplicate").json()
    assert dup["parent_id"] == best["id"]
    assert client.patch(f"/api/clips/{best['id']}", json={"status": "accepted"}).json()["status"] == "accepted"

    # export + validation
    r = client.post(f"/api/clips/{best['id']}/export", json={"resolution": "720p", "fps": 30, "codec": "h264", "quality": "balanced"})
    assert r.status_code == 200, r.text
    j = wait(client, r.json()["job_id"], timeout=900)
    assert j["status"] == "completed", j["error"]
    ex = client.get(f"/api/exports/{r.json()['export_id']}").json()
    assert ex["status"] == "completed" and ex["probe"]["validated"]
    out = Path(ex["output_path"])
    info = media.probe(out)
    assert (info["width"], info["height"]) == (720, 1280) and info["has_audio"] and info["has_video"]
    saved = client.get(f"/api/clips/{best['id']}/editor").json()["timeline"]
    expected = saved["end"] - saved["start"] - sum(min(c["e"], saved["end"]) - max(c["s"], saved["start"]) for c in saved["cuts"]
                                                   if c["e"] > saved["start"] and c["s"] < saved["end"])
    assert abs(info["duration"] - expected) < 0.6

    # persistence: a fresh app instance (simulated restart) reopens the same state
    from app.main import app

    with TestClient(app) as c2:
        p2 = c2.get(f"/api/projects/{pid}").json()
        assert p2["status"] == "analyzed" and p2["clip_count"] >= len(clips)
        ed2 = c2.get(f"/api/clips/{best['id']}/editor").json()
        assert ed2["timeline"]["music"]["volume"] == 0.07
        assert ed2["captions"]["items"][0]["text"] == caps["items"][0]["text"]
        assert any(e["id"] == ex["id"] for e in c2.get("/api/exports").json())


# ------------------------------------------------------------------ failure modes
def test_invalid_media_is_rejected(client, tmp_path):
    bad = tmp_path / "broken.mp4"
    bad.write_bytes(b"this is not a video" * 100)
    pid = client.post("/api/projects", json={"name": "Invalid"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/import-path", json={"path": str(bad), "copy_file": False})
    j = wait(client, r.json()["job_id"])
    assert j["status"] == "failed" and "FFprobe" in j["error"]
    assert client.get(f"/api/projects/{pid}").json()["status"] == "error"
    r = client.post(f"/api/projects/{pid}/import-path", json={"path": str(tmp_path / "missing.mp4")})
    assert r.status_code == 400
    r = client.post(f"/api/projects/{pid}/import-path", json={"path": "C:\\Windows\\win.ini"})
    assert r.status_code == 400


def test_missing_ffmpeg_reports_clear_error(monkeypatch):
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    with pytest.raises(media.MediaError, match="FFmpeg"):
        media.require_ffmpeg()


def test_missing_model_reports_install_hint(monkeypatch):
    monkeypatch.setattr(transcription, "is_installed", lambda name: False)
    with pytest.raises(RuntimeError, match="not installed"):
        transcription.load_model("medium")


def test_offline_mode_blocks_cloud_and_youtube(client):
    client.put("/api/settings", json={"offline_mode": True})
    try:
        pid = client.post("/api/projects", json={"name": "Offline"}).json()["id"]
        r = client.post(f"/api/projects/{pid}/import-youtube", json={"url": "https://youtu.be/dQw4w9WgXcQ", "confirm_rights": True})
        assert r.status_code == 400 and "Offline" in r.json()["detail"]
        prov = client.post("/api/ai/providers", json={"name": "Cloud", "kind": "openai", "api_key": "sk-test"}).json()
        assert prov["has_key"] and "api_key" not in prov
        client.post(f"/api/ai/providers/{prov['id']}/acknowledge")
        r = client.put(f"/api/ai/providers/{prov['id']}", json={"enabled": True})
        assert r.status_code == 400
        t = client.post(f"/api/ai/providers/{prov['id']}/test").json()
        assert t["last_test"]["ok"] is False and "Offline" in t["last_test"]["error"]
        assert client.post("/api/models/download", json={"kind": "whisper", "name": "tiny"}).status_code == 400
        client.delete(f"/api/ai/providers/{prov['id']}")
    finally:
        client.put("/api/settings", json={"offline_mode": False})


def test_cloud_provider_requires_privacy_ack_and_failures_are_reported(client):
    prov = client.post("/api/ai/providers", json={"name": "Unreachable", "kind": "openai_compatible", "base_url": "https://127.0.0.2:9/v1",
                                                  "model": "x"}).json()
    assert prov["is_local"] is False and prov["privacy_acknowledged"] is False
    assert client.put(f"/api/ai/providers/{prov['id']}", json={"enabled": True}).status_code == 400
    client.post(f"/api/ai/providers/{prov['id']}/acknowledge")
    assert client.put(f"/api/ai/providers/{prov['id']}", json={"enabled": True}).json()["enabled"] is True
    t = client.post(f"/api/ai/providers/{prov['id']}/test").json()
    assert t["last_test"]["ok"] is False and "connection failed" in t["last_test"]["error"]
    # analysis pipeline falls back to local scoring when the provider fails
    from app.services import discovery, llm, pipeline
    from tests.conftest import make_words
    from app.services import segmentation

    words = make_words(SCRIPT)
    b = discovery.prepare(discovery.Bundle(duration=words[-1]["e"], words=words, sentences=segmentation.build_sentences(words), has_video=False))
    cands = discovery.discover(b, [20], 0.4)
    cfgp = pipeline._enabled_provider()
    assert cfgp is not None
    with pytest.raises(llm.ProviderError):
        pipeline.refine_with_llm(cfgp, b, cands, 0.4, discovery.DEFAULT_WEIGHTS, type("C", (), {"check_cancel": lambda self: None})())
    client.delete(f"/api/ai/providers/{prov['id']}")


def test_interrupted_jobs_are_recovered():
    from app.db import session_scope
    from app.jobs import manager
    from app.models import Job

    with session_scope() as s:
        j = Job(kind="analysis", status="running", params={})
        s.add(j)
        s.flush()
        jid = j.id
    assert manager.recover() >= 1
    with session_scope() as s:
        assert s.get(Job, jid).status == "interrupted"


def test_insufficient_disk_space_is_reported(client, tmp_path, monkeypatch, sample_video):
    from app.services import pipeline

    real = shutil.disk_usage

    def tiny(path):
        u = real(path)
        return type(u)(u.total, u.total - 1000, 1000)

    monkeypatch.setattr(pipeline.shutil, "disk_usage", tiny)
    pid = client.post("/api/projects", json={"name": "Disk"}).json()["id"]
    r = client.post(f"/api/projects/{pid}/import-path", json={"path": str(sample_video), "copy_file": True})
    j = wait(client, r.json()["job_id"])
    assert j["status"] == "failed" and "disk space" in j["error"].lower()


@needs_ffmpeg
def test_cpu_only_transcription_path(sample_video, tmp_path):
    if AVAILABLE_MODEL is None:
        pytest.skip("no model")
    wav = media.extract_audio(sample_video, tmp_path / "a.wav", duration=30)
    out = transcription.transcribe(wav, media.probe(wav)["duration"], "tiny" if transcription.is_installed("tiny") else AVAILABLE_MODEL, "cpu")
    assert out["device"] == "cpu" and len(out["words"]) > 30
    transcription.unload_models()


def test_cancel_job(client):
    from app.jobs import manager

    def slow(ctx):
        for _ in range(100):
            ctx.progress(0.1, "wait")
            time.sleep(0.05)
        return {}

    manager.register("test_slow", slow)
    jid = manager.submit("test_slow", None, {})
    time.sleep(0.3)
    assert client.post(f"/api/jobs/{jid}/cancel").json()["cancelled"]
    assert wait(client, jid)["status"] == "cancelled"


def test_path_security_and_host_guard(client):
    r = client.get("/api/health", headers={"host": "evil.example.com"})
    assert r.status_code == 403
    r = client.put("/api/settings", json={"exports_dir": "relative/path"})
    assert r.status_code == 400
    r = client.put("/api/settings", json={"exports_dir": "C:\\Windows\\System32"})
    assert r.status_code == 400
    r = client.post("/api/projects/nope/upload", headers={"x-filename": "a.mp4"}, content=b"x")
    assert r.status_code == 404


def test_custom_presets_crud_and_caption_overrides(client):
    presets = client.get("/api/presets").json()
    builtins = [p for p in presets if p["builtin"]]
    assert len(builtins) == 8
    # built-in presets are protected against modification/deletion
    assert client.delete("/api/presets/podcast_pro").status_code == 400
    assert client.put("/api/presets/podcast_pro", json={"name": "Hack", "description": "", "config": {}}).status_code == 400

    # duplicate built-in preset
    dup = client.post("/api/presets/podcast_pro/duplicate").json()
    assert dup["builtin"] is False and "copy" in dup["name"]

    # create custom preset with caption_overrides and verify autoedit honours overrides
    cfg = dict(dup["config"])
    cfg["caption_overrides"] = {"color": "#FFE066", "words_per_caption": 3}
    created = client.post("/api/presets", json={"name": "Studio Gold", "description": "Custom gold captions", "config": cfg}).json()
    assert created["builtin"] is False and created["name"] == "Studio Gold"

    from app.services import autoedit, segmentation
    from tests.conftest import make_words

    words = make_words("Testing custom preset caption overrides across several spoken words.")
    sents = segmentation.build_sentences(words)
    _, cap_style, items = autoedit.build_timeline(
        {"start": 0.0, "end": words[-1]["e"]}, words, sents, None, [], {}, 1920, 1080, created["id"], created["config"], None, None
    )
    assert cap_style["color"] == "#FFE066" and cap_style["words_per_caption"] == 3 and len(items) >= 2

    # update custom preset
    upd = client.put(f"/api/presets/{created['id']}", json={"name": "Studio Platinum", "description": "Updated", "config": cfg}).json()
    assert upd["name"] == "Studio Platinum"

    assert client.delete(f"/api/presets/{dup['id']}").status_code == 200
    assert client.delete(f"/api/presets/{created['id']}").status_code == 200


def test_settings_validation_and_spa_serving(client):
    assert client.put("/api/settings", json={"score_weights": {"hook": 0, "story": 0}}).status_code == 400
    assert client.put("/api/settings", json={"duration_targets": [1]}).status_code == 400
    s = client.put("/api/settings", json={"duration_targets": [30, 75, 120], "score_weights": {"hook": 25, "story": 25, "engagement": 15, "emotion": 10, "information": 10, "standalone": 10, "av_quality": 5}}).json()
    assert s["duration_targets"] == [30.0, 75.0, 120.0] and s["score_weights"]["hook"] == 25.0
    if (config.FRONTEND_DIST / "index.html").exists():
        for route in ("/", "/settings", "/library"):
            resp = client.get(route)
            assert resp.status_code == 200 and "ClipForge AI" in resp.text


def test_delete_local_data_wipes_custom_presets_and_projects(client):
    assert client.delete("/api/system/data?confirm=NOPE").status_code == 400
    pid = client.post("/api/projects", json={"name": "Temp Wipe"}).json()["id"]
    dup = client.post("/api/presets/podcast_pro/duplicate").json()
    res = client.delete("/api/system/data?confirm=DELETE&include_exports=false&include_models=false")
    assert res.status_code == 200 and res.json()["deleted"] is True
    assert client.get(f"/api/projects/{pid}").status_code == 404
    remaining_presets = client.get("/api/presets").json()
    assert all(p["builtin"] for p in remaining_presets) and len(remaining_presets) == 8
    assert dup["id"] not in {p["id"] for p in remaining_presets}


@needs_ffmpeg
def test_live_stream_dvr_flash_clip_editor_and_export(client, sample_video):
    from app.security import SecurityError, validate_youtube_live_url
    from app.services.live_stream import live_manager

    # 1. URL validation supports /live/<id> and @Channel/live while rejecting non-YouTube hosts
    assert validate_youtube_live_url("https://www.youtube.com/live/dQw4w9WgXcQ").endswith("dQw4w9WgXcQ")
    assert validate_youtube_live_url("https://www.youtube.com/@SamayRainaOfficial/live") == "https://www.youtube.com/@SamayRainaOfficial/live"
    with pytest.raises(SecurityError):
        validate_youtube_live_url("https://evil.example.com/@Channel/live")

    # 2. Rights confirmation & offline mode checks
    assert client.post("/api/live/sessions", json={"url": "https://www.youtube.com/live/dQw4w9WgXcQ", "confirm_rights": False}).status_code == 400
    client.put("/api/settings", json={"offline_mode": True})
    try:
        assert client.post("/api/live/sessions", json={"url": "https://www.youtube.com/live/dQw4w9WgXcQ", "confirm_rights": True}).status_code == 400
    finally:
        client.put("/api/settings", json={"offline_mode": False})

    # 3. Live HLS DVR capture -> Flash Clip -> Editor state -> MP4 export -> DVR cleanup
    sess = live_manager.create(
        local_source=sample_video,
        title_override="Live Podcast Test",
        language="hinglish",
        preset_id="podcast_pro",
        aspect="9:16",
        auto_highlight=False,
        dvr_minutes=15,
        pace_realtime=False,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            sess.sync_playlist()
            if sess.dvr_end >= 12.0 and (sess.hls_dir / "live.m3u8").exists():
                break
            time.sleep(0.25)
        assert sess.dvr_end >= 10.0

        detail = client.get(f"/api/live/sessions/{sess.id}").json()
        assert detail["playlist_ready"] is True
        m3u8 = client.get(f"/api/live/sessions/{sess.id}/hls/live.m3u8")
        assert m3u8.status_code == 200 and "#EXTINF:" in m3u8.text and "seg_" in m3u8.text
        first_seg = next(line.strip() for line in m3u8.text.splitlines() if line.strip().endswith(".ts"))
        assert client.get(f"/api/live/sessions/{sess.id}/hls/{first_seg}").status_code == 200
        assert client.get(f"/api/live/sessions/{sess.id}/hls/session.json").status_code == 400

        # Update options on the fly
        upd = client.patch(f"/api/live/sessions/{sess.id}", json={"language": "en", "aspect": "9:16"}).json()
        assert upd["language"] == "en"

        # Flash clip last 12 seconds synchronously via ?wait=true
        clip_res = client.post(
            f"/api/live/sessions/{sess.id}/clip?wait=true",
            json={"mode": "last", "duration": 12.0, "title": "First Place Live Short"},
        )
        assert clip_res.status_code == 200, clip_res.text
        cid = clip_res.json()["clip_id"]

        # Verify captured clip appears in session tray AND opens cleanly in full Clip Editor
        tray = client.get(f"/api/live/sessions/{sess.id}").json()
        assert any(c["id"] == cid for c in tray["clips"])
        ed = client.get(f"/api/clips/{cid}/editor")
        assert ed.status_code == 200
        ed_json = ed.json()
        assert ed_json["timeline"]["aspect"] == "9:16"
        assert ed_json["media"]["duration"] > 5.0

        # Verify 1-click MP4 export succeeds on the live-captured clip
        ex = client.post(f"/api/clips/{cid}/export", json={"resolution": "720p", "fps": 30, "codec": "h264", "quality": "balanced", "audio_bitrate_kbps": 128, "captions": True}).json()
        j = wait(client, ex["job_id"], timeout=180)
        assert j["status"] == "completed", j
        assert Path(j["result"]["path"]).exists()
    finally:
        assert client.delete(f"/api/live/sessions/{sess.id}").status_code == 200
    # Captured clip still exists after DVR buffer deletion
    assert client.get(f"/api/clips/{cid}").status_code == 200


def test_builtin_audio_relocation_self_heals_paths_and_deduplicates(client):
    from app.db import session_scope
    from app.models import AudioAsset
    from app.services import audio_library

    with session_scope() as s:
        rows = s.query(AudioAsset).filter(AudioAsset.origin == "builtin").all()
        assert len(rows) > 0
        orig_count = len(rows)
        first = rows[0]
        first.path = r"C:\MovedFromOldFolder\clip Master\assets\audio\music\\" + Path(first.path).name
        # Simulate a duplicate row created before the fix
        s.add(AudioAsset(kind=first.kind, category=first.category, name=first.name, path=first.path,
                         duration=first.duration, moods=first.moods, bpm=first.bpm, license=first.license, origin="builtin"))

    with session_scope() as s:
        audio_library.sync_builtin(s)
        healed = s.query(AudioAsset).filter(AudioAsset.origin == "builtin").all()
        assert len(healed) == orig_count
        assert all(Path(a.path).is_file() for a in healed)


