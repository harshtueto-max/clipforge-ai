"""End-to-end smoke test against a running ClipForge backend.

Usage:  .venv\\Scripts\\python.exe scripts\\e2e_smoke.py <video path> [--model small] [--targets 30,60] [--keep]

Creates a project, imports the video, runs the full analysis, prints the AI-selected clips, edits the best one
(trim + caption edit + music), exports it and validates the MP4 with ffprobe.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8765"


def wait_job(c: httpx.Client, job_id: str, label: str, timeout: float = 7200) -> dict:
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{job_id}").json()
        msg = f"[{label}] {j['status']:<9} {j['progress'] * 100:5.1f}%  {j.get('stage') or ''}: {j.get('message') or ''}"
        if msg != last:
            print(msg, flush=True)
            last = msg
        if j["status"] in ("completed", "failed", "cancelled", "interrupted"):
            if j["status"] != "completed":
                raise SystemExit(f"{label} job {j['status']}: {j.get('error')}")
            return j
        time.sleep(2)
    raise SystemExit(f"{label} timed out")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--model", default=None)
    ap.add_argument("--targets", default="30,60")
    ap.add_argument("--preset", default="podcast_pro")
    ap.add_argument("--quality", default="balanced")
    ap.add_argument("--project", default=None, help="reuse an existing project id (skip import)")
    args = ap.parse_args()
    video = Path(args.video).resolve()
    with httpx.Client(base_url=BASE, timeout=120) as c:
        deps = c.get("/api/system/dependencies").json()
        for chk in deps["checks"]:
            print(f"  {'OK ' if chk['ok'] else 'NO '} {chk['name']}: {chk['detail']}")
        if args.model:
            c.put("/api/settings", json={"whisper_model": args.model}).raise_for_status()
        if args.project:
            pid = args.project
        else:
            p = c.post("/api/projects", json={"name": f"E2E {video.stem}"}).json()
            pid = p["id"]
            r = c.post(f"/api/projects/{pid}/import-path", json={"path": str(video), "copy_file": False})
            r.raise_for_status()
            wait_job(c, r.json()["job_id"], "import")
        print("project", pid)
        targets = [float(x) for x in args.targets.split(",")]
        t0 = time.time()
        r = c.post(f"/api/projects/{pid}/analyze", json={"duration_targets": targets, "preset_id": args.preset, "analysis_quality": args.quality})
        r.raise_for_status()
        j = wait_job(c, r.json()["job_id"], "analysis")
        print(f"analysis took {time.time() - t0:.0f}s")
        print(json.dumps(j["result"], indent=1)[:3000])
        clips = c.get(f"/api/projects/{pid}/clips").json()
        print(f"\n{len(clips)} clips discovered:")
        for cl in clips[:12]:
            print(f"  {cl['score']:5.1f} [{cl['target_duration']:.0f}s -> {cl['duration']:.1f}s] {cl['start']:7.1f}-{cl['end']:7.1f} "
                  f"{cl['category']:<11} {cl['title'][:70]}  tags={cl['tags']}")
        best = clips[0]
        print("\nBEST:", best["title"])
        print("  hook:", best["hook"])
        print("  reason:", best["reason"])
        ed = c.get(f"/api/clips/{best['id']}/editor").json()
        tl, cap = ed["timeline"], ed["captions"]
        print(f"  timeline: {tl['start']:.2f}-{tl['end']:.2f}, cuts={len(tl['cuts'])}, zooms={len(tl['zooms'])}, "
              f"keyframes={len(tl['reframe']['keyframes'])}, layouts={len(tl['reframe']['layouts'])}, music={tl['music']['asset_id']}, sfx={len(tl['sfx'])}")
        # manual edits: trim 0.2s at the end, change a caption, set music volume
        tl["end"] = round(tl["end"] - 0.2, 3)
        tl["music"]["volume"] = 0.08
        r = c.put(f"/api/clips/{best['id']}/timeline", json={"data": tl, "base_version": ed["timeline_version"]})
        r.raise_for_status()
        print("  saved timeline:", r.json())
        if cap["items"]:
            cap["items"][0]["style"] = {"color": "#FFE066"}
        c.put(f"/api/clips/{best['id']}/captions", json=cap).raise_for_status()
        c.patch(f"/api/clips/{best['id']}", json={"status": "accepted"}).raise_for_status()
        r = c.post(f"/api/clips/{best['id']}/export", json={"resolution": "1080p", "fps": 30, "codec": "h264"})
        r.raise_for_status()
        ex = r.json()
        t0 = time.time()
        wait_job(c, ex["job_id"], "render")
        print(f"render took {time.time() - t0:.0f}s")
        e = c.get(f"/api/exports/{ex['export_id']}").json()
        print("export:", e["status"], e["output_path"])
        pr = e["probe"]
        print(f"  probe: {pr.get('width')}x{pr.get('height')} {pr.get('duration'):.2f}s video={pr.get('video_codec')} audio={pr.get('audio_codec')} "
              f"size={pr.get('size_bytes', 0) / 1e6:.1f}MB validated={pr.get('validated')}")
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate:format=duration",
                              "-of", "json", e["output_path"]], capture_output=True, text=True)
        print(out.stdout)
        print("E2E OK" if e["status"] == "completed" and pr.get("validated") else "E2E FAILED")


if __name__ == "__main__":
    main()
