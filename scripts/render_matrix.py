"""Render-matrix check against a running server: exercises presets, aspect ratios, split-screen, H.265, 4K, fps."""
import sys
import time

import httpx

B = "http://127.0.0.1:8765"
pid = sys.argv[1]
c = httpx.Client(base_url=B, timeout=300)
clips = c.get(f"/api/projects/{pid}/clips").json()
cases = [
    ("minimal_interview", "9:16", {"resolution": "1080p", "fps": 30, "codec": "h264"}, "split"),
    ("high_retention", "1:1", {"resolution": "720p", "fps": 60, "codec": "h265"}, "auto"),
    ("documentary_shorts", "4:5", {"resolution": "1080p", "fps": 25, "codec": "h264", "bitrate_kbps": 6000}, "auto"),
    ("cinematic_story", "16:9", {"resolution": "4k", "fps": 24, "codec": "h265", "quality": "balanced"}, "center"),
]
ok = True
for (preset, aspect, exp, mode), clip in zip(cases, clips[1:]):
    st = c.post(f"/api/clips/{clip['id']}/apply-preset", json={"preset_id": preset, "aspect": aspect}).json()
    if mode != "auto":
        st2 = c.post(f"/api/clips/{clip['id']}/reframe", json={"mode": mode, "aspect": aspect, "smoothness": 0.8}).json()
        tl = st2["timeline"]
    else:
        tl = st["timeline"]
    print(f"{preset:<20} {aspect:<5} layouts={len(tl['reframe'].get('layouts', []))} zooms={len(tl['zooms'])} cuts={len(tl['cuts'])} "
          f"music={'y' if tl['music']['asset_id'] else 'n'} sfx={len(tl['sfx'])} caption={st['captions']['style'].get('id')}")
    r = c.post(f"/api/clips/{clip['id']}/export", json=exp).json()
    t0 = time.time()
    while True:
        j = c.get(f"/api/jobs/{r['job_id']}").json()
        if j["status"] not in ("queued", "running"):
            break
        time.sleep(2)
    e = c.get(f"/api/exports/{r['export_id']}").json()
    p = e["probe"]
    print(f"   -> {j['status']} in {time.time() - t0:.0f}s {p.get('width')}x{p.get('height')} {p.get('fps', 0):.2f}fps {p.get('video_codec')} "
          f"{p.get('duration', 0):.2f}s validated={p.get('validated')} {e.get('error') or ''}")
    ok &= j["status"] == "completed"
print("MATRIX OK" if ok else "MATRIX FAILED")
