"""Clip discovery engine: candidate generation, multi-dimensional editorial scoring, duration targeting,
duplicate suppression and ranking. Everything here runs locally and deterministically from real analysis data.

Scores are *estimated editorial quality* scores, not predictions of social-media virality.
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import audio_analysis, semantic

log = logging.getLogger("clipforge.discovery")

DIMENSIONS = ["hook", "story", "engagement", "emotion", "information", "standalone", "av_quality"]
DIM_LABELS = {
    "hook": "Hook strength", "story": "Story completeness", "engagement": "Engagement potential",
    "emotion": "Emotional intensity", "information": "Information value", "standalone": "Standalone context",
    "av_quality": "Audio/visual quality",
}
CATEGORIES = ["insight", "story", "educational", "advice", "funny", "emotional", "opinion", "qa"]
CATEGORY_LABELS = {"insight": "Insight", "story": "Story", "educational": "Educational", "advice": "Advice", "funny": "Funny",
                   "emotional": "Emotional", "opinion": "Opinion", "qa": "Q&A"}
DEFAULT_WEIGHTS = {"hook": 20, "story": 20, "engagement": 15, "emotion": 15, "information": 10, "standalone": 10, "av_quality": 10}


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return float(max(lo, min(hi, x)))


def sat(x: float, k: float = 1.0) -> float:
    """Saturating 0..1 transform."""
    return 1.0 - math.exp(-max(0.0, x) / max(1e-6, k))


@dataclass
class Bundle:
    duration: float
    words: list[dict[str, Any]]
    sentences: list[dict[str, Any]]
    feats: list[dict[str, Any]] = field(default_factory=list)
    topic_bounds: list[int] = field(default_factory=list)
    topic_ids: list[int] = field(default_factory=list)
    adj_sim: np.ndarray = field(default_factory=lambda: np.zeros(0))
    keywords: list[str] = field(default_factory=list)
    audio_frames: dict[str, np.ndarray] | None = None
    vad: list[dict[str, float]] = field(default_factory=list)
    laughter: list[dict[str, float]] = field(default_factory=list)
    face_samples: list[dict[str, Any]] = field(default_factory=list)
    scenes: list[dict[str, float]] = field(default_factory=list)
    num_speakers: int = 1
    has_video: bool = True

    # derived
    start_q: np.ndarray = field(default_factory=lambda: np.zeros(0))
    end_q: np.ndarray = field(default_factory=lambda: np.zeros(0))
    s_audio: list[dict[str, float]] = field(default_factory=list)
    s_laugh: np.ndarray = field(default_factory=lambda: np.zeros(0))
    s_face: np.ndarray = field(default_factory=lambda: np.zeros(0))
    s_kw: np.ndarray = field(default_factory=lambda: np.zeros(0))
    s_speech: np.ndarray = field(default_factory=lambda: np.zeros(0))
    start_notes: list[list[str]] = field(default_factory=list)
    end_notes: list[list[str]] = field(default_factory=list)


def cuts_active_vad(vad: list[dict[str, float]], t: float, margin: float = 0.22) -> bool:
    """Return True if timestamp `t` slices inside an active Silero VAD speech segment away from its edges."""
    for v in vad:
        if v["s"] + margin < t < v["e"] - margin:
            return True
        if v["s"] > t:
            break
    return False


def prepare(b: Bundle) -> Bundle:
    S = b.sentences
    n = len(S)
    if not b.feats:
        b.feats = semantic.sentence_features(S, b.words)
    if not b.topic_ids:
        X, vec = semantic.tfidf_matrix(S)
        b.topic_bounds, b.topic_ids, _ = semantic.topic_segments(S, X)
        b.adj_sim = semantic.adjacent_similarity(X)
        b.keywords = semantic.global_keywords(X, vec)
    bset = set(b.topic_bounds)
    kwset = set(b.keywords[:30])
    vad_s = np.array([v["s"] for v in b.vad]) if b.vad else np.zeros(0)
    vad_e = np.array([v["e"] for v in b.vad]) if b.vad else np.zeros(0)

    def _mid_vad(t: float, margin: float = 0.22) -> bool:
        if not len(vad_s):
            return False
        k = int(np.searchsorted(vad_s, t, side="right") - 1)
        return k >= 0 and float(vad_s[k]) + margin < t < float(vad_e[k]) - margin

    start_q = np.zeros(n)
    end_q = np.zeros(n)
    b.start_notes, b.end_notes = [], []
    for i, (s, f) in enumerate(zip(S, b.feats)):
        notes: list[str] = []
        q = 0.5
        pb = float(s.get("pause_before", 0))
        if i in bset:
            q += 0.22; notes.append("begins a new topic")
        if pb >= 0.6:
            q += 0.14; notes.append(f"follows a {pb:.1f}s pause")
        elif pb >= 0.3 and not _mid_vad(s["s"], 0.18):
            q += 0.06
        if i > 0 and S[i - 1].get("speaker") != s.get("speaker"):
            q += 0.08; notes.append("starts on a speaker turn")
        if i > 0 and not S[i - 1].get("complete", True) and pb < 0.8:
            q -= 0.42; notes.append("starts mid-sentence")
        if pb < 0.25 and _mid_vad(s["s"], 0.22):
            q -= 0.30; notes.append("starts inside continuous speech without a breath pause")
        if f["weak_open"] > 0:
            q -= min(0.48, 0.35 * f["weak_open"]); notes.append("opens with a connective/pronoun that needs prior context")
        if f["reference_back"] > 0:
            q -= 0.3; notes.append("refers back to earlier discussion")
        if f["question"]:
            q += 0.1; notes.append("opens with a question")
        if f["hook"] > 0:
            q += min(0.15, 0.08 * f["hook"])
        if f["n_words"] < 3:
            q -= 0.15
        start_q[i] = max(0.0, min(1.0, q))
        b.start_notes.append(notes)

        en: list[str] = []
        e = 0.4
        pa = float(s.get("pause_after", 0))
        txt = s["text"].rstrip()
        if txt.endswith(("...", "…")):
            e -= 0.42; en.append("trails off unfinished")
        elif s.get("complete", txt.endswith((".", "!", "?"))):
            e += 0.22; en.append("ends on a complete sentence")
        else:
            e -= 0.32; en.append("ends without closing punctuation")
        if pa >= 0.7:
            e += 0.18; en.append(f"followed by a {min(9.9, pa):.1f}s pause")
        elif pa >= 0.35 and not _mid_vad(s["e"], 0.18):
            e += 0.08
        if pa < 0.25 and _mid_vad(s["e"], 0.22):
            e -= 0.34; en.append("cuts off while speaker is still talking")
        if (i + 1) in bset or i == n - 1:
            e += 0.14; en.append("closes before a topic change")
        if f["conclusion"] > 0:
            e += min(0.2, 0.12 * f["conclusion"]); en.append("contains a concluding statement")
        if re.search(r"\b(and|but|so|because|or|the|a|to|of|that|with|for|in|on|is|was)[,.]?$", txt, re.I) or txt.endswith((",", ";", ":")):
            e -= 0.38; en.append("ends mid-thought")
        if f["question"]:
            if i + 1 < n and pa < 1.0 and S[i + 1].get("speaker") == s.get("speaker"):
                e -= 0.28; en.append("stops on a setup question before the speaker's answer")
            else:
                e -= 0.12
        if i + 1 < n and S[i + 1].get("speaker") != s.get("speaker"):
            e += 0.06
        end_q[i] = max(0.0, min(1.0, e))
        b.end_notes.append(en)
    b.start_q, b.end_q = start_q, end_q

    b.s_audio = []
    for s in S:
        if b.audio_frames is not None:
            b.s_audio.append(audio_analysis.window_stats(b.audio_frames, s["s"], s["e"]))
        else:
            b.s_audio.append({"energy": 0.0, "energy_var": 0.0, "pitch_var": 0.0, "excitement": 0.0, "excitement_max": 0.0})
    b.s_laugh = np.zeros(n)
    for ev in b.laughter:
        for i, s in enumerate(S):
            if ev["s"] <= s["e"] + 1.5 and ev["e"] >= s["s"]:
                b.s_laugh[i] = max(b.s_laugh[i], ev.get("confidence", 0.5))
    b.s_face = np.full(n, 0.0)
    if b.face_samples:
        ft = np.array([x["t"] for x in b.face_samples])
        fc = np.array([1.0 if x["faces"] else 0.0 for x in b.face_samples])
        sh = np.array([x.get("sharp", 100.0) for x in b.face_samples])
        for i, s in enumerate(S):
            m = (ft >= s["s"]) & (ft <= s["e"])
            b.s_face[i] = fc[m].mean() if m.any() else (1.0 if not b.has_video else 0.5)
        b.sharp_ref = float(np.median(sh)) if len(sh) else 100.0
    b.s_kw = np.array([sum(1 for t in semantic.tokens(s["text"]) if t in kwset) for s in S], dtype=float)
    b.s_speech = np.array([sum(b.words[k]["e"] - b.words[k]["s"] for k in range(s["w0"], s["w1"])) for s in S])
    return b


# ------------------------------------------------------------------ scoring
def score_window(b: Bundle, i: int, j: int, weights: dict[str, float] | None = None) -> dict[str, Any]:
    S, F = b.sentences, b.feats
    weights = weights or DEFAULT_WEIGHTS
    s0, s1 = S[i]["s"], S[j]["e"]
    D = max(1.0, s1 - s0)
    idx = range(i, j + 1)
    nw = sum(F[k]["n_words"] for k in idx) or 1
    ex: dict[str, list[str]] = {d: [] for d in DIMENSIONS}

    # ---- hook: first ~6 seconds
    hk = [k for k in idx if S[k]["s"] - s0 <= 6.0] or [i]
    f0 = F[i]
    hook_lex = sum(F[k]["hook"] for k in hk)
    h = 30.0
    if hook_lex > 0:
        h += 32 * sat(hook_lex, 1.0)
        hits = [x for k in hk for x in F[k].get("hook_hits", [])]
        ex["hook"].append(f"strong opening phrase (\"{hits[0]}\")" if hits else "strong opening language")
    if any(F[k]["question"] for k in hk):
        h += 14; ex["hook"].append("poses a question in the first seconds")
    if any(F[k]["numbers"] for k in hk):
        h += 8; ex["hook"].append("leads with a concrete number")
    if f0["you"] > 0:
        h += 6; ex["hook"].append("addresses the viewer directly")
    if 4 <= f0["n_words"] <= 16:
        h += 8; ex["hook"].append("short, punchy first line")
    h += 12 * max(F[k]["sent_mag"] for k in hk)
    a_first = np.mean([b.s_audio[k]["energy"] for k in hk])
    a_all = np.mean([b.s_audio[k]["energy"] for k in idx])
    if a_first - a_all > 0.2:
        h += 6; ex["hook"].append("energetic delivery at the start")
    if f0["weak_open"] > 0:
        h -= 22 * min(1.5, f0["weak_open"]); ex["hook"].append("starts with a filler/connective which weakens the opening")
    h -= 40 * f0["filler_ratio"]
    hook = clamp(h)

    # ---- story completeness
    topics = [b.topic_ids[k] for k in idx] if b.topic_ids else [0]
    dom = max(set(topics), key=topics.count)
    topic_frac = topics.count(dom) / len(topics)
    sims = b.adj_sim[i:j] if len(b.adj_sim) else np.zeros(0)
    cohesion = float(np.clip(np.mean(sims) / 0.15, 0, 1)) if len(sims) else 0.5
    third = max(1, (j - i + 1) // 3)
    setup = any(F[k]["question"] or F[k]["story"] > 0 or F[k]["hook"] > 0 for k in range(i, i + third))
    payoff = any(F[k]["conclusion"] > 0 or F[k]["advice"] > 0 or F[k]["exclaim"] for k in range(j - third + 1, j + 1))
    st = 100 * (0.3 * b.start_q[i] + 0.3 * b.end_q[j] + 0.18 * topic_frac + 0.1 * cohesion + 0.06 * setup + 0.06 * payoff)
    if b.start_notes[i]:
        ex["story"].append("start " + ", ".join(b.start_notes[i][:2]))
    if b.end_notes[j]:
        ex["story"].append("end " + ", ".join(b.end_notes[j][:2]))
    ex["story"].append(f"{topic_frac:.0%} of sentences stay on one topic")
    if setup and payoff:
        ex["story"].append("has a setup and a payoff")
    story = clamp(st)

    # ---- engagement
    turns = sum(1 for k in range(i + 1, j + 1) if S[k].get("speaker") != S[k - 1].get("speaker"))
    rate = nw / max(1.0, float(sum(b.s_speech[k] for k in idx)) or D)
    questions = sum(1 for k in idx if F[k]["question"])
    laugh = float(b.s_laugh[i:j + 1].max()) if j >= i else 0.0
    evar = float(np.mean([b.s_audio[k]["energy_var"] for k in idx]))
    en = 30.0
    if b.num_speakers > 1 and 1 <= turns <= 8:
        en += 14; ex["engagement"].append(f"back-and-forth between speakers ({turns} turns)")
    en += min(12, questions * 4)
    if questions:
        ex["engagement"].append(f"{questions} question(s)")
    en += min(8, sum(1 for k in idx if F[k]["exclaim"]) * 3)
    if 2.2 <= rate <= 3.8:
        en += 12; ex["engagement"].append(f"lively speaking pace ({rate:.1f} words/s)")
    elif rate < 1.6:
        en -= 8; ex["engagement"].append("slow pace")
    en += 10 * min(1.0, evar / 0.9)
    if laugh > 0:
        en += 12 * laugh; ex["engagement"].append("possible laughter detected")
    en += 8 * sat(sum(F[k]["humor"] for k in idx), 1.0)
    filler = sum(F[k]["filler_ratio"] * F[k]["n_words"] for k in idx) / nw
    en -= 60 * filler
    if filler > 0.05:
        ex["engagement"].append(f"{filler:.0%} filler words")
    engagement = clamp(en)

    # ---- emotion
    mags = [F[k]["sent_mag"] for k in idx]
    emo_lex = sum(F[k]["emotion"] for k in idx)
    excite = float(np.mean([b.s_audio[k]["excitement"] for k in idx]))
    exc_max = float(max(b.s_audio[k]["excitement_max"] for k in idx))
    em = 100 * (0.35 * float(np.mean(mags)) + 0.2 * float(max(mags)) + 0.2 * sat(emo_lex / max(1, (j - i + 1) / 4), 1.0)
                + 0.15 * float(np.clip((excite + 0.3) / 1.0, 0, 1)) + 0.1 * float(np.clip(exc_max / 2.0, 0, 1)))
    if emo_lex:
        ex["emotion"].append("emotionally charged language")
    if np.mean(mags) > 0.4:
        ex["emotion"].append("strong sentiment throughout")
    if exc_max > 1.2:
        ex["emotion"].append("vocal intensity peaks")
    if not ex["emotion"]:
        ex["emotion"].append("calm, neutral delivery")
    emotion = clamp(em)

    # ---- information value
    nums = sum(F[k]["numbers"] for k in idx)
    edu = sum(F[k]["education"] for k in idx)
    adv = sum(F[k]["advice"] for k in idx)
    lexd = sum(F[k]["lexical_density"] * F[k]["n_words"] for k in idx) / nw
    kwd = float(b.s_kw[i:j + 1].sum()) / nw
    inf = 100 * (0.25 * sat(nums / max(1, D / 30), 1.2) + 0.25 * sat(edu / max(1, D / 30), 1.5) + 0.2 * sat(adv / max(1, D / 30), 1.0)
                 + 0.15 * float(np.clip((lexd - 0.3) / 0.25, 0, 1)) + 0.15 * float(np.clip(kwd / 0.08, 0, 1)))
    if nums:
        ex["information"].append(f"{nums} concrete figure(s)")
    if edu:
        ex["information"].append("explains causes/evidence")
    if adv:
        ex["information"].append("gives actionable advice")
    if not ex["information"]:
        ex["information"].append("limited factual content")
    information = clamp(inf)

    # ---- standalone context
    sa = 72.0
    if f0["weak_open"] > 0:
        sa -= 22 * min(1.5, f0["weak_open"]); ex["standalone"].append("first sentence depends on prior context")
    refs = sum(F[k]["reference_back"] for k in idx)
    if refs:
        sa -= min(30, 15 * refs); ex["standalone"].append("refers back to earlier parts of the video")
    if i in set(b.topic_bounds):
        sa += 14; ex["standalone"].append("starts exactly at a topic boundary")
    if b.s_kw[i:min(j + 1, i + 2)].sum() > 0:
        sa += 8; ex["standalone"].append("introduces its subject early")
    sa += 10 * (topic_frac - 0.6)
    if b.end_q[j] < 0.4:
        sa -= 12; ex["standalone"].append("ending feels unfinished")
    if not ex["standalone"]:
        ex["standalone"].append("understandable on its own")
    standalone = clamp(sa)

    # ---- audio / visual quality
    speech_cov = float(sum(b.s_speech[k] for k in idx)) / D
    conf = sum(F[k]["asr_conf"] * F[k]["n_words"] for k in idx) / nw
    face = float(np.mean(b.s_face[i:j + 1])) if b.has_video and len(b.s_face) else 1.0
    gaps = sum(1 for k in range(i + 1, j + 1) if S[k].get("pause_before", 0) > 2.0)
    av = 100 * (0.35 * float(np.clip(speech_cov / 0.75, 0, 1)) + 0.3 * float(np.clip((conf - 0.5) / 0.4, 0, 1)) + 0.25 * face + 0.1) - 6 * gaps
    ex["av_quality"].append(f"speech covers {min(1.0, speech_cov):.0%} of the clip")
    ex["av_quality"].append(f"transcription confidence {conf:.0%}")
    if b.has_video:
        ex["av_quality"].append(f"face visible in {face:.0%} of sampled frames")
    if gaps:
        ex["av_quality"].append(f"{gaps} long pause(s)")
    av_quality = clamp(av)

    scores = {"hook": hook, "story": story, "engagement": engagement, "emotion": emotion, "information": information,
              "standalone": standalone, "av_quality": av_quality}
    total = weighted_total(scores, weights)

    # categories
    humor = sum(F[k]["humor"] for k in idx) + 2 * laugh
    qa = 0.0
    for k in range(i, j):
        if F[k]["question"] and S[k + 1].get("speaker") != S[k].get("speaker"):
            qa += 1
    cat_scores = {
        "funny": humor * 1.2,
        "emotional": (emotion - 45) / 15,
        "educational": (edu + nums * 0.6) / max(1, D / 30),
        "advice": adv * 1.2 / max(1, D / 30),
        "story": sum(F[k]["story"] for k in idx) / max(1, D / 30),
        "opinion": sum(F[k]["opinion"] for k in idx) * 0.8 / max(1, D / 30),
        "qa": qa * 0.9 / max(1, D / 30) if b.num_speakers > 1 else 0.0,
        "insight": 1.0,
    }
    category = max(cat_scores, key=cat_scores.get)
    return {"start": round(s0, 3), "end": round(s1, 3), "duration": round(D, 2), "i": i, "j": j, "score": round(total, 1),
            "scores": {k: round(v, 1) for k, v in scores.items()}, "explanations": {k: "; ".join(v) for k, v in ex.items()},
            "category": category, "cat_scores": {k: round(v, 2) for k, v in cat_scores.items()}}


def weighted_total(scores: dict[str, float], weights: dict[str, float]) -> float:
    tw = sum(max(0.0, float(weights.get(k, 0))) for k in DIMENSIONS) or 1.0
    return clamp(sum(scores[k] * max(0.0, float(weights.get(k, 0))) for k in DIMENSIONS) / tw)


# ------------------------------------------------------------------ text helpers
_FILLER_RX = re.compile(r"\b(um+|uh+|erm|you know,?|i mean,?|like,)\s*", re.I)
_LEAD_RX = re.compile(r"^(so|and|but|well|okay|ok|yeah|yes|right|now|anyway|also)[,\s]+", re.I)


def clean_text(t: str) -> str:
    t = _FILLER_RX.sub("", t).strip()
    for _ in range(3):
        t2 = _LEAD_RX.sub("", t).strip()
        if t2 == t:
            break
        t = t2
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(\d)\s+%", r"\1%", t)
    t = re.sub(r"\b(\w+)( \1\b)+", r"\1", t, flags=re.I)  # "perhaps perhaps" -> "perhaps"
    return t[:1].upper() + t[1:] if t else t


def make_title(b: Bundle, i: int, j: int, exclude: set[str] | None = None) -> str:
    cands = []
    for k in range(i, j + 1):
        f, s = b.feats[k], b.sentences[k]
        q = f["hook"] * 1.0 + f["sent_mag"] + f["opinion"] * 0.4 + f["conclusion"] * 0.4 + min(f["numbers"], 2) * 0.3
        q += 1.0 if 6 <= f["n_words"] <= 16 else (-0.5 if f["n_words"] > 26 else 0)
        q -= f["weak_open"] * 0.6 + f["filler_ratio"] * 3 + f["reference_back"]
        q -= 0.03 * (k - i)  # prefer earlier
        cands.append((q, s["text"]))
    cands.sort(key=lambda x: -x[0])
    exclude = exclude or set()
    title = ""
    for _, text in cands or [(0, b.sentences[i]["text"])]:
        title = _format_title(text)
        if title.lower() not in exclude:
            break
    return title


def _format_title(text: str) -> str:
    t = clean_text(text)
    t = t.rstrip(".,;:!…")
    if len(t) > 72:
        t = t[:72].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return semantic.title_case(t)


def make_hook(b: Bundle, i: int, j: int) -> str:
    txt = b.sentences[i]["text"]
    if len(txt) < 40 and i + 1 <= j:
        txt += " " + b.sentences[i + 1]["text"]
    return txt if len(txt) <= 160 else txt[:157].rsplit(" ", 1)[0] + "…"


def make_description(b: Bundle, i: int, j: int, category: str, duration: float) -> str:
    kw = set(b.keywords[:40])
    ranked = sorted(range(i, j + 1), key=lambda k: -(sum(1 for t in semantic.tokens(b.sentences[k]["text"]) if t in kw)
                                                      + b.feats[k]["conclusion"] + b.feats[k]["advice"]))
    picks = sorted(ranked[:2])
    body = " ".join(clean_text(b.sentences[k]["text"]) for k in picks)
    if len(body) > 230:
        body = body[:227].rsplit(" ", 1)[0] + "…"
    return f"{CATEGORY_LABELS.get(category, 'Insight')} moment ({duration:.0f}s): {body}"


def make_reason(c: dict[str, Any], weights: dict[str, float]) -> str:
    contrib = sorted(DIMENSIONS, key=lambda d: -(c["scores"][d] - 50) * max(1, weights.get(d, 1)))
    parts = []
    for d in contrib[:3]:
        if c["scores"][d] >= 55:
            parts.append(f"{DIM_LABELS[d]} {c['scores'][d]:.0f}: {c['explanations'][d].split(';')[0]}")
    weakest = min(DIMENSIONS, key=lambda d: c["scores"][d])
    txt = "; ".join(parts) if parts else "Best available boundaries for this duration in a lower-energy section"
    return f"{txt}. Weakest: {DIM_LABELS[weakest]} ({c['scores'][weakest]:.0f})."


# ------------------------------------------------------------------ discovery
def overlap_ratio(a: dict, b: dict) -> float:
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    return inter / max(1e-6, min(a["end"] - a["start"], b["end"] - b["start"]))


def iou(a: dict, b: dict) -> float:
    inter = max(0.0, min(a["end"], b["end"]) - max(a["start"], b["start"]))
    union = max(a["end"], b["end"]) - min(a["start"], b["start"])
    return inter / max(1e-6, union)


def windows_for(b: Bundle, lo: float, hi: float, min_start_q: float, min_end_q: float) -> list[tuple[int, int]]:
    S = b.sentences
    out = []
    n = len(S)
    for i in range(n):
        if b.start_q[i] < min_start_q:
            continue
        for j in range(i, n):
            d = S[j]["e"] - S[i]["s"]
            if d > hi:
                break
            if d >= lo and b.end_q[j] >= min_end_q:
                out.append((i, j))
    return out


def clip_text(b: Bundle, i: int, j: int) -> str:
    return " ".join(b.sentences[k]["text"] for k in range(i, j + 1))


def discover(b: Bundle, targets: list[float], tolerance: float = 0.2, weights: dict[str, float] | None = None,
             max_per_target: int = 8, preferences: dict[str, Any] | None = None, progress=None) -> list[dict[str, Any]]:
    weights = weights or DEFAULT_WEIGHTS
    prefs = preferences or {}
    want_cats = set(prefs.get("categories") or [])
    min_score = float(prefs.get("min_score") or 0)
    if not b.sentences:
        return []
    if not len(b.start_q):
        prepare(b)
    results: list[dict[str, Any]] = []
    target_list = sorted(set(float(t) for t in targets if t and t > 0))
    per_target: dict[float, list[dict[str, Any]]] = {}
    for ti, T in enumerate(target_list):
        lo, hi = max(5.0, T * (1 - tolerance)), T * (1 + tolerance)
        wins = windows_for(b, lo, hi, 0.45, 0.45)
        if len(wins) < 4 * max_per_target:
            wins = list(set(wins) | set(windows_for(b, lo, hi, 0.25, 0.3)))
        fits = True
        if not wins:
            wins = windows_for(b, lo, hi * 1.4, 0.15, 0.2)
            fits = False
        if not wins and b.sentences:
            # video shorter than target: whole transcript as single candidate
            wins = [(0, len(b.sentences) - 1)]
            fits = False
        scored = []
        seen_pairs: set[tuple[int, int]] = set()
        S = b.sentences
        for (i, j) in wins:
            # Snap unfinished / mid-utterance boundaries to complete sentences within allowed duration
            if b.end_q[j] < 0.45:
                for j2 in (j + 1, j + 2):
                    if j2 < len(S) and S[j2]["e"] - S[i]["s"] <= (hi if fits else hi * 1.4) and b.end_q[j2] > b.end_q[j] + 0.12:
                        j = j2
                        break
            if i > 0 and b.start_q[i] < 0.35:
                for i2 in (i - 1, i - 2):
                    if i2 >= 0 and S[j]["e"] - S[i2]["s"] <= (hi if fits else hi * 1.4) and b.start_q[i2] > b.start_q[i] + 0.15:
                        i = i2
                        break
            if (i, j) in seen_pairs:
                continue
            seen_pairs.add((i, j))
            c = score_window(b, i, j, weights)
            c["fits_duration"] = fits and lo <= c["duration"] <= hi
            if want_cats and c["category"] not in want_cats:
                c["score"] = round(c["score"] * 0.85, 1)
            # mild preference for durations close to the target
            c["_rank"] = c["score"] - 6.0 * abs(c["duration"] - T) / max(1.0, T)
            c["target_duration"] = T
            scored.append(c)
        scored.sort(key=lambda c: -c["_rank"])
        per_target[T] = [c for c in scored if c["score"] >= min_score]
        if progress:
            progress((ti + 1) / max(1, len(target_list)) * 0.8)

    # Round-robin selection across duration targets so every target gets its best moments, while suppressing
    # near-duplicates both within a target (overlap / transcript similarity) and across targets (same opening
    # line, or mostly the same span). A cross-target repeat is only allowed if that target would otherwise
    # have fewer than two recommendations.
    chosen_by: dict[float, list[dict[str, Any]]] = {T: [] for T in target_list}
    cursor = {T: 0 for T in target_list}
    texts: dict[int, str] = {}
    deferred: dict[float, list[dict[str, Any]]] = {}

    def txt_of(c):
        k = id(c)
        if k not in texts:
            texts[k] = clip_text(b, c["i"], c["j"])
        return texts[k]

    active = True
    while active:
        active = False
        for T in target_list:
            if len(chosen_by[T]) >= max_per_target:
                continue
            lst = per_target[T]
            while cursor[T] < len(lst):
                c = lst[cursor[T]]
                cursor[T] += 1
                same = any(overlap_ratio(c, o) > 0.35 or semantic.clip_text_similarity(txt_of(c), txt_of(o)) > 0.5
                           for o in chosen_by[T])
                if same:
                    continue
                cross = any(abs(c["start"] - o["start"]) < 2.5 or iou(c, o) > 0.6
                            for U, os_ in chosen_by.items() if U != T for o in os_)
                if cross:
                    deferred.setdefault(T, []).append(c)
                    continue
                c["_text"] = txt_of(c)
                chosen_by[T].append(c)
                active = True
                break
    # targets that would end up (nearly) empty may reuse a moment chosen for another duration
    for T in target_list:
        for c in deferred.get(T, []):
            if len(chosen_by[T]) >= 2:
                break
            if any(overlap_ratio(c, o) > 0.35 for o in chosen_by[T]):
                continue
            c["_text"] = txt_of(c)
            chosen_by[T].append(c)
    for T in target_list:
        results.extend(chosen_by[T])
    final = sorted(results, key=lambda c: -c["score"])
    used_titles: set[str] = set()
    for c in final:
        i, j = c["i"], c["j"]
        c["title"] = make_title(b, i, j, used_titles)
        used_titles.add(c["title"].lower())
        c["hook"] = make_hook(b, i, j)
        c["description"] = make_description(b, i, j, c["category"], c["duration"])
        c["reason"] = make_reason(c, weights)
        c["transcript"] = c.pop("_text")
        c["speakers"] = sorted({int(b.sentences[k].get("speaker", 0)) for k in range(i, j + 1)})
        c.pop("_rank", None)
    assign_tags(final)
    return final


def assign_tags(clips: list[dict[str, Any]]) -> None:
    if not clips:
        return
    for c in clips:
        c["tags"] = []
    by = sorted(clips, key=lambda c: -c["score"])
    for k, c in enumerate(by):
        c["rank"] = k + 1
    by[0]["tags"].append("best_overall")
    rules = {
        "highest_hook": lambda c: c["scores"]["hook"],
        "best_story": lambda c: c["scores"]["story"],
        "most_informative": lambda c: c["scores"]["information"],
        "most_emotional": lambda c: c["scores"]["emotion"],
        "best_standalone": lambda c: c["scores"]["standalone"],
        "funniest": lambda c: c["cat_scores"].get("funny", 0),
    }
    for tag, key in rules.items():
        top = max(clips, key=key)
        if tag == "funniest" and key(top) <= 0.5:
            continue
        top["tags"].append(tag)


def sentence_range(b: Bundle, start: float, end: float) -> tuple[int, int]:
    S = b.sentences
    i = min(range(len(S)), key=lambda k: abs(S[k]["s"] - start))
    j = min(range(len(S)), key=lambda k: abs(S[k]["e"] - end))
    if j < i:
        j = i
    return i, j


def score_range(b: Bundle, start: float, end: float, weights: dict[str, float] | None = None) -> dict[str, Any]:
    """Score an arbitrary (user-edited) range by snapping to the nearest sentence boundaries."""
    if not len(b.start_q):
        prepare(b)
    i, j = sentence_range(b, start, end)
    c = score_window(b, i, j, weights)
    c["reason"] = make_reason(c, weights or DEFAULT_WEIGHTS)
    return c


def alternatives(b: Bundle, start: float, end: float, target: float, tolerance: float, weights: dict[str, float] | None,
                 exclude: list[tuple[float, float]]) -> dict[str, Any] | None:
    """Find the best alternative boundaries covering the same moment (used by 'Regenerate')."""
    if not len(b.start_q):
        prepare(b)
    ref = {"start": start, "end": end}
    lo, hi = max(5.0, target * (1 - tolerance)), target * (1 + tolerance)
    best = None
    for (i, j) in windows_for(b, lo, hi * 1.1, 0.25, 0.3):
        cand = {"start": b.sentences[i]["s"], "end": b.sentences[j]["e"]}
        ov = iou(cand, ref)
        if ov < 0.25 or any(abs(cand["start"] - a) < 0.5 and abs(cand["end"] - z) < 0.5 for a, z in exclude):
            continue
        c = score_window(b, i, j, weights)
        rk = c["score"] + 5 * ov
        if best is None or rk > best[0]:
            best = (rk, c)
    if not best:
        return None
    c = best[1]
    i, j = c["i"], c["j"]
    c["title"] = make_title(b, i, j)
    c["hook"] = make_hook(b, i, j)
    c["description"] = make_description(b, i, j, c["category"], c["duration"])
    c["reason"] = make_reason(c, weights or DEFAULT_WEIGHTS)
    c["transcript"] = clip_text(b, i, j)
    c["speakers"] = sorted({int(b.sentences[k].get("speaker", 0)) for k in range(i, j + 1)})
    c["fits_duration"] = lo <= c["duration"] <= hi
    return c
