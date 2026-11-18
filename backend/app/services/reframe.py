"""Smart reframing: converts face / subject tracking data into smooth crop paths and layouts."""
from __future__ import annotations

from typing import Any

import numpy as np

ASPECTS = {"9:16": 9 / 16, "16:9": 16 / 9, "1:1": 1.0, "4:5": 4 / 5}
OUTPUT_SIZES = {
    "9:16": {"1080p": (1080, 1920), "720p": (720, 1280), "4k": (2160, 3840)},
    "16:9": {"1080p": (1920, 1080), "720p": (1280, 720), "4k": (3840, 2160)},
    "1:1": {"1080p": (1080, 1080), "720p": (720, 720), "4k": (2160, 2160)},
    "4:5": {"1080p": (1080, 1350), "720p": (720, 900), "4k": (2160, 2700)},
}


def crop_box(src_w: int, src_h: int, aspect: str, zoom: float = 1.0) -> tuple[float, float]:
    """Return normalized crop (width, height) relative to the source frame for the target aspect."""
    ar = ASPECTS.get(aspect, 9 / 16)
    src_ar = src_w / max(1, src_h)
    if src_ar >= ar:
        ch = 1.0
        cw = (src_h * ar) / src_w
    else:
        cw = 1.0
        ch = (src_w / ar) / src_h
    return cw / max(1.0, zoom), ch / max(1.0, zoom)


def _rdp(points: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    dmax, idx = 0.0, 0
    for k in range(1, len(points) - 1):
        x, y = points[k]
        if x1 == x0:
            d = abs(y - y0)
        else:
            yi = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
            d = abs(y - yi)
        if d > dmax:
            dmax, idx = d, k
    if dmax > eps:
        return _rdp(points[: idx + 1], eps)[:-1] + _rdp(points[idx:], eps)
    return [points[0], points[-1]]


def _speaker_at(t: float, sentences: list[dict[str, Any]]) -> int | None:
    lo, hi = 0, len(sentences) - 1
    while lo <= hi:
        m = (lo + hi) // 2
        s = sentences[m]
        if t < s["s"]:
            hi = m - 1
        elif t > s["e"]:
            lo = m + 1
        else:
            return int(s.get("speaker", 0))
    return None


def compute(samples: list[dict[str, Any]], scenes: list[dict[str, float]], sentences: list[dict[str, Any]],
            spk_pos: dict[int, dict[str, float]], src_w: int, src_h: int, aspect: str, start: float, end: float,
            mode: str = "auto", smoothness: float = 0.75, prefer_split: bool = False) -> dict[str, Any]:
    cw, ch = crop_box(src_w, src_h, aspect)
    hw, hh = cw / 2, ch / 2
    base = {"mode": mode, "aspect": aspect, "keyframes": [], "layouts": [], "offset": {"x": 0.0, "y": 0.0}}
    if mode == "center" or not samples or (cw >= 0.999 and ch >= 0.999):
        base["keyframes"] = [{"t": round(start, 3), "x": 0.5, "y": 0.5}]
        return base
    sel = [s for s in samples if start - 1.0 <= s["t"] <= end + 1.0]
    if not sel:
        base["keyframes"] = [{"t": round(start, 3), "x": 0.5, "y": 0.5}]
        return base
    ts = np.array([s["t"] for s in sel])
    tx = np.full(len(sel), np.nan)
    ty = np.full(len(sel), np.nan)
    two_wide = np.zeros(len(sel), dtype=bool)
    pairs: list[tuple[float, float, float, float] | None] = [None] * len(sel)
    last_choice = None
    for k, s in enumerate(sel):
        faces = sorted(s["faces"], key=lambda f: -f[2] * f[3])
        if not faces:
            if s.get("motion", 0) > 6:
                tx[k], ty[k] = s["subject"][0], s["subject"][1]
            continue
        if len(faces) >= 2 and faces[1][2] * faces[1][3] > 0.35 * faces[0][2] * faces[0][3]:
            a, b = faces[0], faces[1]
            left, right = (a, b) if a[0] < b[0] else (b, a)
            span = (right[0] + right[2] / 2) - (left[0] - left[2] / 2)
            if span <= cw * 0.95:
                tx[k], ty[k] = (left[0] + right[0]) / 2, (left[1] + right[1]) / 2
                continue
            two_wide[k] = True
            pairs[k] = (left[0], left[1], right[0], right[1])
            sp = _speaker_at(s["t"], sentences)
            choice = None
            if sp is not None and sp in spk_pos:
                px = spk_pos[sp]["cx"]
                choice = left if abs(left[0] - px) <= abs(right[0] - px) else right
            elif last_choice is not None:
                choice = left if abs(left[0] - last_choice) <= abs(right[0] - last_choice) else right
            else:
                choice = faces[0]
            tx[k], ty[k] = choice[0], choice[1]
            last_choice = choice[0]
        else:
            f = faces[0]
            tx[k], ty[k] = f[0], f[1] - f[3] * 0.15  # keep a little headroom
            last_choice = f[0]

    # fill gaps: hold previous valid, else next valid, else centre
    def fill(arr):
        out = arr.copy()
        valid = ~np.isnan(out)
        if not valid.any():
            return np.full_like(out, 0.5)
        idx = np.where(valid)[0]
        for k in range(len(out)):
            if np.isnan(out[k]):
                prev = idx[idx < k]
                out[k] = out[prev[-1]] if len(prev) else out[idx[0]]
        return out

    tx, ty = fill(tx), fill(ty)
    # per-scene smoothing with dead zone and velocity limit
    scene_starts = sorted({sc["s"] for sc in scenes if start - 1 < sc["s"] < end + 1})
    seg_id = np.searchsorted(np.array(scene_starts), ts, side="right") if scene_starts else np.zeros(len(ts), dtype=int)
    dz = 0.04 + 0.07 * smoothness
    vmax = 0.35 * (1.0 - 0.65 * smoothness)  # normalized width per second
    sigma_s = 0.4 + 1.6 * smoothness
    px = np.zeros_like(tx)
    py = np.zeros_like(ty)
    for sid in np.unique(seg_id):
        m = np.where(seg_id == sid)[0]
        cur_x, cur_y = tx[m[0]], ty[m[0]]
        for n_, k in enumerate(m):
            if abs(tx[k] - cur_x) > dz:
                cur_x = tx[k]
            if abs(ty[k] - cur_y) > dz * 1.5:
                cur_y = ty[k]
            px[k], py[k] = cur_x, cur_y
        # gaussian smoothing inside the scene
        if len(m) > 2:
            dt = np.median(np.diff(ts[m])) if len(m) > 1 else 0.5
            sig = max(1.0, sigma_s / max(0.05, dt))
            rad = int(3 * sig)
            kern = np.exp(-0.5 * (np.arange(-rad, rad + 1) / sig) ** 2)
            kern /= kern.sum()
            for arr in (px, py):
                seg = arr[m]
                padded = np.pad(seg, rad, mode="edge")
                arr[m] = np.convolve(padded, kern, mode="valid")[: len(m)]
        # velocity limit
        for k_prev, k in zip(m, m[1:]):
            dt = max(1e-3, ts[k] - ts[k_prev])
            lim = vmax * dt
            px[k] = px[k_prev] + np.clip(px[k] - px[k_prev], -lim, lim)
            py[k] = py[k_prev] + np.clip(py[k] - py[k_prev], -lim, lim)
    px = np.clip(px, hw, 1 - hw)
    py = np.clip(py, hh, 1 - hh)

    # keyframes with scene-cut aware simplification
    kfs: list[dict[str, float]] = []
    for sid in np.unique(seg_id):
        m = np.where(seg_id == sid)[0]
        pts_x = _rdp([(float(ts[k]), float(px[k])) for k in m], 0.006)
        ymap = {float(ts[k]): float(py[k]) for k in m}
        for t, x in pts_x:
            kfs.append({"t": round(t, 3), "x": round(x, 4), "y": round(ymap.get(t, 0.5), 4), "cut": False})
        if kfs and len(pts_x):
            kfs[-len(pts_x)]["cut"] = True  # first keyframe of a scene = hard cut, no interpolation from previous
    kfs.sort(key=lambda k: k["t"])
    base["keyframes"] = kfs or [{"t": round(start, 3), "x": 0.5, "y": 0.5}]

    # split-screen layouts for sustained two-person wide shots
    if mode == "split" or (mode == "auto" and prefer_split):
        runs = []
        k = 0
        while k < len(sel):
            if two_wide[k]:
                j = k
                while j + 1 < len(sel) and (two_wide[j + 1] or (j + 2 < len(sel) and two_wide[j + 2])):
                    j += 1
                if ts[j] - ts[k] >= 2.5:
                    pp = [p for p in pairs[k:j + 1] if p]
                    arr = np.array(pp)
                    runs.append({"s": round(max(start, float(ts[k])), 3), "e": round(min(end, float(ts[j]) + 0.5), 3), "layout": "split",
                                 "top": {"x": round(float(np.median(arr[:, 0])), 4), "y": round(float(np.median(arr[:, 1])), 4)},
                                 "bottom": {"x": round(float(np.median(arr[:, 2])), 4), "y": round(float(np.median(arr[:, 3])), 4)}})
                k = j + 1
            else:
                k += 1
        base["layouts"] = [r for r in runs if r["e"] - r["s"] >= 2.0]
    return base


def position_at(keyframes: list[dict[str, float]], t: float) -> tuple[float, float]:
    if not keyframes:
        return 0.5, 0.5
    if t <= keyframes[0]["t"]:
        return keyframes[0]["x"], keyframes[0]["y"]
    for a, b in zip(keyframes, keyframes[1:]):
        if a["t"] <= t <= b["t"]:
            if b.get("cut"):
                return (a["x"], a["y"]) if t < b["t"] else (b["x"], b["y"])
            r = (t - a["t"]) / max(1e-6, b["t"] - a["t"])
            return a["x"] + (b["x"] - a["x"]) * r, a["y"] + (b["y"] - a["y"]) * r
    return keyframes[-1]["x"], keyframes[-1]["y"]
