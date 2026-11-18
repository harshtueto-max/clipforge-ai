"""Procedural generator for ClipForge's built-in royalty-free audio library.

All music beds and sound effects are synthesized from scratch with NumPy, so they are original works
released by this project under CC0 - no third-party samples are used.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

SR = 44100
RNG = np.random.default_rng(1234)

NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def midi_hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def env_adsr(n: int, a=0.01, d=0.1, s=0.7, r=0.2) -> np.ndarray:
    a_n, d_n, r_n = int(a * SR), int(d * SR), int(r * SR)
    s_n = max(0, n - a_n - d_n - r_n)
    e = np.concatenate([np.linspace(0, 1, max(1, a_n)), np.linspace(1, s, max(1, d_n)), np.full(s_n, s), np.linspace(s, 0, max(1, r_n))])
    return e[:n] if len(e) >= n else np.pad(e, (0, n - len(e)))


def lowpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    from scipy.signal import butter, sosfilt

    sos = butter(2, min(0.99, cutoff / (SR / 2)), btype="low", output="sos")
    return sosfilt(sos, x)


def highpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    from scipy.signal import butter, sosfilt

    sos = butter(2, min(0.99, cutoff / (SR / 2)), btype="high", output="sos")
    return sosfilt(sos, x)


def bandpass(x, lo, hi):
    from scipy.signal import butter, sosfilt

    sos = butter(2, [lo / (SR / 2), min(0.99, hi / (SR / 2))], btype="band", output="sos")
    return sosfilt(sos, x)


def reverb(x: np.ndarray, seconds=1.6, mix=0.25) -> np.ndarray:
    from scipy.signal import fftconvolve

    n = int(seconds * SR)
    ir = RNG.standard_normal(n) * np.exp(-np.linspace(0, 7, n))
    ir = lowpass(ir, 6000)
    ir /= np.sqrt((ir ** 2).sum())
    wet = fftconvolve(x, ir)[: len(x)]
    return (1 - mix) * x + mix * wet * 0.6


# --------------------------------------------------------------- instruments
def saw(f, t):
    return 2 * ((f * t) % 1.0) - 1


def tone_pad(freqs, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for f in freqs:
        for det in (-0.12, 0.0, 0.11):
            out += saw(f * 2 ** (det / 12), t) * 0.3
    out = lowpass(out, 1400)
    return out * env_adsr(n, a=min(0.8, dur * 0.3), d=0.3, s=0.85, r=min(1.0, dur * 0.3)) / max(1, len(freqs))


def keys(f, dur, bright=1.0):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = np.zeros(n)
    for k, amp in enumerate([1.0, 0.45, 0.25, 0.12, 0.06]):
        out += amp * np.sin(2 * np.pi * f * (k + 1) * t) * np.exp(-t * (2.2 + k * 1.5 / bright))
    return out * env_adsr(n, a=0.004, d=0.05, s=1.0, r=0.08) * 0.5


def pluck(f, dur):
    n = int(dur * SR)
    period = max(2, int(SR / f))
    buf = RNG.uniform(-1, 1, period)
    out = np.zeros(n)
    for k in range(n):
        out[k] = buf[k % period]
        buf[k % period] = 0.497 * (buf[k % period] + buf[(k + 1) % period])
    return out * 0.6


def fast_pluck(f, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    out = (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) + 0.15 * saw(f, t)) * np.exp(-t * 9)
    return out * 0.5


def bass(f, dur, kind="sine"):
    n = int(dur * SR)
    t = np.arange(n) / SR
    w = np.sin(2 * np.pi * f * t) if kind == "sine" else lowpass(saw(f, t), 600)
    return w * env_adsr(n, a=0.005, d=0.1, s=0.8, r=0.05) * 0.6


def kick(dur=0.35):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = 50 + 110 * np.exp(-t * 30)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t * 9) * 0.9


def snare(dur=0.25):
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = highpass(RNG.standard_normal(n), 1500) * np.exp(-t * 18)
    body = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 25)
    return (noise * 0.5 + body * 0.4) * 0.7


def hat(dur=0.06, open_=False):
    n = int((0.25 if open_ else dur) * SR)
    t = np.arange(n) / SR
    return highpass(RNG.standard_normal(n), 7000) * np.exp(-t * (12 if open_ else 60)) * 0.25


def place(buf, sig, at, gain=1.0):
    a = int(at * SR)
    if a >= len(buf):
        return
    b = min(len(buf), a + len(sig))
    buf[a:b] += sig[: b - a] * gain


# --------------------------------------------------------------- music
MOODS = {
    "cinematic": dict(bpm=70, root="D", minor=True, prog=[0, 8, 3, 10], drums="boom", lead="pad", bars=12),
    "motivational": dict(bpm=118, root="C", minor=False, prog=[0, 7, 9, 5], drums="four", lead="pluck8", bars=16),
    "emotional": dict(bpm=72, root="A", minor=True, prog=[0, 5, 3, 7], drums=None, lead="arp_keys", bars=12),
    "corporate": dict(bpm=108, root="G", minor=False, prog=[0, 9, 5, 7], drums="light", lead="pluck8", bars=16),
    "podcast": dict(bpm=88, root="F", minor=False, prog=[0, 9, 2, 7], drums="light", lead="keys7", bars=14),
    "documentary": dict(bpm=78, root="E", minor=True, prog=[0, 8, 5, 3], drums=None, lead="slow_keys", bars=12),
    "suspense": dict(bpm=86, root="C#", minor=True, prog=[0, 0, 1, 0], drums="tick", lead="pulse", bars=12),
    "comedy": dict(bpm=126, root="F", minor=False, prog=[0, 5, 7, 0], drums="bouncy", lead="staccato", bars=16),
    "lofi": dict(bpm=80, root="D#", minor=False, prog=[2, 7, 0, 9], drums="swing", lead="keys7", bars=14),
    "energetic": dict(bpm=138, root="E", minor=True, prog=[0, 8, 3, 10], drums="four_hard", lead="arp16", bars=20),
}


def chord(root_midi: int, degree_semitones: int, minor_key: bool, seventh=False) -> list[int]:
    major_scale = [0, 2, 4, 5, 7, 9, 11]
    minor_scale = [0, 2, 3, 5, 7, 8, 10]
    scale = minor_scale if minor_key else major_scale
    # find scale degree nearest to semitone offset
    base = degree_semitones % 12
    if base not in scale:
        scale_idx = min(range(7), key=lambda k: abs(scale[k] - base))
    else:
        scale_idx = scale.index(base)
    notes = []
    for step in (0, 2, 4) + ((6,) if seventh else ()):
        k = scale_idx + step
        notes.append(root_midi + scale[k % 7] + 12 * (k // 7))
    return notes


def render_music(mood: str) -> np.ndarray:
    p = MOODS[mood]
    beat = 60.0 / p["bpm"]
    bar = beat * 4
    bars = p["bars"]
    total = bars * bar + 1.5
    L = np.zeros(int(total * SR))
    R = np.zeros(int(total * SR))
    root = 48 + NOTE[p["root"]]
    for b_ in range(bars):
        t0 = b_ * bar
        deg = p["prog"][b_ % len(p["prog"])]
        notes = chord(root, deg, p["minor"], seventh=p["lead"] in ("keys7",))
        freqs = [midi_hz(m + 12) for m in notes]
        # pad bed (all moods, quieter for busy ones)
        pad = tone_pad(freqs, bar + 0.3)
        g = 0.35 if p["lead"] in ("pad", "slow_keys", "pulse") else 0.18
        place(L, pad, t0, g); place(R, pad, t0, g * 0.9)
        # bass
        if mood not in ("emotional",):
            bkind = "saw" if mood in ("energetic", "suspense") else "sine"
            if p["lead"] == "pulse":
                for k in range(16):
                    place(L, bass(midi_hz(notes[0] - 12), beat / 4 * 0.9, bkind), t0 + k * beat / 4, 0.35)
            elif mood == "comedy":
                for k in range(4):
                    m = notes[0] - 12 if k % 2 == 0 else notes[2] - 12
                    place(L, bass(midi_hz(m), beat * 0.4), t0 + k * beat, 0.5)
            else:
                for k in range(2 if p["bpm"] < 100 else 4):
                    step = bar / (2 if p["bpm"] < 100 else 4)
                    place(L, bass(midi_hz(notes[0] - 12), step * 0.95, bkind), t0 + k * step, 0.45)
            R[:] = R  # bass mono-ish; mixed to centre below
        # lead
        lead = p["lead"]
        if lead == "pluck8":
            for k in range(8):
                m = notes[[0, 1, 2, 1][k % 4]] + 24
                s = fast_pluck(midi_hz(m), beat / 2)
                place(L if k % 2 else R, s, t0 + k * beat / 2, 0.28)
        elif lead == "arp16":
            for k in range(16):
                m = notes[k % 3] + 24 + (12 if k % 8 == 7 else 0)
                place(L if k % 2 else R, fast_pluck(midi_hz(m), beat / 4), t0 + k * beat / 4, 0.22)
        elif lead == "arp_keys":
            for k in range(8):
                m = notes[[0, 1, 2, 1, 0, 2, 1, 2][k]] + 24
                s = keys(midi_hz(m), beat * 1.5)
                place(L, s, t0 + k * beat / 2, 0.35); place(R, s, t0 + k * beat / 2 + 0.01, 0.3)
        elif lead == "keys7":
            for k, off in enumerate((0.0, 1.5, 2.5)):
                for m in notes:
                    s = keys(midi_hz(m + 12), beat * 1.2, bright=0.7)
                    place(L, s, t0 + off * beat, 0.16); place(R, s, t0 + off * beat + 0.012, 0.15)
        elif lead == "slow_keys":
            for k in range(2):
                s = keys(midi_hz(notes[(b_ + k) % 3] + 24), bar)
                place(L, s, t0 + k * bar / 2, 0.3); place(R, s, t0 + k * bar / 2 + 0.02, 0.25)
        elif lead == "staccato":
            for k in range(8):
                if k in (1, 3, 4, 6):
                    m = notes[(k + b_) % 3] + 24
                    s = fast_pluck(midi_hz(m), beat * 0.25)
                    place(L, s, t0 + k * beat / 2, 0.35); place(R, s, t0 + k * beat / 2, 0.3)
        elif lead == "pulse":
            if b_ % 2 == 0:
                s = keys(midi_hz(notes[0] + 36), bar, bright=0.4)
                place(L, s, t0 + beat * 2, 0.12); place(R, s, t0 + beat * 2.02, 0.12)
        # drums
        d = p["drums"]
        if d == "boom" and b_ % 2 == 0:
            boom = reverb(kick(1.2) * 1.2, 1.5, 0.4)
            place(L, boom, t0, 0.5); place(R, boom, t0, 0.5)
        elif d in ("four", "four_hard"):
            for k in range(4):
                place(L, kick(), t0 + k * beat, 0.55); place(R, kick(), t0 + k * beat, 0.55)
                place(L, hat(), t0 + k * beat + beat / 2, 0.6); place(R, hat(), t0 + k * beat + beat / 2, 0.6)
                if k in (1, 3):
                    place(L, snare(), t0 + k * beat, 0.4 if d == "four" else 0.55); place(R, snare(), t0 + k * beat, 0.4)
        elif d == "light":
            for k in range(4):
                if k in (0, 2):
                    place(L, kick(), t0 + k * beat, 0.35); place(R, kick(), t0 + k * beat, 0.35)
                for h in (0, 0.5):
                    place(L if h else R, hat(), t0 + (k + h) * beat, 0.35)
                if k in (1, 3):
                    place(L, snare() * 0.6, t0 + k * beat, 0.25); place(R, snare() * 0.6, t0 + k * beat, 0.25)
        elif d == "swing":
            for k in range(4):
                if k in (0, 2):
                    place(L, kick(), t0 + k * beat, 0.4); place(R, kick(), t0 + k * beat, 0.4)
                if k in (1, 3):
                    sn = lowpass(snare(), 3500)
                    place(L, sn, t0 + k * beat, 0.3); place(R, sn, t0 + k * beat, 0.3)
                for h, sw in ((0, 0), (1, 0.66)):
                    place(L if h else R, lowpass(hat(), 9000), t0 + (k + sw) * beat, 0.3)
        elif d == "tick":
            for k in range(8):
                place(R, hat(0.03), t0 + k * beat / 2, 0.4)
            place(L, kick(0.6), t0, 0.4); place(R, kick(0.6), t0, 0.4)
        elif d == "bouncy":
            for k in range(4):
                place(L, kick(0.2), t0 + k * beat, 0.4); place(R, kick(0.2), t0 + k * beat, 0.4)
                place(L, hat(), t0 + k * beat + beat / 2, 0.4)
    mix = np.stack([L, R], axis=1)
    if mood == "lofi":
        crackle = (RNG.random(len(L)) > 0.9993) * RNG.uniform(-0.3, 0.3, len(L))
        hiss = lowpass(RNG.standard_normal(len(L)) * 0.004, 5000)
        mix = np.stack([lowpass(L, 3200) + crackle + hiss, lowpass(R, 3200) + crackle + hiss], axis=1)
    mix[:, 0] = reverb(mix[:, 0], 1.4, 0.18)
    mix[:, 1] = reverb(mix[:, 1], 1.5, 0.18)
    # loop-friendly edges
    fade = int(0.02 * SR)
    mix[:fade] *= np.linspace(0, 1, fade)[:, None]
    mix[-int(1.2 * SR):] *= np.linspace(1, 0, int(1.2 * SR))[:, None]
    return normalize(mix, 0.7)


def normalize(x, peak=0.8):
    m = np.abs(x).max() or 1.0
    return x / m * peak


# --------------------------------------------------------------- SFX
def sfx_whoosh(up=True, dur=0.9):
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = RNG.standard_normal(n)
    out = np.zeros(n)
    chunks = 40
    for c in range(chunks):
        a, b = c * n // chunks, (c + 1) * n // chunks
        frac = c / chunks if up else 1 - c / chunks
        lo = 300 + 3000 * frac
        out[a:b] = bandpass(noise[max(0, a - 2000):b], lo, lo * 2.2)[-(b - a):]
    envl = np.sin(np.pi * t / dur) ** 2
    return stereo_pan(out * envl, sweep=True)


def sfx_impact(deep=True):
    dur = 1.6
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = (40 if deep else 70) + 120 * np.exp(-t * 12)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3.5)
    crack = highpass(RNG.standard_normal(n), 800) * np.exp(-t * 30) * 0.5
    sig = reverb(body + crack, 1.8, 0.35)
    return stereo_pan(sig)


def sfx_pop(high=False):
    dur = 0.18
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = (900 if high else 600) * np.exp(-t * 18) + 200
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 35)
    return stereo_pan(s)


def sfx_riser(dur=2.5, tonal=True):
    n = int(dur * SR)
    t = np.arange(n) / SR
    noise = RNG.standard_normal(n)
    out = np.zeros(n)
    chunks = 50
    for c in range(chunks):
        a, b = c * n // chunks, (c + 1) * n // chunks
        lo = 200 + 5000 * (c / chunks) ** 2
        out[a:b] = bandpass(noise[max(0, a - 2000):b], lo, lo * 1.8)[-(b - a):]
    out *= (t / dur) ** 2
    if tonal:
        f = 110 * 2 ** (3 * t / dur)
        out += 0.4 * np.sin(2 * np.pi * np.cumsum(f) / SR) * (t / dur) ** 1.5
    return stereo_pan(out)


def sfx_transition(kind=0):
    if kind == 0:  # reverse swell
        s = sfx_riser(1.2, tonal=False)
        s[-int(0.03 * SR):] *= np.linspace(1, 0, int(0.03 * SR))[:, None]
        return s
    w = sfx_whoosh(True, 0.6)
    tail = sfx_pop(True)
    out = np.zeros((len(w) + len(tail), 2))
    out[: len(w)] += w
    out[len(w) - 2000: len(w) - 2000 + len(tail)] += tail * 0.6
    return out


def sfx_cinematic_hit(metal=False):
    dur = 3.0
    n = int(dur * SR)
    t = np.arange(n) / SR
    boom = np.sin(2 * np.pi * np.cumsum(35 + 80 * np.exp(-t * 8)) / SR) * np.exp(-t * 1.8)
    if metal:
        for fr, amp in ((523, 0.25), (1187, 0.18), (1764, 0.12), (2933, 0.08)):
            boom += amp * np.sin(2 * np.pi * fr * t) * np.exp(-t * 2.5)
    boom += highpass(RNG.standard_normal(n), 2000) * np.exp(-t * 20) * 0.3
    return stereo_pan(reverb(boom, 2.5, 0.45))


def sfx_notification(variant=0):
    notes = [(880, 0.0), (1318.5, 0.12)] if variant == 0 else [(1046.5, 0.0), (1568, 0.09), (2093, 0.18)]
    dur = 0.8
    out = np.zeros(int(dur * SR))
    for f, at in notes:
        place(out, keys(f, 0.6, bright=2.0), at, 0.6)
    return stereo_pan(reverb(out, 0.8, 0.2))


def sfx_comedy(variant=0):
    if variant == 0:  # boing
        dur = 0.8
        t = np.arange(int(dur * SR)) / SR
        f = 220 + 160 * np.sin(2 * np.pi * 9 * t) * np.exp(-t * 3) + 80 * t
        s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3)
    else:  # slide whistle
        dur = 1.0
        t = np.arange(int(dur * SR)) / SR
        f = 500 + 900 * (t / dur) + 15 * np.sin(2 * np.pi * 6 * t)
        s = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_adsr(len(t), 0.05, 0.1, 0.8, 0.2)
    return stereo_pan(s)


def stereo_pan(mono, sweep=False):
    n = len(mono)
    if sweep:
        p = np.linspace(-0.6, 0.6, n)
    else:
        p = np.zeros(n)
    l = mono * np.sqrt((1 - p) / 2) * 1.414
    r = mono * np.sqrt((1 + p) / 2) * 1.414
    return normalize(np.stack([l, r], axis=1), 0.85)


SFX = {
    "whoosh": [("Whoosh Up", lambda: sfx_whoosh(True)), ("Whoosh Down", lambda: sfx_whoosh(False, 0.7))],
    "impact": [("Deep Impact", lambda: sfx_impact(True)), ("Punch Impact", lambda: sfx_impact(False))],
    "pop": [("Soft Pop", lambda: sfx_pop(False)), ("Bright Pop", lambda: sfx_pop(True))],
    "riser": [("Tension Riser", lambda: sfx_riser(2.5, True)), ("Noise Riser", lambda: sfx_riser(1.8, False))],
    "transition": [("Reverse Swell", lambda: sfx_transition(0)), ("Swoosh Pop", lambda: sfx_transition(1))],
    "cinematic_hit": [("Cinematic Boom", lambda: sfx_cinematic_hit(False)), ("Metallic Hit", lambda: sfx_cinematic_hit(True))],
    "notification": [("Ding", lambda: sfx_notification(0)), ("Chime Up", lambda: sfx_notification(1))],
    "comedy": [("Boing", lambda: sfx_comedy(0)), ("Slide Whistle", lambda: sfx_comedy(1))],
}


def _write(path_m4a: Path, data: np.ndarray, ffmpeg: str) -> None:
    import soundfile as sf

    wav = path_m4a.with_suffix(".tmp.wav")
    sf.write(str(wav), data.astype(np.float32), SR, subtype="PCM_16")
    subprocess.run([ffmpeg, "-y", "-v", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "192k", str(path_m4a)], check=True,
                   creationflags=0x08000000 if hasattr(subprocess, "STARTUPINFO") else 0)
    wav.unlink(missing_ok=True)


def generate(out_dir: Path, ffmpeg: str, force: bool = False) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    if manifest_path.exists() and not force:
        return json.loads(manifest_path.read_text())
    items = []
    (out_dir / "music").mkdir(exist_ok=True)
    (out_dir / "sfx").mkdir(exist_ok=True)
    for mood in MOODS:
        data = render_music(mood)
        p = out_dir / "music" / f"{mood}.m4a"
        _write(p, data, ffmpeg)
        items.append({"kind": "music", "category": mood, "name": f"{mood.title()} Bed", "file": f"music/{mood}.m4a",
                      "duration": round(len(data) / SR, 2), "bpm": MOODS[mood]["bpm"], "moods": [mood]})
    for cat, variants in SFX.items():
        for k, (name, fn) in enumerate(variants):
            data = fn()
            p = out_dir / "sfx" / f"{cat}_{k + 1}.m4a"
            _write(p, data, ffmpeg)
            items.append({"kind": "sfx", "category": cat, "name": name, "file": f"sfx/{cat}_{k + 1}.m4a",
                          "duration": round(len(data) / SR, 2), "bpm": None, "moods": [cat]})
    manifest = {"version": 1, "license": "CC0 1.0 - original procedurally generated audio by ClipForge AI", "items": items}
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":  # pragma: no cover
    import shutil
    import sys

    root = Path(__file__).resolve().parents[3] / "assets" / "audio"
    ff = shutil.which("ffmpeg")
    if not ff:
        sys.exit("ffmpeg not found")
    m = generate(root, ff, force="--force" in sys.argv)
    print(f"Generated {len(m['items'])} audio assets in {root}")
