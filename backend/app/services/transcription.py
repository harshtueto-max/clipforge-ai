"""Local speech recognition with Faster-Whisper (CTranslate2).

The engine is behind a small interface so it can be swapped for another local ASR backend later.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from .. import config
from . import segmentation

log = logging.getLogger("clipforge.asr")

WHISPER_MODELS: dict[str, dict[str, Any]] = {
    "tiny": {"repo": "Systran/faster-whisper-tiny", "size_mb": 75, "ram_gb": 1.0, "vram_gb": 1.0, "speed": "~10-20x realtime on CPU", "quality": "basic"},
    "base": {"repo": "Systran/faster-whisper-base", "size_mb": 145, "ram_gb": 1.5, "vram_gb": 1.0, "speed": "~6-12x realtime on CPU", "quality": "good"},
    "small": {"repo": "Systran/faster-whisper-small", "size_mb": 484, "ram_gb": 2.5, "vram_gb": 2.0, "speed": "~2-4x realtime on CPU", "quality": "very good"},
    "medium": {"repo": "Systran/faster-whisper-medium", "size_mb": 1530, "ram_gb": 5.0, "vram_gb": 3.5, "speed": "~1x realtime on CPU, fast on GPU", "quality": "excellent"},
    "large-v3": {"repo": "Systran/faster-whisper-large-v3", "size_mb": 3100, "ram_gb": 8.0, "vram_gb": 5.0, "speed": "slow on CPU; GPU recommended", "quality": "best"},
    "large-v3-turbo": {"repo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "size_mb": 1620, "ram_gb": 6.0, "vram_gb": 3.5, "speed": "GPU recommended", "quality": "near-best, faster"},
}

_dll_dirs_added = False


def add_cuda_dll_dirs() -> list[str]:
    """Make pip-installed NVIDIA runtime DLLs (nvidia-cublas-cu12 / nvidia-cudnn-cu12) discoverable."""
    global _dll_dirs_added
    added: list[str] = []
    if sys.platform != "win32" or _dll_dirs_added:
        return added
    _dll_dirs_added = True
    for base in sys.path:
        nv = Path(base) / "nvidia"
        if nv.is_dir():
            for sub in nv.iterdir():
                b = sub / "bin"
                if b.is_dir():
                    try:
                        os.add_dll_directory(str(b))
                        os.environ["PATH"] = str(b) + os.pathsep + os.environ.get("PATH", "")
                        added.append(str(b))
                    except OSError:
                        pass
    return added


def model_dir(name: str) -> Path:
    return config.WHISPER_DIR / name


def is_installed(name: str) -> bool:
    d = model_dir(name)
    return (d / "model.bin").exists() and (d / "config.json").exists()


_status_cache: dict[str, Any] = {}


def engine_status() -> dict[str, Any]:
    """Report whether the ASR runtime can be loaded on this machine (cached after first probe)."""
    if "engine" in _status_cache:
        return dict(_status_cache["engine"])
    try:
        add_cuda_dll_dirs()
        import ctranslate2  # noqa: F401

        cuda = ctranslate2.get_cuda_device_count()
        res = {"available": True, "engine": f"faster-whisper / ctranslate2 {ctranslate2.__version__}", "cuda_devices": cuda, "error": None}
    except Exception as exc:  # noqa: BLE001
        res = {"available": False, "engine": "faster-whisper", "cuda_devices": 0, "error": f"{type(exc).__name__}: {exc}"}
    _status_cache["engine"] = res
    return dict(res)


def cuda_usable() -> tuple[bool, str]:
    """Check that CUDA inference really works (driver + cuBLAS + cuDNN present). Cached."""
    if "cuda" in _status_cache:
        return _status_cache["cuda"]
    res = _cuda_usable()
    _status_cache["cuda"] = res
    return res


def _cuda_usable() -> tuple[bool, str]:
    add_cuda_dll_dirs()
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() < 1:
            return False, "No CUDA device detected"
        types = ctranslate2.get_supported_compute_types("cuda")
        import ctypes

        try:
            ctypes.WinDLL("cublas64_12.dll") if sys.platform == "win32" else None
        except OSError:
            return False, "CUDA device found but cuBLAS 12 runtime is missing (run setup.bat and choose GPU support)"
        return True, f"CUDA ok ({', '.join(sorted(types))})"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def download_model(name: str, progress: Callable[[float, str], None] | None = None, ctx=None) -> Path:
    if name not in WHISPER_MODELS:
        raise ValueError(f"Unknown model {name}")
    if config.get_settings().get("offline_mode"):
        raise RuntimeError("Offline mode is enabled - disable it in Settings to download models")
    from huggingface_hub import snapshot_download

    target = model_dir(name)
    target.mkdir(parents=True, exist_ok=True)
    expected = WHISPER_MODELS[name]["size_mb"] * 1024 * 1024
    stop = threading.Event()

    def _watch():
        while not stop.wait(1.0):
            size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
            if progress:
                try:
                    progress(min(0.99, size / expected), f"{size / 1e6:.0f} / {expected / 1e6:.0f} MB")
                except Exception:  # noqa: BLE001
                    stop.set()

    w = threading.Thread(target=_watch, daemon=True)
    w.start()
    try:
        snapshot_download(
            repo_id=WHISPER_MODELS[name]["repo"],
            local_dir=str(target),
            allow_patterns=["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"],
        )
    finally:
        stop.set()
        w.join(timeout=2)
    if not is_installed(name):
        raise RuntimeError("Model download incomplete")
    return target


_model_cache: dict[tuple, Any] = {}
_model_lock = threading.Lock()


def resolve_device(pref: str) -> tuple[str, str]:
    if pref == "cpu":
        return "cpu", "int8"
    ok, _ = cuda_usable()
    if ok:
        return "cuda", "int8_float16"
    if pref == "cuda":
        raise RuntimeError("CUDA was requested but is not usable on this machine; select CPU or Auto in Settings")
    return "cpu", "int8"


def load_model(name: str, device_pref: str = "auto", compute_type: str = "auto"):
    if not is_installed(name):
        raise RuntimeError(f"Whisper model '{name}' is not installed. Open Settings > Models to download it "
                           f"({WHISPER_MODELS.get(name, {}).get('size_mb', '?')} MB).")
    add_cuda_dll_dirs()
    from faster_whisper import WhisperModel

    device, ctype = resolve_device(device_pref)
    if compute_type != "auto":
        ctype = compute_type
    key = (name, device, ctype)
    with _model_lock:
        if key in _model_cache:
            return _model_cache[key], device, ctype
        _model_cache.clear()
        threads = max(1, (os.cpu_count() or 4) - 1)
        try:
            m = WhisperModel(str(model_dir(name)), device=device, compute_type=ctype, cpu_threads=threads)
        except Exception as exc:  # noqa: BLE001
            if device == "cuda":
                log.warning("CUDA load failed (%s), falling back to CPU", exc)
                device, ctype = "cpu", "int8"
                m = WhisperModel(str(model_dir(name)), device="cpu", compute_type="int8", cpu_threads=threads)
                key = (name, device, ctype)
            else:
                raise
        _model_cache[key] = m
        return m, device, ctype


HINGLISH_PROMPT = (
    "Namaste dosto, aaj ke show mein aapka swagat hai. "
    "Bhai sach batau toh life mein yeh bahut important baat hai, let's start!"
)
HINDI_DEVANAGARI_PROMPT = "नमस्ते दोस्तों, आज के इस वीडियो में आपका स्वागत है। यह बहुत महत्वपूर्ण बात है।"
TRANSLATE_CAPABLE_ORDER = ("large-v3", "medium", "small", "base", "tiny")


def _resolve_lang_mode(language: str | None) -> tuple[str, str | None, str, str | None, bool]:
    """Return (mode_label, whisper_lang, whisper_task, initial_prompt, romanize_hinglish)."""
    if not language or language == "auto":
        return "auto", None, "transcribe", None, False
    code = language.strip().lower()
    if code == "hinglish":
        return "hinglish", "hi", "transcribe", HINGLISH_PROMPT, True
    if code == "hi":
        return "hi", "hi", "transcribe", HINDI_DEVANAGARI_PROMPT, False
    if code == "en_translate":
        return "en_translate", None, "translate", None, False
    return code, code, "transcribe", None, False


def _resolve_translate_model(preferred: str) -> tuple[str, str]:
    """OpenAI's distilled `large-v3-turbo` does not include translation heads; pick an installed translate-capable
    multilingual Whisper model when available, otherwise fall back gracefully to `en` transcription."""
    if preferred != "large-v3-turbo" and is_installed(preferred):
        return preferred, "translate"
    for cand in TRANSLATE_CAPABLE_ORDER:
        if is_installed(cand):
            return cand, "translate"
    return preferred, "transcribe"


def unload_models() -> None:
    with _model_lock:
        _model_cache.clear()


def transcribe(wav_path: str | Path, duration: float, model_name: str, device_pref: str = "auto",
               language: str | None = None, progress: Callable[[float, str], None] | None = None, ctx=None) -> dict[str, Any]:
    from . import hinglish
    from .media import load_wav

    mode_label, lang, task, prompt, romanize = _resolve_lang_mode(language)
    used_model = model_name
    if task == "translate":
        used_model, task = _resolve_translate_model(model_name)
        if task == "transcribe":
            lang = "en"
    model, device, ctype = load_model(used_model, device_pref)

    # Decode the 16 kHz analysis WAV ourselves (avoids PyAV API differences across versions).
    audio, sr = load_wav(wav_path)
    if sr != 16000:
        import librosa

        audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)

    def _run(m, dev):
        segments, info = m.transcribe(
            audio, language=lang, task=task, initial_prompt=prompt, word_timestamps=True, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500}, beam_size=5, condition_on_previous_text=False,
        )
        words: list[dict[str, Any]] = []
        segs: list[dict[str, Any]] = []
        for seg in segments:
            if ctx is not None:
                ctx.check_cancel()
            w0 = len(words)
            for w in seg.words or []:
                txt = w.word.strip()
                if romanize:
                    txt = hinglish.to_hinglish(txt).strip()
                if not txt:
                    continue
                words.append({"w": txt, "s": round(float(w.start), 3), "e": round(float(max(w.end, w.start + 0.02)), 3),
                              "p": round(float(w.probability), 3)})
            seg_txt = hinglish.to_hinglish(seg.text.strip()) if romanize else seg.text.strip()
            segs.append({"s": round(seg.start, 3), "e": round(seg.end, 3), "text": seg_txt, "w0": w0, "w1": len(words),
                         "no_speech_prob": round(float(seg.no_speech_prob), 3), "avg_logprob": round(float(seg.avg_logprob), 3)})
            if progress and duration > 0:
                progress(min(0.999, seg.end / duration), f"Transcribed {segmentation_ts(seg.end)} / {segmentation_ts(duration)} on {dev}")
        return words, segs, info

    try:
        words, segs, info = _run(model, device)
    except RuntimeError as exc:
        if device != "cuda":
            raise
        log.warning("CUDA transcription failed (%s); retrying on CPU", exc)
        unload_models()
        model, device, ctype = load_model(used_model, "cpu")
        words, segs, info = _run(model, device)

    words = _fix_monotonic(words, segs)
    sentences = segmentation.build_sentences(words)
    return {
        "language": "hinglish" if mode_label == "hinglish" else ("en" if task == "translate" else info.language),
        "language_mode": mode_label,
        "language_probability": round(float(info.language_probability), 3),
        "duration": duration,
        "model": used_model,
        "device": device,
        "compute_type": ctype,
        "words": words,
        "segments": segs,
        "sentences": sentences,
        "pauses": segmentation.find_pauses(words, 0.7),
    }


def transcribe_slice(wav_path: str | Path, start: float, end: float, mode: str = "hinglish",
                     model_name: str | None = None, device_pref: str = "auto") -> tuple[list[dict[str, Any]], str]:
    """Fast per-clip audio slice transcription/translation for switching clip captions between
    Hindi (Devanagari), Hinglish (Roman Hindi + English), and English without re-analyzing the full video."""
    import soundfile as sf
    from . import hinglish

    s_cfg = config.get_settings()
    pref_model = model_name or s_cfg.get("whisper_model", "small")
    if not is_installed(pref_model):
        pref_model = next((m for m in ("large-v3-turbo", "large-v3", "medium", "small", "base", "tiny") if is_installed(m)), pref_model)

    req_mode = "en_translate" if mode == "en" else mode
    _, lang, task, prompt, romanize = _resolve_lang_mode(req_mode)
    used_model = pref_model
    if task == "translate":
        used_model, task = _resolve_translate_model(pref_model)
        if task == "transcribe":
            lang = "en"

    info_sf = sf.info(str(wav_path))
    sr = info_sf.samplerate
    slice_s = max(0.0, float(start) - 0.12)
    slice_e = min(float(info_sf.duration), float(end) + 0.25)
    f0 = max(0, int(slice_s * sr))
    f1 = max(f0 + 1, int(slice_e * sr))
    audio, _ = sf.read(str(wav_path), start=f0, stop=f1, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:
        import librosa

        audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)

    model, device, _ = load_model(used_model, device_pref)
    try:
        segments, _ = model.transcribe(
            audio, language=lang, task=task, initial_prompt=prompt, word_timestamps=True, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 350}, beam_size=5, condition_on_previous_text=False,
        )
        words: list[dict[str, Any]] = []
        segs: list[dict[str, Any]] = []
        for seg in segments:
            w0 = len(words)
            for w in seg.words or []:
                txt = w.word.strip()
                if romanize:
                    txt = hinglish.to_hinglish(txt).strip()
                if not txt:
                    continue
                ws = round(slice_s + float(w.start), 3)
                we = round(slice_s + float(max(w.end, w.start + 0.03)), 3)
                words.append({"w": txt, "s": ws, "e": we, "p": round(float(w.probability), 3)})
            segs.append({
                "s": round(slice_s + float(seg.start), 3),
                "e": round(slice_s + float(seg.end), 3),
                "w0": w0,
                "w1": len(words),
            })
    finally:
        unload_models()
    return _fix_monotonic(words, segs), used_model


def _fix_monotonic(words: list[dict[str, Any]], segs: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Repair collapsed/overlapping Whisper word timestamps (common in large-v3-turbo) so every word
    has a positive, strictly non-overlapping [s, e] span."""
    if not words:
        return words
    # First spread collapsed runs inside each segment when segment bounds are available
    if segs:
        for seg in segs:
            a, b = int(seg.get("w0", 0)), int(seg.get("w1", 0))
            if b - a < 1 or b > len(words):
                continue
            s_lo = max(0.0, float(seg.get("s", words[a]["s"])))
            s_hi = max(s_lo + 0.04 * (b - a), float(seg.get("e", words[b - 1]["e"])))
            sub = words[a:b]
            k = 0
            while k < len(sub):
                collapsed = (sub[k]["e"] - sub[k]["s"] <= 0.03) or (k + 1 < len(sub) and sub[k + 1]["s"] <= sub[k]["s"] + 0.005)
                if not collapsed:
                    k += 1
                    continue
                j = k
                while j + 1 < len(sub) and (
                    sub[j + 1]["s"] <= sub[j]["e"] + 0.01 or sub[j + 1]["e"] - sub[j + 1]["s"] <= 0.03
                ):
                    j += 1
                span_s = max(s_lo, sub[k - 1]["e"] if k > 0 else sub[k]["s"])
                next_s = sub[j + 1]["s"] if j + 1 < len(sub) else s_hi
                span_e = max(span_s + 0.05 * (j - k + 1), min(s_hi, max(sub[j]["e"], next_s)))
                weights = [max(1, len(sub[m]["w"])) for m in range(k, j + 1)]
                wsum = sum(weights)
                cur = span_s
                for idx_m, wt in zip(range(k, j + 1), weights):
                    dur = (span_e - span_s) * (wt / wsum)
                    sub[idx_m]["s"] = round(cur, 3)
                    cur += dur
                    sub[idx_m]["e"] = round(max(sub[idx_m]["s"] + 0.03, cur), 3)
                k = j + 1

    # Global strict non-overlapping pass
    n = len(words)
    i = 0
    prev_end = 0.0
    while i < n:
        # Detect any remaining stacked words sharing identical/overlapping start times
        j = i
        while j + 1 < n and float(words[j + 1]["s"]) < max(prev_end, float(words[j]["e"])) - 0.002:
            j += 1
        if j > i:
            span_s = max(prev_end, float(words[i]["s"]))
            raw_e = max(float(words[m]["e"]) for m in range(i, j + 1))
            if j + 1 < n and float(words[j + 1]["s"]) > raw_e:
                raw_e = min(float(words[j + 1]["s"]), raw_e + 0.18 * (j - i + 1))
            span_e = max(span_s + 0.05 * (j - i + 1), raw_e)
            weights = [max(1, len(words[m]["w"])) for m in range(i, j + 1)]
            wsum = sum(weights)
            cur = span_s
            for m, wt in zip(range(i, j + 1), weights):
                dur = (span_e - span_s) * (wt / wsum)
                words[m]["s"] = round(cur, 3)
                cur += dur
                words[m]["e"] = round(max(words[m]["s"] + 0.03, cur), 3)
            prev_end = words[j]["e"]
            i = j + 1
        else:
            s = round(max(prev_end, float(words[i]["s"])), 3)
            e = round(max(s + 0.04, float(words[i]["e"])), 3)
            words[i]["s"], words[i]["e"] = s, e
            prev_end = e
            i += 1
    return words


def segmentation_ts(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
