"""Automatic first-pass editor: builds a non-destructive, fully editable timeline for a discovered clip."""
from __future__ import annotations

from typing import Any

from . import captions, reframe, segmentation
from .models_util import short_id
from .presets import ZOOM_EVERY, preset_config


def build_zooms(segments: list[tuple[float, float]], sentences: list[dict[str, Any]], frequency: str, scale: float,
                start: float, end: float) -> list[dict[str, float]]:
    every = ZOOM_EVERY.get(frequency, 0)
    if not every or scale <= 1.001:
        return []
    # candidate switch points: cut points (jump cuts) and sentence starts
    points = sorted({round(s, 3) for s, _ in segments[1:]} | {round(x["s"], 3) for x in sentences if start + 1 < x["s"] < end - 1})
    zooms = []
    zoomed = False
    last = start
    zstart = None
    for p in points:
        if p - last >= every * (0.6 if zoomed else 1.0):
            if not zoomed:
                zstart = p
            else:
                zooms.append({"s": zstart, "e": p, "scale": round(scale, 3)})
            zoomed = not zoomed
            last = p
    if zoomed and zstart is not None and end - zstart > 1.0:
        zooms.append({"s": zstart, "e": round(end, 3), "scale": round(scale, 3)})
    return zooms


def build_sfx(sentences: list[dict[str, Any]], zooms: list[dict[str, float]], intensity: str, sfx_asset_id: str | None,
              start: float, end: float) -> list[dict[str, Any]]:
    if intensity == "none" or not sfx_asset_id:
        return []
    limit = {"low": 1, "medium": 3, "high": 5}.get(intensity, 1)
    points = [z["s"] for z in zooms]
    # also emphasise questions / concluding lines
    for s in sentences:
        if start + 2 < s["s"] < end - 2 and (s["text"].rstrip().endswith("?") or s["text"].rstrip().endswith("!")):
            points.append(s["s"])
    out: list[dict[str, Any]] = []
    for p in sorted(points):
        if all(abs(p - o["t"]) >= 8.0 for o in out):
            out.append({"id": short_id(), "asset_id": sfx_asset_id, "t": round(max(start, p - 0.15), 3), "volume": 0.35})
        if len(out) >= limit:
            break
    return out


def _natural_bounds(start: float, end: float, words: list[dict[str, Any]], vad: list[dict[str, float]] | None,
                    max_dur: float = 0.0) -> tuple[float, float]:
    """Pad clip start/end around real speech onsets and decays without bleeding into neighboring words."""
    prev_w = next((w for w in reversed(words) if float(w["e"]) <= start + 0.01 and float(w["s"]) < start - 0.02), None)
    next_w = next((w for w in words if float(w["s"]) >= end - 0.01 and float(w["e"]) > end + 0.02), None)
    first = next((w for w in words if float(w["s"]) >= start - 0.05), None)
    last = next((w for w in reversed(words) if float(w["e"]) <= end + 0.3), None)

    s_onset = float(first["s"]) if first else start
    e_decay = float(last["e"]) if last else end

    # If Silero VAD shows the current word's phonation started slightly earlier or finished slightly later,
    # include that breath/tail without crossing into neighboring words.
    if vad:
        for v in vad:
            vs, ve = float(v["s"]), float(v["e"])
            if vs <= s_onset <= ve and s_onset - vs <= 0.45:
                s_onset = vs
            if vs <= e_decay <= ve and ve - e_decay <= 0.9:
                e_decay = ve

    min_s = (float(prev_w["e"]) + 0.06) if prev_w else 0.0
    max_e = (float(next_w["s"]) - 0.06) if next_w else (max_dur if max_dur > 0 else e_decay + 0.35)
    new_s = max(0.0, max(min_s, s_onset - 0.20) if min_s <= s_onset else s_onset - 0.05)
    new_e = min(max_e, e_decay + 0.32) if max_e >= e_decay else e_decay + 0.10
    if max_dur > 0:
        new_e = min(max_dur, new_e)
    return round(new_s, 3), round(max(new_s + 1.0, new_e), 3)


def build_timeline(clip: dict[str, Any], words: list[dict[str, Any]], sentences: list[dict[str, Any]], vision: dict[str, Any] | None,
                   scenes: list[dict[str, float]], spk_pos: dict[int, Any], src_w: int, src_h: int, preset_id: str,
                   preset_cfg: dict[str, Any] | None, music_asset_id: str | None, sfx_asset_id: str | None,
                   aspect: str = "9:16", fps: float = 30.0, vad: list[dict[str, float]] | None = None,
                   laughter: list[dict[str, float]] | None = None, duration: float = 0.0) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    cfg = preset_config(preset_cfg)
    start, end = _natural_bounds(float(clip["start"]), float(clip["end"]), words, vad, duration)
    cuts = []
    cut_cfg = cfg["cuts"]
    if cut_cfg.get("remove_silence"):
        cuts = segmentation.silence_cuts(
            words, start, end, float(cut_cfg.get("min_silence", 1.0)), float(cut_cfg.get("keep_pad", 0.24)),
            vad=vad, protected=laughter,
        )
    segs = segmentation.keep_segments(start, end, cuts)
    in_clip = [s for s in sentences if s["s"] >= start - 0.1 and s["e"] <= end + 0.5]
    rf = cfg["reframe"]
    samples = (vision or {}).get("samples", [])
    rdata = reframe.compute(samples, scenes, sentences, spk_pos, src_w or 1920, src_h or 1080, aspect, start, end,
                            mode=rf.get("mode", "auto"), smoothness=float(rf.get("smoothness", 0.75)), prefer_split=bool(rf.get("prefer_split")))
    rdata["smoothness"] = float(rf.get("smoothness", 0.75))
    rdata["prefer_split"] = bool(rf.get("prefer_split"))
    zooms = build_zooms(segs, in_clip, cfg["zoom"].get("frequency", "none"), float(cfg["zoom"].get("scale", 1.1)), start, end)
    music = cfg["music"]
    timeline = {
        "version": 1,
        "preset_id": preset_id,
        "start": round(start, 3),
        "end": round(end, 3),
        "cuts": cuts,
        "cut_settings": dict(cut_cfg),
        "aspect": aspect,
        "reframe": rdata,
        "zooms": zooms,
        "music": {"asset_id": music_asset_id if music.get("enabled") else None, "recommended_id": music_asset_id,
                  "volume": float(music.get("volume", 0.1)), "fade_in": float(music.get("fade_in", 1.0)),
                  "fade_out": float(music.get("fade_out", 1.5)), "ducking": bool(music.get("ducking", True)), "offset": 0.0},
        "sfx": build_sfx(in_clip, zooms, cfg["sfx"].get("intensity", "low"), sfx_asset_id, start, end),
        "sfx_recommended_id": sfx_asset_id,
        "audio": {"enhance_voice": bool(cfg["audio"].get("enhance_voice", True)), "denoise": bool(cfg["audio"].get("denoise", False)),
                  "loudness": float(cfg["audio"].get("loudness", -14)), "voice_gain_db": 0.0},
        "export": {"resolution": "1080p", "fps": int(round(fps)) if round(fps) in (24, 25, 30, 50, 60) else 30, "codec": "h264",
                   "quality": "high", "bitrate_kbps": None, "audio_bitrate_kbps": 192},
    }
    style_id = cfg.get("caption_style", "podcast_pro")
    st = captions.style_for(style_id, cfg.get("caption_overrides"))
    cap_style = {"id": style_id, **{k: v for k, v in st.items() if k not in ("id",)}}
    items = captions.build_items(words, start, end, int(st.get("words_per_caption", 4)))
    if any(captions.hinglish.has_devanagari(it["text"]) for it in items) and cap_style.get("font") not in captions.DEVANAGARI_FONTS:
        cap_style["font"] = captions.default_devanagari_font()
        cap_style["bold"] = True
    return timeline, cap_style, items
