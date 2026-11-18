"""FFmpeg render engine: turns a non-destructive timeline into a finished, validated MP4."""
from __future__ import annotations

import logging
import math
import shutil
from pathlib import Path
from typing import Any

from . import captions, media, reframe, segmentation

log = logging.getLogger("clipforge.render")


class RenderError(RuntimeError):
    pass


def _even(x: float) -> int:
    v = int(round(x))
    return max(2, v - (v % 2))


def output_size(aspect: str, resolution: str) -> tuple[int, int]:
    sizes = reframe.OUTPUT_SIZES.get(aspect) or reframe.OUTPUT_SIZES["9:16"]
    return sizes.get(resolution, sizes["1080p"])


def build_pieces(tl: dict[str, Any]) -> list[dict[str, Any]]:
    """Split kept segments at zoom / layout boundaries so each piece has a constant zoom and layout."""
    segs = segmentation.keep_segments(tl["start"], tl["end"], tl.get("cuts", []))
    marks = set()
    for z in tl.get("zooms", []):
        marks.update([z["s"], z["e"]])
    for l in tl.get("reframe", {}).get("layouts", []):
        marks.update([l["s"], l["e"]])
    pieces = []
    for s, e in segs:
        pts = sorted([s, e] + [m for m in marks if s + 0.25 < m < e - 0.25])
        for a, b in zip(pts, pts[1:]):
            if b - a < 0.04:
                continue
            mid = (a + b) / 2
            zoom = 1.0
            for z in tl.get("zooms", []):
                if z["s"] <= mid < z["e"]:
                    zoom = float(z.get("scale", 1.0))
            layout = None
            for l in tl.get("reframe", {}).get("layouts", []):
                if l["s"] <= mid < l["e"] and l.get("layout") == "split":
                    layout = l
            pieces.append({"s": round(a, 3), "e": round(b, 3), "zoom": zoom, "layout": layout})
    return pieces


def _piecewise(points: list[tuple[float, float]], var: str = "t") -> str:
    """Piecewise-linear ffmpeg expression through (time, value) points (time relative to piece start)."""
    if not points:
        return "0"
    if len(points) == 1:
        return f"{points[0][1]:.2f}"
    expr = f"{points[-1][1]:.2f}"
    for (t0, v0), (t1, v1) in reversed(list(zip(points, points[1:]))):
        if t1 - t0 < 1e-3:
            seg = f"{v1:.2f}"
        else:
            slope = (v1 - v0) / (t1 - t0)
            seg = f"({v0:.2f}+({slope:.4f})*({var}-{t0:.3f}))"
        expr = f"if(lt({var},{t1:.3f}),{seg},{expr})"
    return expr


def _crop_expr(tl: dict[str, Any], piece: dict[str, Any], src_w: int, src_h: int) -> str:
    aspect = tl.get("aspect", "9:16")
    rf = tl.get("reframe", {}) or {}
    cw, ch = reframe.crop_box(src_w, src_h, aspect, piece["zoom"])
    cw_px, ch_px = _even(cw * src_w), _even(ch * src_h)
    cw_px, ch_px = min(cw_px, src_w - (src_w % 2)), min(ch_px, src_h - (src_h % 2))
    off = rf.get("offset") or {"x": 0.0, "y": 0.0}
    kfs = rf.get("keyframes") or [{"t": tl["start"], "x": 0.5, "y": 0.5}]
    if rf.get("mode") == "center":
        kfs = [{"t": tl["start"], "x": 0.5, "y": 0.5}]
    a, b = piece["s"], piece["e"]
    times = [a] + [k["t"] for k in kfs if a < k["t"] < b] + [b]
    # thin very dense keyframe sets to keep expressions small
    if len(times) > 40:
        step = math.ceil(len(times) / 40)
        times = times[::step] + [b]
    xs, ys = [], []
    for t in times:
        cx, cy = reframe.position_at(kfs, t)
        cx = cx + float(off.get("x", 0))
        cy = cy + float(off.get("y", 0))
        x = min(max(cx * src_w - cw_px / 2, 0), src_w - cw_px)
        y = min(max(cy * src_h - ch_px / 2, 0), src_h - ch_px)
        xs.append((t - a, x))
        ys.append((t - a, y))
    x_expr = _piecewise(xs) if len({round(v) for _, v in xs}) > 1 else f"{xs[0][1]:.2f}"
    y_expr = _piecewise(ys) if len({round(v) for _, v in ys}) > 1 else f"{ys[0][1]:.2f}"
    return f"crop=w={cw_px}:h={ch_px}:x='{x_expr}':y='{y_expr}'"


def _split_crop(src_w, src_h, cx, cy, half_ar) -> str:
    ch = src_h * 0.82
    cw = ch * half_ar
    if cw > src_w * 0.5:
        cw = src_w * 0.5
        ch = cw / half_ar
    cw_px, ch_px = _even(cw), _even(ch)
    x = min(max(cx * src_w - cw_px / 2, 0), src_w - cw_px)
    y = min(max(cy * src_h - ch_px * 0.42, 0), src_h - ch_px)
    return f"crop={cw_px}:{ch_px}:{x:.0f}:{y:.0f}"


def plan(tl: dict[str, Any], cap_style: dict[str, Any], cap_items: list[dict[str, Any]], src: dict[str, Any],
         out_path: Path, work: Path, asset_paths: dict[str, str], keywords: set[str], encoder_pref: str = "auto") -> dict[str, Any]:
    ffmpeg, _ = media.require_ffmpeg()
    exp = tl.get("export", {})
    W, H = output_size(tl.get("aspect", "9:16"), exp.get("resolution", "1080p"))
    fps = int(exp.get("fps", 30))
    if fps not in (24, 25, 30, 50, 60):
        fps = 30
    src_w, src_h = int(src.get("width") or 1920), int(src.get("height") or 1080)
    has_video, has_audio = bool(src.get("has_video", True)), bool(src.get("has_audio", True))
    pieces = build_pieces(tl)
    if not pieces:
        raise RenderError("Timeline has no content left after cuts")
    segs = segmentation.keep_segments(tl["start"], tl["end"], tl.get("cuts", []))
    out_dur = sum(p["e"] - p["s"] for p in pieces)
    t0 = tl["start"]
    t_end = tl["end"]
    inputs: list[str] = ["-ss", f"{t0:.3f}", "-t", f"{max(1.0, (t_end - t0) + 0.5):.3f}", "-i", str(src["path"])]
    n_in = 1
    fg: list[str] = []
    N = len(pieces)
    if has_video:
        if N > 1:
            fg.append(f"[0:v]split={N}" + "".join(f"[vi{k}]" for k in range(N)))
        else:
            fg.append("[0:v]null[vi0]")
    if has_audio:
        if N > 1:
            fg.append(f"[0:a]asplit={N}" + "".join(f"[ai{k}]" for k in range(N)))
        else:
            fg.append("[0:a]anull[ai0]")
    for k, p in enumerate(pieces):
        a, b = p["s"] - t0, p["e"] - t0
        if has_video:
            base = f"[vi{k}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS"
            if p["layout"]:
                lay = p["layout"]
                half_ar = W / (H / 2)
                top = _split_crop(src_w, src_h, lay["top"]["x"], lay["top"]["y"], half_ar)
                bot = _split_crop(src_w, src_h, lay["bottom"]["x"], lay["bottom"]["y"], half_ar)
                fg.append(f"{base},split=2[sa{k}][sb{k}]")
                fg.append(f"[sa{k}]{top},scale={W}:{H // 2}:flags=lanczos,setsar=1[st{k}]")
                fg.append(f"[sb{k}]{bot},scale={W}:{H - H // 2}:flags=lanczos,setsar=1[sbb{k}]")
                fg.append(f"[st{k}][sbb{k}]vstack=inputs=2,fps={fps},format=yuv420p[v{k}]")
            else:
                crop = _crop_expr(tl, p, src_w, src_h)
                fg.append(f"{base},{crop},scale={W}:{H}:flags=lanczos,setsar=1,fps={fps},format=yuv420p[v{k}]")
        if has_audio:
            d = b - a
            fd = min(0.012, d / 4)
            fg.append(f"[ai{k}]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
                      f"apad=whole_dur={d:.3f},atrim=0:{d:.3f},"
                      f"afade=t=in:d={fd:.3f},afade=t=out:st={max(0, d - fd):.3f}:d={fd:.3f}[a{k}]")
    if not has_video:
        inputs += ["-f", "lavfi", "-t", f"{out_dur:.3f}", "-i", f"color=c=0x101114:s={W}x{H}:r={fps}"]
        vin = n_in
        n_in += 1
    if has_video and has_audio:
        fg.append("".join(f"[v{k}][a{k}]" for k in range(N)) + f"concat=n={N}:v=1:a=1[vc][voice0]")
    elif has_video:
        fg.append("".join(f"[v{k}]" for k in range(N)) + f"concat=n={N}:v=1:a=0[vc]")
        inputs += ["-f", "lavfi", "-t", f"{out_dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        fg.append(f"[{n_in}:a]anull[voice0]")
        n_in += 1
    else:
        fg.append("".join(f"[a{k}]" for k in range(N)) + f"concat=n={N}:v=0:a=1[voice0]")
        fg.append(f"[voice0]asplit=2[voice0b][wv]")
        fg.append(f"[wv]showwaves=s={W}x{H // 3}:mode=cline:colors=white:rate={fps}[wave]")
        fg.append(f"[{vin}:v][wave]overlay=0:(H-h)/2[vc]")
    voice_label = "voice0" if has_video else "voice0b"

    # captions
    vlabel = "vc"
    if cap_items:
        st = captions.style_for(cap_style.get("id", "podcast_pro"), {k: v for k, v in cap_style.items() if k != "id"})
        ass = work / "captions.ass"
        captions.write_ass(ass, cap_items, st, W, H, segs, keywords)
        fg.append(f"[vc]subtitles=filename=captions.ass[vcap]")
        vlabel = "vcap"

    # voice processing
    au = tl.get("audio", {}) or {}
    chain = []
    if au.get("denoise"):
        chain.append("afftdn=nf=-25")
    if au.get("enhance_voice", True):
        chain += ["highpass=f=80", "equalizer=f=3200:t=q:w=1.2:g=2.5", "acompressor=threshold=-21dB:ratio=3:attack=8:release=180:makeup=2"]
    if float(au.get("voice_gain_db", 0) or 0) != 0:
        chain.append(f"volume={float(au['voice_gain_db']):.1f}dB")
    fg.append(f"[{voice_label}]{','.join(chain) if chain else 'anull'}[vp]")

    mix_inputs = []
    music = tl.get("music") or {}
    music_path = asset_paths.get(music.get("asset_id") or "")
    if music_path:
        inputs += ["-stream_loop", "-1", "-i", music_path]
        mi = n_in
        n_in += 1
        vol = max(0.0, min(1.0, float(music.get("volume", 0.1))))
        fi = max(0.0, float(music.get("fade_in", 1.0)))
        fo = max(0.0, float(music.get("fade_out", 1.5)))
        off = max(0.0, float(music.get("offset", 0.0)))
        mchain = (f"[{mi}:a]atrim=start={off:.3f}:end={off + out_dur:.3f},asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
                  f"volume={vol:.3f}")
        if fi > 0:
            mchain += f",afade=t=in:d={min(fi, out_dur / 2):.2f}"
        if fo > 0:
            mchain += f",afade=t=out:st={max(0, out_dur - fo):.2f}:d={min(fo, out_dur / 2):.2f}"
        fg.append(mchain + "[mus]")
        if music.get("ducking", True):
            fg.append("[vp]asplit=2[vpm][vsc]")
            fg.append("[mus][vsc]sidechaincompress=threshold=0.02:ratio=9:attack=15:release=350:makeup=1[musd]")
            mix_inputs += ["[vpm]", "[musd]"]
        else:
            mix_inputs += ["[vp]", "[mus]"]
    else:
        mix_inputs.append("[vp]")
    for k, fx in enumerate(tl.get("sfx", []) or []):
        pth = asset_paths.get(fx.get("asset_id") or "")
        if not pth:
            continue
        ot = segmentation.source_to_output(float(fx["t"]), segs)
        if ot is None:
            # snap to the next kept segment
            later = [segmentation.source_to_output(s, segs) for s, _ in segs if s >= fx["t"]]
            ot = later[0] if later else None
        if ot is None or ot >= out_dur:
            continue
        inputs += ["-i", pth]
        si = n_in
        n_in += 1
        ms = int(ot * 1000)
        fg.append(f"[{si}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={max(0.0, min(1.5, float(fx.get('volume', 0.4)))):.2f},"
                  f"adelay={ms}|{ms}[sfx{k}]")
        mix_inputs.append(f"[sfx{k}]")
    loud = float(au.get("loudness", -14))
    if len(mix_inputs) > 1:
        fg.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:duration=first:normalize=0:dropout_transition=0[mix]")
        last = "[mix]"
    else:
        last = mix_inputs[0]
    fg.append(f"{last}loudnorm=I={loud:.1f}:TP=-1.5:LRA=11,aresample=48000,alimiter=limit=0.95[aout]")

    graph = ";\n".join(fg)
    (work / "filter.txt").write_text(graph, encoding="utf-8")

    # encoder
    codec = exp.get("codec", "h264")
    quality = exp.get("quality", "high")
    br = exp.get("bitrate_kbps")
    venc: list[str]
    use_hw = encoder_pref != "off"
    cq = {"high": 20, "balanced": 23, "small": 27}.get(quality, 21)
    if codec == "h265":
        if use_hw and media.encoder_works("hevc_nvenc"):
            venc = ["-c:v", "hevc_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq + 2)]
        else:
            venc = ["-c:v", "libx265", "-preset", "medium", "-crf", str(cq + 3)]
        venc += ["-tag:v", "hvc1"]
    else:
        if use_hw and media.encoder_works("h264_nvenc"):
            venc = ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", str(cq), "-profile:v", "high"]
        else:
            venc = ["-c:v", "libx264", "-preset", "medium", "-crf", str(cq - 1), "-profile:v", "high"]
    if br:
        br = int(br)
        venc = [x for x in venc]
        venc += ["-b:v", f"{br}k", "-maxrate", f"{int(br * 1.5)}k", "-bufsize", f"{br * 2}k"]
    elif "nvenc" in venc[1]:
        venc += ["-b:v", "0"]
    abr = int(exp.get("audio_bitrate_kbps") or 192)
    cmd = [ffmpeg, "-y", "-v", "error", "-nostdin", *inputs, "-/filter_complex", "filter.txt", "-map", f"[{vlabel}]", "-map", "[aout]",
           *venc, "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", f"{abr}k", "-ar", "48000", "-movflags", "+faststart",
           "-t", f"{out_dur:.3f}", "-progress", "pipe:1", str(out_path)]
    return {"cmd": cmd, "duration": out_dur, "width": W, "height": H, "fps": fps, "pieces": len(pieces), "encoder": venc[1]}


def validate(path: Path, expected_duration: float, width: int, height: int) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 1024:
        raise RenderError("Output file missing or empty")
    info = media.probe(path)
    problems = []
    if not info["has_video"]:
        problems.append("no video stream")
    if not info["has_audio"]:
        problems.append("no audio stream")
    if info["width"] != width or info["height"] != height:
        problems.append(f"resolution {info['width']}x{info['height']} != {width}x{height}")
    if abs(info["duration"] - expected_duration) > max(1.2, expected_duration * 0.05):
        problems.append(f"duration {info['duration']:.2f}s != expected {expected_duration:.2f}s")
    if problems:
        raise RenderError("Export validation failed: " + "; ".join(problems))
    info["validated"] = True
    return info


def render(tl, cap_style, cap_items, src, out_path: Path, work: Path, asset_paths, keywords, encoder_pref="auto", ctx=None,
           progress=None) -> dict[str, Any]:
    work.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = work / ("render" + out_path.suffix)
    p = plan(tl, cap_style, cap_items, src, tmp_out, work, asset_paths, keywords, encoder_pref)

    try:
        _run_in(work, p["cmd"], p["duration"], progress, ctx)
    except media.MediaError as exc:
        if "nvenc" in p["encoder"]:
            log.warning("Hardware encode failed (%s); retrying with software encoder", exc)
            tmp_out.unlink(missing_ok=True)
            p = plan(tl, cap_style, cap_items, src, tmp_out, work, asset_paths, keywords, "off")
            _run_in(work, p["cmd"], p["duration"], progress, ctx)
        else:
            raise RenderError(str(exc)) from exc
    info = validate(tmp_out, p["duration"], p["width"], p["height"])
    final = out_path
    k = 1
    while final.exists():
        final = out_path.with_name(f"{out_path.stem} ({k}){out_path.suffix}")
        k += 1
    shutil.move(str(tmp_out), str(final))
    info.update({"path": str(final), "encoder": p["encoder"], "pieces": p["pieces"], "expected_duration": round(p["duration"], 3)})
    return info


def _run_in(cwd: Path, cmd: list[str], duration: float, progress, ctx) -> None:
    import os
    import subprocess
    import threading

    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore",
                            creationflags=media.CREATE_NO_WINDOW)
    if ctx is not None:
        ctx.register_process(proc)
    errs: list[str] = []

    def drain():
        for line in proc.stderr:  # type: ignore[union-attr]
            errs.append(line)

    th = threading.Thread(target=drain, daemon=True)
    th.start()
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if line.startswith("out_time_us="):
                try:
                    us = int(line.strip().split("=")[1])
                    if progress and duration > 0:
                        progress(min(0.99, us / 1e6 / duration))
                except ValueError:
                    pass
            if ctx is not None and ctx.cancelled:
                proc.kill()
                break
        proc.wait()
    finally:
        th.join(timeout=2)
        if ctx is not None:
            ctx.unregister_process(proc)
    if ctx is not None:
        ctx.check_cancel()
    if proc.returncode != 0:
        raise media.MediaError(f"FFmpeg render failed (exit {proc.returncode}): {''.join(errs[-12:])[-1500:]}")
