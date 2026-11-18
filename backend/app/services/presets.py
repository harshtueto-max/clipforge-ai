"""Built-in editing presets (original configurations) and helpers."""
from __future__ import annotations

import copy
from typing import Any

BUILTIN_PRESETS: dict[str, dict[str, Any]] = {
    "podcast_pro": {
        "name": "Podcast Pro",
        "description": "Clean speaker-focused framing, word-highlight captions, light music bed with strong ducking.",
        "config": {
            "caption_style": "podcast_pro", "reframe": {"mode": "auto", "smoothness": 0.75, "prefer_split": False},
            "zoom": {"frequency": "low", "scale": 1.1}, "cuts": {"remove_silence": True, "min_silence": 1.1, "keep_pad": 0.26},
            "music": {"enabled": True, "moods": ["podcast", "lofi", "corporate"], "volume": 0.10, "ducking": True, "fade_in": 1.0, "fade_out": 1.5},
            "sfx": {"intensity": "low"}, "audio": {"enhance_voice": True, "denoise": False, "loudness": -14},
        },
    },
    "high_retention": {
        "name": "High Retention Talking Head",
        "description": "Tight jump cuts, frequent punch-in zooms, bold animated captions, energetic music.",
        "config": {
            "caption_style": "bold_viral", "reframe": {"mode": "auto", "smoothness": 0.6, "prefer_split": False},
            "zoom": {"frequency": "high", "scale": 1.15}, "cuts": {"remove_silence": True, "min_silence": 0.85, "keep_pad": 0.20},
            "music": {"enabled": True, "moods": ["energetic", "motivational"], "volume": 0.09, "ducking": True, "fade_in": 0.5, "fade_out": 1.0},
            "sfx": {"intensity": "medium"}, "audio": {"enhance_voice": True, "denoise": False, "loudness": -13},
        },
    },
    "cinematic_story": {
        "name": "Cinematic Storytelling",
        "description": "Slow smooth reframing, minimal zoom, documentary captions, cinematic score.",
        "config": {
            "caption_style": "documentary", "reframe": {"mode": "auto", "smoothness": 0.9, "prefer_split": False},
            "zoom": {"frequency": "none", "scale": 1.0}, "cuts": {"remove_silence": True, "min_silence": 1.4, "keep_pad": 0.34},
            "music": {"enabled": True, "moods": ["cinematic", "emotional"], "volume": 0.14, "ducking": True, "fade_in": 2.0, "fade_out": 2.5},
            "sfx": {"intensity": "low"}, "audio": {"enhance_voice": True, "denoise": False, "loudness": -15},
        },
    },
    "educational": {
        "name": "Educational Creator",
        "description": "Keyword-highlighted captions, moderate cuts, calm background bed.",
        "config": {
            "caption_style": "educational", "reframe": {"mode": "auto", "smoothness": 0.75, "prefer_split": False},
            "zoom": {"frequency": "medium", "scale": 1.1}, "cuts": {"remove_silence": True, "min_silence": 1.0, "keep_pad": 0.24},
            "music": {"enabled": True, "moods": ["corporate", "lofi", "documentary"], "volume": 0.08, "ducking": True, "fade_in": 1.0, "fade_out": 1.5},
            "sfx": {"intensity": "low"}, "audio": {"enhance_voice": True, "denoise": False, "loudness": -14},
        },
    },
    "fast_commentary": {
        "name": "Fast Commentary",
        "description": "Aggressive dead-air removal, frequent zooms, karaoke captions, punchy SFX.",
        "config": {
            "caption_style": "karaoke", "reframe": {"mode": "auto", "smoothness": 0.55, "prefer_split": False},
            "zoom": {"frequency": "high", "scale": 1.18}, "cuts": {"remove_silence": True, "min_silence": 0.8, "keep_pad": 0.18},
            "music": {"enabled": True, "moods": ["energetic", "suspense"], "volume": 0.08, "ducking": True, "fade_in": 0.3, "fade_out": 0.8},
            "sfx": {"intensity": "medium"}, "audio": {"enhance_voice": True, "denoise": False, "loudness": -13},
        },
    },
    "minimal_interview": {
        "name": "Minimal Interview",
        "description": "Split-screen when two people are on camera, clean captions, no music.",
        "config": {
            "caption_style": "clean_minimal", "reframe": {"mode": "auto", "smoothness": 0.85, "prefer_split": True},
            "zoom": {"frequency": "none", "scale": 1.0}, "cuts": {"remove_silence": True, "min_silence": 1.25, "keep_pad": 0.30},
            "music": {"enabled": False, "moods": ["podcast"], "volume": 0.08, "ducking": True, "fade_in": 1.0, "fade_out": 1.5},
            "sfx": {"intensity": "none"}, "audio": {"enhance_voice": True, "denoise": False, "loudness": -15},
        },
    },
    "comedy_highlights": {
        "name": "Comedy Highlights",
        "description": "Quick cuts, pop-in captions, playful music and occasional comedic SFX.",
        "config": {
            "caption_style": "bold_viral", "reframe": {"mode": "auto", "smoothness": 0.6, "prefer_split": False},
            "zoom": {"frequency": "medium", "scale": 1.16}, "cuts": {"remove_silence": True, "min_silence": 1.0, "keep_pad": 0.25},
            "music": {"enabled": True, "moods": ["comedy", "lofi"], "volume": 0.09, "ducking": True, "fade_in": 0.5, "fade_out": 1.0},
            "sfx": {"intensity": "medium"}, "audio": {"enhance_voice": True, "denoise": False, "loudness": -13},
        },
    },
    "documentary_shorts": {
        "name": "Documentary Shorts",
        "description": "Boxed serif captions, gentle reframing, documentary score, noise reduction on.",
        "config": {
            "caption_style": "documentary", "reframe": {"mode": "auto", "smoothness": 0.9, "prefer_split": False},
            "zoom": {"frequency": "low", "scale": 1.06}, "cuts": {"remove_silence": True, "min_silence": 1.35, "keep_pad": 0.34},
            "music": {"enabled": True, "moods": ["documentary", "cinematic", "emotional"], "volume": 0.12, "ducking": True, "fade_in": 2.0, "fade_out": 2.0},
            "sfx": {"intensity": "none"}, "audio": {"enhance_voice": True, "denoise": True, "loudness": -15},
        },
    },
}

CATEGORY_MOODS = {
    "funny": ["comedy", "lofi"], "emotional": ["emotional", "cinematic"], "educational": ["corporate", "documentary", "lofi"],
    "advice": ["motivational", "corporate"], "story": ["cinematic", "documentary"], "opinion": ["suspense", "podcast"],
    "qa": ["podcast", "lofi"], "insight": ["podcast", "corporate"],
}

ZOOM_EVERY = {"none": 0, "low": 14.0, "medium": 8.0, "high": 4.5}


def preset_config(preset: dict[str, Any] | None) -> dict[str, Any]:
    base = copy.deepcopy(BUILTIN_PRESETS["podcast_pro"]["config"])
    if preset:
        for k, v in preset.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                base[k].update(v)
            else:
                base[k] = v
    return base
