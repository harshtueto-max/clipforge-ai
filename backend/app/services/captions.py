"""Caption engine: word-timed caption chunking, style presets, and ASS (libass) subtitle generation."""
from __future__ import annotations

import copy
import re
import sys
from pathlib import Path
from typing import Any

from . import hinglish, segmentation
from .models_util import short_id

DEVANAGARI_FONTS = {
    "Nirmala UI", "Nirmala UI Semibold", "Mangal", "Aparajita", "Kokila", "Utsaah",
    "Noto Sans Devanagari", "Noto Sans",
}


def default_devanagari_font() -> str:
    return "Nirmala UI" if sys.platform == "win32" else "Noto Sans Devanagari"

CAPTION_STYLES: dict[str, dict[str, Any]] = {
    "clean_minimal": {
        "name": "Clean Minimal", "font": "Segoe UI Semibold", "size": 0.042, "bold": False, "color": "#FFFFFF",
        "highlight_color": "#FFFFFF", "stroke_color": "#000000", "stroke": 0.0, "shadow": 2.0, "shadow_color": "#000000",
        "position": "bottom", "margin": 0.16, "animation": "fade", "uppercase": False, "words_per_caption": 7,
        "line_spacing": 1.0, "box": False, "box_color": "#000000", "box_opacity": 0.55, "highlight_keywords": False,
    },
    "podcast_pro": {
        "name": "Podcast Pro", "font": "Arial Black", "size": 0.05, "bold": True, "color": "#FFFFFF",
        "highlight_color": "#FFD43B", "stroke_color": "#000000", "stroke": 4.0, "shadow": 1.5, "shadow_color": "#000000",
        "position": "center_low", "margin": 0.28, "animation": "highlight", "uppercase": False, "words_per_caption": 4,
        "line_spacing": 1.0, "box": False, "box_color": "#000000", "box_opacity": 0.5, "highlight_keywords": False,
    },
    "bold_viral": {
        "name": "Bold Viral", "font": "Impact", "size": 0.068, "bold": False, "color": "#FFFFFF",
        "highlight_color": "#39FF14", "stroke_color": "#000000", "stroke": 6.0, "shadow": 3.0, "shadow_color": "#000000",
        "position": "center", "margin": 0.0, "animation": "pop", "uppercase": True, "words_per_caption": 2,
        "line_spacing": 1.0, "box": False, "box_color": "#000000", "box_opacity": 0.5, "highlight_keywords": True,
    },
    "highlighted_keywords": {
        "name": "Highlighted Keywords", "font": "Arial", "size": 0.052, "bold": True, "color": "#FFFFFF",
        "highlight_color": "#FF5C5C", "stroke_color": "#111111", "stroke": 4.0, "shadow": 1.0, "shadow_color": "#000000",
        "position": "center_low", "margin": 0.26, "animation": "none", "uppercase": False, "words_per_caption": 5,
        "line_spacing": 1.0, "box": False, "box_color": "#000000", "box_opacity": 0.5, "highlight_keywords": True,
    },
    "karaoke": {
        "name": "Karaoke", "font": "Verdana", "size": 0.048, "bold": True, "color": "#FFFFFF",
        "highlight_color": "#00D1FF", "stroke_color": "#000000", "stroke": 3.5, "shadow": 1.0, "shadow_color": "#000000",
        "position": "bottom", "margin": 0.2, "animation": "karaoke", "uppercase": False, "words_per_caption": 6,
        "line_spacing": 1.0, "box": False, "box_color": "#000000", "box_opacity": 0.5, "highlight_keywords": False,
    },
    "documentary": {
        "name": "Documentary", "font": "Georgia", "size": 0.04, "bold": False, "color": "#F5F1E8",
        "highlight_color": "#F5F1E8", "stroke_color": "#000000", "stroke": 0.0, "shadow": 0.0, "shadow_color": "#000000",
        "position": "bottom", "margin": 0.12, "animation": "fade", "uppercase": False, "words_per_caption": 9,
        "line_spacing": 1.1, "box": True, "box_color": "#000000", "box_opacity": 0.6, "highlight_keywords": False,
    },
    "educational": {
        "name": "Educational", "font": "Segoe UI Black", "size": 0.046, "bold": True, "color": "#FFFFFF",
        "highlight_color": "#7CC4FF", "stroke_color": "#0B1B33", "stroke": 4.0, "shadow": 1.0, "shadow_color": "#000000",
        "position": "center_low", "margin": 0.25, "animation": "highlight", "uppercase": False, "words_per_caption": 5,
        "line_spacing": 1.0, "box": False, "box_color": "#000000", "box_opacity": 0.5, "highlight_keywords": True,
    },
}

POSITIONS = {"top": (8, 0.12), "center": (5, 0.0), "center_low": (2, 0.28), "bottom": (2, 0.16)}


def style_for(style_id: str, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    st = copy.deepcopy(CAPTION_STYLES.get(style_id) or CAPTION_STYLES["podcast_pro"])
    st["id"] = style_id if style_id in CAPTION_STYLES else "podcast_pro"
    if overrides:
        for k, v in overrides.items():
            if v is not None:
                st[k] = v
    return st


def sanitize_items(items: list[dict[str, Any]], min_dur: float = 0.12) -> list[dict[str, Any]]:
    """Guarantee every caption item has `end >= start + min_dur` and consecutive items do not overlap."""
    if not items:
        return []
    out = [copy.deepcopy(it) for it in items if str(it.get("text", "")).strip()]
    out.sort(key=lambda x: (float(x.get("start", 0.0)), float(x.get("end", 0.0))))
    for it in out:
        s = max(0.0, float(it.get("start", 0.0)))
        e = max(s + min_dur, float(it.get("end", s + min_dur)))
        it["start"], it["end"] = round(s, 3), round(e, 3)
    for a, b in zip(out, out[1:]):
        if b["start"] < a["end"]:
            if b["end"] >= a["start"] + 2 * min_dur:
                mid = round(max(a["start"] + min_dur, min(b["end"] - min_dur, b["start"])), 3)
                a["end"] = mid
                b["start"] = mid
            else:
                b["start"] = round(a["end"], 3)
            if b["end"] < b["start"] + min_dur:
                b["end"] = round(b["start"] + min_dur, 3)
    return out


def build_items(words: list[dict[str, Any]], start: float, end: float, words_per_caption: int = 4,
                max_gap: float = 0.6, max_chars: int = 28) -> list[dict[str, Any]]:
    """Group real transcript words (source time) into caption items. Never invents text."""
    raw_inside = [dict(w) for w in words if w["s"] >= start - 0.05 and w["e"] <= end + 0.3]
    if not raw_inside:
        return []
    from .transcription import _fix_monotonic

    inside = _fix_monotonic(raw_inside)
    items: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []

    def flush():
        if cur:
            s0 = round(float(cur[0]["s"]), 3)
            e0 = round(max(s0 + 0.12, float(cur[-1]["e"])), 3)
            items.append({
                "id": short_id(), "start": s0, "end": e0,
                "text": " ".join(w["w"] for w in cur), "words": [{"w": w["w"], "s": w["s"], "e": w["e"]} for w in cur],
                "style": {},
            })
            cur.clear()

    for k, w in enumerate(inside):
        if cur:
            gap = w["s"] - cur[-1]["e"]
            chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
            if len(cur) >= words_per_caption or gap > max_gap or chars > max_chars * 2 or segmentation.is_sentence_end(cur[-1]["w"]):
                flush()
        cur.append(w)
    flush()
    # extend each caption slightly to the next one (avoid flicker) only when strictly positive gap
    for a, b in zip(items, items[1:]):
        gap = b["start"] - a["end"]
        if 0 < gap < 0.3:
            a["end"] = round(b["start"], 3)
    return sanitize_items(items)


def retime_words(item: dict[str, Any]) -> list[dict[str, Any]]:
    """If caption text was edited, keep original word timings when counts match, otherwise distribute evenly."""
    toks = item["text"].replace("\n", " \n ").split(" ")
    toks = [t for t in toks if t != ""]
    real = [t for t in toks if t != "\n"]
    ws = item.get("words") or []
    if len(ws) == len(real) and all(w.get("s") is not None for w in ws):
        return [{"w": t, "s": w["s"], "e": w["e"]} for t, w in zip(real, ws)]
    n = max(1, len(real))
    d = (item["end"] - item["start"]) / n
    return [{"w": t, "s": item["start"] + k * d, "e": item["start"] + (k + 1) * d} for k, t in enumerate(real)]


def hex_to_ass(color: str, alpha: float = 0.0) -> str:
    c = (color or "#FFFFFF").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", c):
        c = "FFFFFF"
    r, g, b = c[0:2], c[2:4], c[4:6]
    a = int(max(0, min(255, round(alpha * 255))))
    return f"&H{a:02X}{b}{g}{r}".upper()


def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def _fmt_time(t: float) -> str:
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    cs = int(round((s - int(s)) * 100))
    si = int(s)
    if cs == 100:
        si += 1
        cs = 0
    return f"{h}:{m:02d}:{si:02d}.{cs:02d}"


def build_ass(items: list[dict[str, Any]], style: dict[str, Any], width: int, height: int,
              segments: list[tuple[float, float]], keywords: set[str] | None = None) -> str:
    items = sanitize_items(items)
    keywords = {k.lower() for k in (keywords or set())}
    has_deva = any(hinglish.has_devanagari(it.get("text", "")) for it in items)
    font_name = str(style.get("font", "Arial")).replace(",", " ").strip() or "Arial"
    use_bold = bool(style.get("bold"))
    if has_deva and font_name not in DEVANAGARI_FONTS:
        font_name = default_devanagari_font()
        use_bold = True
    fs = max(12, int(round(style["size"] * height)))
    an, _ = POSITIONS.get(style.get("position", "bottom"), (2, 0.16))
    margin_v = int(round(float(style.get("margin", 0.16)) * height)) if an != 5 else 0
    outline = float(style.get("stroke", 0)) * height / 1920 * 1.6
    shadow = float(style.get("shadow", 0)) * height / 1920 * 1.6
    border_style = 3 if style.get("box") else 1
    back = hex_to_ass(style.get("box_color", "#000000"), 1 - float(style.get("box_opacity", 0.5))) if style.get("box") \
        else hex_to_ass(style.get("shadow_color", "#000000"), 0.3)
    outline_col = hex_to_ass(style.get("box_color", "#000000"), 1 - float(style.get("box_opacity", 0.5))) if style.get("box") \
        else hex_to_ass(style.get("stroke_color", "#000000"))
    if style.get("box"):
        outline = max(outline, fs * 0.25)
    primary = hex_to_ass(style["color"])
    hl = hex_to_ass(style.get("highlight_color", style["color"]))
    karaoke = style.get("animation") == "karaoke"
    spacing = 0
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,{font_name},{fs},{hl if karaoke else primary},{primary},{outline_col},{back},"
        f"{-1 if use_bold else 0},0,0,0,100,{int(100 * float(style.get('line_spacing', 1.0)))},{spacing},0,{border_style},"
        f"{outline:.1f},{shadow:.1f},{an},{int(width * 0.08)},{int(width * 0.08)},{margin_v},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    anim = style.get("animation", "none")
    for it in items:
        ist = dict(style)
        ist.update({k: v for k, v in (it.get("style") or {}).items() if v is not None})
        words = retime_words(it)
        text_tokens = it["text"].replace("\n", " \n ").split(" ")
        text_tokens = [t for t in text_tokens if t]
        o_s = _map(it["start"], segments, forward=True)
        o_e = _map(it["end"], segments, forward=False)
        if o_s is None or o_e is None or o_e - o_s < 0.05:
            continue
        upper = bool(ist.get("uppercase"))
        it_primary = hex_to_ass(ist.get("color", style["color"]))
        it_hl = hex_to_ass(ist.get("highlight_color", style.get("highlight_color")))
        prefix = ""
        if ist.get("pos_x") is not None and ist.get("pos_y") is not None:
            prefix += f"\\an5\\pos({int(float(ist['pos_x']) * width)},{int(float(ist['pos_y']) * height)})"
        if it.get("style"):
            if ist.get("font") != style.get("font") and (not hinglish.has_devanagari(it["text"]) or ist.get("font") in DEVANAGARI_FONTS):
                prefix += f"\\fn{ist['font']}"
            if ist.get("size") != style.get("size"):
                prefix += f"\\fs{max(12, int(round(float(ist['size']) * height)))}"
            if ist.get("color") != style.get("color"):
                prefix += f"\\c{it_primary}"

        def word_txt(t: str) -> str:
            return _esc(t if hinglish.has_devanagari(t) else (t.upper() if upper else t))

        def kw_wrap(t: str) -> str:
            base = re.sub(r"[^\w'%-]", "", t.lower())
            if ist.get("highlight_keywords") and (base in keywords or re.fullmatch(r"\d+(\.\d+)?%?", base or "")):
                return f"{{\\c{it_hl}}}{word_txt(t)}{{\\c{it_primary}}}"
            return word_txt(t)

        if anim == "karaoke":
            parts, wi = [], 0
            cursor = o_s
            for t in text_tokens:
                if t == "\n":
                    parts.append("\\N")
                    continue
                w = words[min(wi, len(words) - 1)]
                ws_o = _map(w["e"], segments, forward=False) or cursor
                dur_cs = max(1, int(round((ws_o - cursor) * 100)))
                cursor = max(cursor, ws_o)
                parts.append(f"{{\\k{dur_cs}}}{word_txt(t)} ")
                wi += 1
            lines.append(f"Dialogue: 0,{_fmt_time(o_s)},{_fmt_time(o_e)},Default,,0,0,0,,{{{prefix}}}{''.join(parts).rstrip()}")
        elif anim == "highlight" and words:
            real_idx = 0
            spans = []
            for k, w in enumerate(words):
                a = _map(w["s"], segments, forward=True)
                z = _map(words[k + 1]["s"], segments, forward=True) if k + 1 < len(words) else o_e
                if a is None or z is None:
                    continue
                spans.append((k, max(a, o_s), max(z, a + 0.05)))
            if spans:
                spans[0] = (spans[0][0], o_s, spans[0][2])
            for k, a, z in spans:
                parts, wi = [], 0
                for t in text_tokens:
                    if t == "\n":
                        parts.append("\\N")
                        continue
                    if wi == k:
                        parts.append(f"{{\\c{it_hl}\\fscx108\\fscy108}}{word_txt(t)}{{\\c{it_primary}\\fscx100\\fscy100}}")
                    else:
                        parts.append(kw_wrap(t))
                    wi += 1
                txt = " ".join(parts).replace(" \\N ", "\\N")
                lines.append(f"Dialogue: 0,{_fmt_time(a)},{_fmt_time(min(z, o_e))},Default,,0,0,0,,{{{prefix}}}{txt}")
        else:
            body = " ".join("\\N" if t == "\n" else kw_wrap(t) for t in text_tokens).replace(" \\N ", "\\N")
            eff = ""
            if anim == "fade":
                eff = "\\fad(90,70)"
            elif anim == "pop":
                eff = "\\fscx70\\fscy70\\t(0,90,\\fscx112\\fscy112)\\t(90,160,\\fscx100\\fscy100)"
            lines.append(f"Dialogue: 0,{_fmt_time(o_s)},{_fmt_time(o_e)},Default,,0,0,0,,{{{prefix}{eff}}}{body}")
    return "\n".join(lines) + "\n"


def _map(t: float, segments: list[tuple[float, float]], forward: bool) -> float | None:
    """Map source time to output time; if t is inside a cut, snap to the next (forward) or previous segment edge."""
    m = segmentation.source_to_output(t, segments)
    if m is not None:
        return m
    acc = 0.0
    prev_end_out = None
    for s, e in segments:
        if t < s:
            return acc if forward else (prev_end_out if prev_end_out is not None else acc)
        acc += e - s
        prev_end_out = acc
    return prev_end_out


def write_ass(path: Path, *args, **kwargs) -> Path:
    path.write_text(build_ass(*args, **kwargs), encoding="utf-8")
    return path
