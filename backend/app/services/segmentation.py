"""Pure-Python transcript segmentation helpers (sentences, pauses, time mapping). Unit-tested."""
from __future__ import annotations

import re
from typing import Any

ABBREVIATIONS = {
    "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.", "etc.", "e.g.", "i.e.", "u.s.", "u.k.", "a.m.", "p.m.",
    "no.", "inc.", "ltd.", "co.", "jan.", "feb.", "mar.", "apr.", "jun.", "jul.", "aug.", "sep.", "sept.", "oct.", "nov.", "dec.",
}
TERMINALS = (".", "?", "!", "।", "॥")


def is_sentence_end(word: str) -> bool:
    raw = word.strip().strip('"\')]}»”’')
    w = raw.lower()
    if not w:
        return False
    if w.endswith(("...", "…")):
        return False
    if w in ABBREVIATIONS:
        return False
    if re.fullmatch(r"(\w\.){2,}", w):  # initials like U.S.A.
        return False
    if re.fullmatch(r"\d+\.", w):  # numbered list "1."
        return False
    return w.endswith(TERMINALS)


def build_sentences(words: list[dict[str, Any]], pause_split: float = 1.2, max_words: int = 45,
                    soft_pause: float = 0.45) -> list[dict[str, Any]]:
    """Group timed words into sentences.

    words: [{"w": str, "s": float, "e": float}] in chronological order.
    Splits at terminal punctuation, at long pauses, and breaks very long run-ons at comma+pause.
    """
    sentences: list[dict[str, Any]] = []
    if not words:
        return sentences
    start = 0
    n = len(words)
    for i in range(n):
        w = words[i]
        gap_after = (words[i + 1]["s"] - w["e"]) if i + 1 < n else 999.0
        length = i - start + 1
        end_here = False
        if is_sentence_end(w["w"]):
            end_here = True
        elif gap_after >= pause_split:
            end_here = True
        elif length >= max_words and (w["w"].rstrip().endswith((",", ";", ":")) or gap_after >= soft_pause):
            end_here = True
        elif length >= max_words * 2:
            end_here = True
        if end_here or i == n - 1:
            sentences.append(_mk_sentence(words, start, i + 1, len(sentences)))
            start = i + 1
    # pauses
    for k, s in enumerate(sentences):
        s["pause_before"] = round(s["s"] - sentences[k - 1]["e"], 3) if k > 0 else round(s["s"], 3)
        s["pause_after"] = round(sentences[k + 1]["s"] - s["e"], 3) if k + 1 < len(sentences) else 5.0
    return sentences


def _mk_sentence(words, a, b, idx):
    text = " ".join(x["w"].strip() for x in words[a:b]).strip()
    text = re.sub(r"\s+([,.?!;:…])", r"\1", text)
    return {
        "i": idx,
        "s": round(words[a]["s"], 3),
        "e": round(words[b - 1]["e"], 3),
        "text": text,
        "w0": a,
        "w1": b,
        "complete": bool(is_sentence_end(words[b - 1]["w"])),
    }


def find_pauses(words: list[dict[str, Any]], min_gap: float = 0.6) -> list[dict[str, float]]:
    out = []
    for i in range(1, len(words)):
        gap = words[i]["s"] - words[i - 1]["e"]
        if gap >= min_gap:
            out.append({"s": round(words[i - 1]["e"], 3), "e": round(words[i]["s"], 3), "d": round(gap, 3)})
    return out


def keep_segments(start: float, end: float, cuts: list[dict[str, float]]) -> list[tuple[float, float]]:
    """Given clip bounds and removed ranges (source time), return kept [s,e] ranges in order."""
    cuts = sorted(((max(start, c["s"]), min(end, c["e"])) for c in cuts if c["e"] > start and c["s"] < end))
    segs: list[tuple[float, float]] = []
    cur = start
    for s, e in cuts:
        if s > cur + 1e-3:
            segs.append((cur, s))
        cur = max(cur, e)
    if end > cur + 1e-3:
        segs.append((cur, end))
    return [(round(a, 3), round(b, 3)) for a, b in segs if b - a >= 0.04]


def source_to_output(t: float, segments: list[tuple[float, float]]) -> float | None:
    """Map a source timestamp to output timeline time. None if t falls inside a removed range."""
    acc = 0.0
    for s, e in segments:
        if s - 1e-6 <= t <= e + 1e-6:
            return acc + (min(max(t, s), e) - s)
        acc += e - s
    return None


def output_to_source(t: float, segments: list[tuple[float, float]]) -> float:
    acc = 0.0
    for s, e in segments:
        d = e - s
        if t <= acc + d:
            return s + (t - acc)
        acc += d
    return segments[-1][1] if segments else 0.0


def output_duration(segments: list[tuple[float, float]]) -> float:
    return round(sum(e - s for s, e in segments), 3)


def silence_cuts(words: list[dict[str, Any]], start: float, end: float, min_silence: float = 0.6,
                 keep_pad: float = 0.15, vad: list[dict[str, float]] | None = None,
                 protected: list[dict[str, float]] | None = None) -> list[dict[str, float]]:
    """Compute removable dead-air ranges inside [start, end], keeping `keep_pad` around all spoken words,
    Silero VAD voice activity, and protected non-speech intervals (e.g. laughter)."""
    spans: list[tuple[float, float]] = [
        (max(start, float(w["s"])), min(end, float(w["e"])))
        for w in words
        if float(w["e"]) > start and float(w["s"]) < end
    ]
    for extra in (vad or (), protected or ()):
        for seg in extra:
            s0, e0 = float(seg.get("s", 0.0)), float(seg.get("e", 0.0))
            if e0 > start and s0 < end and e0 > s0:
                spans.append((max(start, s0), min(end, e0)))
    if not spans:
        return []
    spans.sort()
    merged: list[list[float]] = [[spans[0][0], spans[0][1]]]
    for s0, e0 in spans[1:]:
        if s0 <= merged[-1][1] + 0.08:
            merged[-1][1] = max(merged[-1][1], e0)
        else:
            merged.append([s0, e0])

    cuts: list[dict[str, float]] = []
    # leading/trailing dead air inside the clip
    if merged[0][0] - start > min_silence:
        cuts.append({"s": round(start, 3), "e": round(merged[0][0] - keep_pad, 3), "auto": True})
    for (_, a_e), (b_s, _) in zip(merged, merged[1:]):
        gap = b_s - a_e
        if gap > min_silence and (b_s - keep_pad) - (a_e + keep_pad) > 0.08:
            cuts.append({"s": round(a_e + keep_pad, 3), "e": round(b_s - keep_pad, 3), "auto": True})
    if end - merged[-1][1] > min_silence:
        cuts.append({"s": round(merged[-1][1] + keep_pad, 3), "e": round(end, 3), "auto": True})
    return [c for c in cuts if c["e"] - c["s"] > 0.08]
