"""Local audio analysis: voice activity (Silero VAD), loudness, pitch, excitement, laughter, pauses."""
from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np

log = logging.getLogger("clipforge.audio")

HOP_S = 0.1  # 10 feature frames per second


def silero_vad(audio: np.ndarray, sr: int = 16000) -> list[dict[str, float]]:
    """Speech segments using the Silero VAD model bundled with faster-whisper (onnxruntime, local)."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        opts = VadOptions(min_silence_duration_ms=300, speech_pad_ms=120)
        chunks = get_speech_timestamps(audio, opts, sampling_rate=sr) if "sampling_rate" in get_speech_timestamps.__code__.co_varnames \
            else get_speech_timestamps(audio, opts)
        return [{"s": round(c["start"] / sr, 3), "e": round(c["end"] / sr, 3)} for c in chunks]
    except Exception as exc:  # noqa: BLE001
        log.warning("Silero VAD unavailable (%s); using energy-based VAD", exc)
        return energy_vad(audio, sr)


def energy_vad(audio: np.ndarray, sr: int = 16000, thresh_db: float = -40.0) -> list[dict[str, float]]:
    hop = int(sr * 0.03)
    n = len(audio) // hop
    if n == 0:
        return []
    frames = audio[: n * hop].reshape(n, hop)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    floor = np.percentile(db, 10)
    active = db > max(thresh_db, floor + 12)
    segs, start = [], None
    for i, a in enumerate(active):
        if a and start is None:
            start = i
        elif not a and start is not None:
            if i - start > 5:
                segs.append({"s": round(start * 0.03, 3), "e": round(i * 0.03, 3)})
            start = None
    if start is not None:
        segs.append({"s": round(start * 0.03, 3), "e": round(n * 0.03, 3)})
    return segs


def frame_features(audio: np.ndarray, sr: int, progress: Callable[[float], None] | None = None) -> dict[str, np.ndarray]:
    import librosa

    hop = int(sr * HOP_S)
    n_fft = 1024
    # Process in chunks to bound memory on long inputs
    chunk = sr * 300
    rms_l, cen_l, flat_l, zcr_l, f0_l = [], [], [], [], []
    total = len(audio)
    for off in range(0, max(1, total), chunk):
        seg = audio[off: off + chunk]
        if len(seg) < n_fft:
            seg = np.pad(seg, (0, n_fft - len(seg)))
        rms = librosa.feature.rms(y=seg, frame_length=n_fft, hop_length=hop, center=True)[0]
        S = np.abs(librosa.stft(seg, n_fft=n_fft, hop_length=hop, center=True))
        cen = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
        flat = librosa.feature.spectral_flatness(S=S)[0]
        zcr = librosa.feature.zero_crossing_rate(seg, frame_length=n_fft, hop_length=hop, center=True)[0]
        try:
            f0 = librosa.yin(seg, fmin=65, fmax=420, sr=sr, frame_length=2048, hop_length=hop, center=True)
        except Exception:  # noqa: BLE001
            f0 = np.zeros_like(rms)
        m = min(len(rms), len(cen), len(flat), len(zcr), len(f0))
        expected = int(np.ceil(min(chunk, total - off) / hop))
        m = min(m, max(1, expected))
        rms_l.append(rms[:m]); cen_l.append(cen[:m]); flat_l.append(flat[:m]); zcr_l.append(zcr[:m]); f0_l.append(f0[:m])
        if progress:
            progress(min(1.0, (off + chunk) / max(1, total)))
    rms = np.concatenate(rms_l)
    db = 20 * np.log10(rms + 1e-6)
    return {
        "t": np.arange(len(rms)) * HOP_S,
        "db": db.astype(np.float32),
        "centroid": np.concatenate(cen_l).astype(np.float32),
        "flatness": np.concatenate(flat_l).astype(np.float32),
        "zcr": np.concatenate(zcr_l).astype(np.float32),
        "f0": np.concatenate(f0_l).astype(np.float32),
    }


def _mask_from_segments(segments: list[dict[str, float]], n: int) -> np.ndarray:
    m = np.zeros(n, dtype=bool)
    for s in segments:
        a, b = int(s["s"] / HOP_S), int(np.ceil(s["e"] / HOP_S))
        m[max(0, a):min(n, b)] = True
    return m


def detect_laughter(feats: dict[str, np.ndarray], word_mask: np.ndarray, vad_mask: np.ndarray) -> list[dict[str, float]]:
    """Heuristic laughter detector: voiced-energy bursts that the ASR did not transcribe as words,
    with high spectral flatness / zero-crossing and rhythmic energy modulation. Marked as *possible* laughter."""
    db = feats["db"]
    n = len(db)
    if n < 20:
        return []
    loud = db > (np.percentile(db, 50) + 3)
    noisy = (feats["flatness"] > np.percentile(feats["flatness"], 70)) | (feats["zcr"] > np.percentile(feats["zcr"], 70))
    cand = loud & noisy & vad_mask[:n] & ~word_mask[:n]
    out = []
    i = 0
    while i < n:
        if cand[i]:
            j = i
            while j < n and (cand[j] or (j + 1 < n and cand[j + 1])):
                j += 1
            dur = (j - i) * HOP_S
            if 0.5 <= dur <= 8.0:
                seg = db[i:j]
                mod = float(np.std(np.diff(seg))) if len(seg) > 3 else 0.0
                if mod > 1.5:
                    out.append({"s": round(i * HOP_S, 2), "e": round(j * HOP_S, 2), "confidence": round(min(1.0, mod / 6), 2)})
            i = j + 1
        else:
            i += 1
    return out


def analyze(audio: np.ndarray, sr: int, words: list[dict[str, Any]], progress: Callable[[float, str], None] | None = None) -> dict[str, Any]:
    if progress:
        progress(0.02, "Voice activity detection (Silero VAD)")
    vad = silero_vad(audio, sr)
    if progress:
        progress(0.2, "Loudness / pitch / spectral features")
    feats = frame_features(audio, sr, (lambda p: progress(0.2 + 0.6 * p, "Audio features")) if progress else None)
    n = len(feats["db"])
    vad_mask = _mask_from_segments(vad, n)
    word_mask = _mask_from_segments([{"s": w["s"], "e": w["e"]} for w in words], n)
    if progress:
        progress(0.85, "Laughter / excitement detection")
    laughter = detect_laughter(feats, word_mask, vad_mask)

    speech_db = feats["db"][vad_mask] if vad_mask.any() else feats["db"]
    mu, sd = float(np.mean(speech_db)), float(np.std(speech_db) + 1e-6)
    energy_z = (feats["db"] - mu) / sd
    f0 = feats["f0"].copy()
    voiced = vad_mask & (f0 > 70) & (f0 < 400)
    f0_mu = float(np.median(f0[voiced])) if voiced.any() else 150.0
    # excitement: loud + pitch raised, smoothed over 2s
    pitch_rel = np.where(voiced, (f0 - f0_mu) / max(20.0, f0_mu * 0.25), 0.0)
    exc = np.clip(0.6 * energy_z + 0.4 * pitch_rel, -3, 3)
    k = int(2.0 / HOP_S)
    exc_s = np.convolve(exc, np.ones(k) / k, mode="same")
    excitement = []
    thr = np.percentile(exc_s, 95) if n > 50 else 99
    i = 0
    while i < n:
        if exc_s[i] >= thr and vad_mask[i]:
            j = i
            while j < n and exc_s[j] >= thr:
                j += 1
            if (j - i) * HOP_S >= 1.0:
                excitement.append({"s": round(i * HOP_S, 2), "e": round(j * HOP_S, 2), "level": round(float(exc_s[i:j].mean()), 2)})
            i = j
        i += 1
    long_pauses = [p for p in _pauses(words) if p["d"] >= 1.5]
    clip_ratio = float((np.abs(audio) > 0.98).mean()) if len(audio) else 0.0
    return {
        "vad": vad,
        "speech_ratio": round(float(vad_mask.mean()) if n else 0.0, 3),
        "laughter": laughter,
        "excitement": excitement,
        "long_pauses": long_pauses,
        "loudness_db_mean": round(mu, 2),
        "pitch_median_hz": round(f0_mu, 1),
        "clipping_ratio": round(clip_ratio, 5),
        "_frames": {
            "energy_z": energy_z.astype(np.float32),
            "pitch_rel": pitch_rel.astype(np.float32),
            "excitement": exc_s.astype(np.float32),
            "db": feats["db"],
        },
    }


def _pauses(words):
    out = []
    for a, b in zip(words, words[1:]):
        g = b["s"] - a["e"]
        if g > 0.5:
            out.append({"s": round(a["e"], 2), "e": round(b["s"], 2), "d": round(g, 2)})
    return out


def window_stats(frames: dict[str, np.ndarray], s: float, e: float) -> dict[str, float]:
    a, b = int(s / HOP_S), max(int(s / HOP_S) + 1, int(e / HOP_S))
    ez = frames["energy_z"][a:b]
    pr = frames["pitch_rel"][a:b]
    ex = frames["excitement"][a:b]
    if len(ez) == 0:
        return {"energy": 0.0, "energy_var": 0.0, "pitch_var": 0.0, "excitement": 0.0, "excitement_max": 0.0}
    return {
        "energy": float(ez.mean()),
        "energy_var": float(ez.std()),
        "pitch_var": float(pr.std()),
        "excitement": float(ex.mean()),
        "excitement_max": float(ex.max()),
    }
