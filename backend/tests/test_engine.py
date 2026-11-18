"""Unit tests: caption timing / ASS generation, clip scoring, candidate ranking, duplicate suppression,
renderer planning, audio settings, security helpers."""
from pathlib import Path

import numpy as np
import pytest

from app.services import captions, discovery, renderer, reframe, segmentation, semantic
from app.security import SecurityError, safe_join, sanitize_filename, validate_youtube_url
from tests.conftest import make_words

STORY = (
    "Here's the thing most people get wrong about sleep. They think eight hours is a magic number. "
    "But the research says something different. In one study of 10,000 people, consistency mattered more than duration. "
    "So the lesson is simple. Go to bed at the same time every night. "
)
FILLER = "and um so yeah it was like you know whatever. and then it was fine I guess. "


def _bundle(text: str, repeats: int = 1, gap: float = 0.8) -> discovery.Bundle:
    words = []
    t = 0.0
    for _ in range(repeats):
        for w in make_words(text, start=t):
            words.append(w)
        t = words[-1]["e"] + gap
    sents = segmentation.build_sentences(words)
    b = discovery.Bundle(duration=words[-1]["e"], words=words, sentences=sents, has_video=False)
    return discovery.prepare(b)


# ---------------------------------------------------------------- captions
def test_caption_items_use_only_real_words():
    words = make_words("hello world this is a caption test with real words only")
    items = captions.build_items(words, 0, 100, words_per_caption=3)
    joined = " ".join(it["text"] for it in items)
    assert joined == " ".join(w["w"] for w in words)
    assert all(len(it["words"]) <= 3 for it in items)
    for a, b in zip(items, items[1:]):
        assert a["end"] <= b["start"] + 1e-6  # never overlap


def test_caption_retiming_after_edit():
    it = {"start": 1.0, "end": 2.0, "text": "hello world", "words": [{"w": "hello", "s": 1.0, "e": 1.4}, {"w": "world", "s": 1.5, "e": 2.0}]}
    assert captions.retime_words(it)[1]["s"] == 1.5
    it["text"] = "hi there big world"
    ws = captions.retime_words(it)
    assert len(ws) == 4 and ws[0]["s"] == 1.0 and ws[-1]["e"] == pytest.approx(2.0)


def test_ass_generation_maps_time_through_cuts():
    words = make_words("one two three four five six seven eight", gap_after={3: 2.0})
    items = captions.build_items(words, 0, 20, words_per_caption=4)
    segs = segmentation.keep_segments(0, words[-1]["e"], [{"s": words[3]["e"] + 0.1, "e": words[4]["s"] - 0.1}])
    for sid in captions.CAPTION_STYLES:
        ass = captions.build_ass(items, captions.style_for(sid), 1080, 1920, segs, {"five"})
        assert "[Events]" in ass and "Dialogue:" in ass
        assert "PlayResX: 1080" in ass
    ass = captions.build_ass(items, captions.style_for("clean_minimal"), 1080, 1920, segs)
    lines = [l for l in ass.splitlines() if l.startswith("Dialogue")]
    # second caption starts right after the cut in output time (~1.4s), not at its source time (~3.4s)
    start2 = lines[1].split(",")[1]
    h, m, s = start2.split(":")
    assert float(s) < 2.0


def test_hex_to_ass():
    assert captions.hex_to_ass("#FF0000") == "&H000000FF"
    assert captions.hex_to_ass("#00FF00", 0.5) == "&H8000FF00"
    assert captions.hex_to_ass("garbage") == "&H00FFFFFF"


# ---------------------------------------------------------------- scoring / ranking
def test_scores_in_range_and_weighted_total():
    b = _bundle(STORY + FILLER, repeats=4)
    c = discovery.score_window(b, 0, 5)
    assert set(c["scores"]) == set(discovery.DIMENSIONS)
    assert all(0 <= v <= 100 for v in c["scores"].values())
    assert 0 <= c["score"] <= 100
    w = {k: 0 for k in discovery.DIMENSIONS}
    w["hook"] = 1
    assert discovery.weighted_total(c["scores"], w) == pytest.approx(c["scores"]["hook"])


def test_strong_story_beats_filler():
    b = _bundle(STORY + FILLER, repeats=3)
    S = b.sentences
    story_end = next(k for k, s in enumerate(S) if "every night" in s["text"])
    filler_start = story_end + 1
    filler_end = next(k for k, s in enumerate(S) if k > filler_start and "guess" in s["text"])
    good = discovery.score_window(b, 0, story_end)
    bad = discovery.score_window(b, filler_start, filler_end)
    assert good["score"] > bad["score"] + 10
    assert good["scores"]["hook"] > bad["scores"]["hook"]
    assert good["scores"]["story"] > bad["scores"]["story"]
    assert good["explanations"]["hook"]


def test_discover_respects_duration_and_dedupes():
    b = _bundle(STORY + FILLER, repeats=12)
    clips = discovery.discover(b, [20.0], tolerance=0.25, max_per_target=6)
    assert clips, "should find candidates"
    for c in clips:
        if c["fits_duration"]:
            assert 15.0 <= c["duration"] <= 25.0
        assert c["title"] and c["hook"] and c["reason"]
    for a in clips:
        for o in clips:
            if a is not o:
                assert discovery.overlap_ratio(a, o) <= 0.35 + 1e-6
    ranked = sorted(clips, key=lambda c: -c["score"])
    assert ranked[0]["rank"] == 1 and "best_overall" in ranked[0]["tags"]


def test_discover_marks_unfit_when_video_too_short():
    b = _bundle(STORY, repeats=1)
    clips = discovery.discover(b, [180.0], tolerance=0.1)
    assert clips and all(not c["fits_duration"] for c in clips)


def test_weak_start_penalized():
    b = _bundle("And then he said that. " + STORY, repeats=2)
    assert b.start_q[0] < b.start_q[1]


def test_text_similarity():
    assert semantic.clip_text_similarity("sleep research study", "sleep research study") == 1.0
    assert semantic.clip_text_similarity("sleep research", "football match") == 0.0


# ---------------------------------------------------------------- reframe / render plan
def test_crop_box_aspects():
    cw, ch = reframe.crop_box(1920, 1080, "9:16")
    assert ch == 1.0 and cw == pytest.approx((1080 * 9 / 16) / 1920)
    cw, ch = reframe.crop_box(1920, 1080, "16:9")
    assert cw == pytest.approx(1.0) and ch == pytest.approx(1.0)
    cw2, _ = reframe.crop_box(1920, 1080, "9:16", zoom=1.2)
    assert cw2 < cw or cw2 == pytest.approx(reframe.crop_box(1920, 1080, "9:16")[0] / 1.2)


def test_reframe_follows_face_smoothly():
    samples = [{"t": t / 2, "faces": [[0.3 if t < 20 else 0.7, 0.4, 0.1, 0.18, 0.9]], "motion": 1, "subject": [0.5, 0.5]} for t in range(40)]
    rf = reframe.compute(samples, [{"s": 0, "e": 20}], [], {}, 1920, 1080, "9:16", 0, 19.5)
    xs = [k["x"] for k in rf["keyframes"]]
    assert xs[0] == pytest.approx(0.3, abs=0.05)
    assert xs[-1] == pytest.approx(0.7, abs=0.08)
    # no jumps larger than the velocity limit allows between consecutive keyframes
    for a, b in zip(rf["keyframes"], rf["keyframes"][1:]):
        assert abs(b["x"] - a["x"]) <= 0.35 * (b["t"] - a["t"]) + 0.02


def test_build_pieces_splits_at_zoom():
    tl = {"start": 0, "end": 10, "cuts": [{"s": 4, "e": 5}], "zooms": [{"s": 6, "e": 8, "scale": 1.2}], "reframe": {"layouts": []}}
    pieces = renderer.build_pieces(tl)
    assert [(p["s"], p["e"], p["zoom"]) for p in pieces] == [(0, 4, 1.0), (5, 6, 1.0), (6, 8, 1.2), (8, 10, 1.0)]


def test_piecewise_expression():
    e = renderer._piecewise([(0, 10), (2, 20), (4, 20)])
    assert e.startswith("if(lt(t,2.000)")
    assert renderer._piecewise([(0, 5)]) == "5.00"


def test_render_plan_audio_settings(tmp_path: Path):
    tl = {"start": 0, "end": 10, "cuts": [], "zooms": [], "aspect": "9:16", "reframe": {"keyframes": [{"t": 0, "x": 0.5, "y": 0.5}]},
          "music": {"asset_id": "m1", "volume": 0.1, "fade_in": 1, "fade_out": 1, "ducking": True},
          "sfx": [{"asset_id": "s1", "t": 2.0, "volume": 0.4}],
          "audio": {"enhance_voice": True, "denoise": True, "loudness": -14, "voice_gain_db": 2},
          "export": {"resolution": "1080p", "fps": 30, "codec": "h264"}}
    src = {"path": "in.mp4", "width": 1920, "height": 1080, "has_video": True, "has_audio": True}
    p = renderer.plan(tl, {"id": "podcast_pro"}, [], src, tmp_path / "o.mp4", tmp_path, {"m1": "m.m4a", "s1": "s.m4a"}, set(), "off")
    graph = (tmp_path / "filter.txt").read_text()
    assert "sidechaincompress" in graph and "afftdn" in graph and "loudnorm=I=-14.0" in graph
    assert "adelay=2000|2000" in graph and "volume=2.0dB" in graph
    assert p["width"] == 1080 and p["height"] == 1920 and p["duration"] == pytest.approx(10)
    assert "-stream_loop" in p["cmd"]


# ---------------------------------------------------------------- security
def test_sanitize_filename():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename('a<b>c:"d|e?.mp4') == "a_b_c__d_e_.mp4"
    assert sanitize_filename("CON.mp4") == "_CON.mp4"
    assert sanitize_filename("") == "file"


def test_safe_join_blocks_traversal(tmp_path: Path):
    assert safe_join(tmp_path, "a", "b.txt") == (tmp_path / "a" / "b.txt").resolve()
    with pytest.raises(SecurityError):
        safe_join(tmp_path, "..", "evil")


def test_youtube_url_validation():
    assert validate_youtube_url("https://youtu.be/dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    assert validate_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5").endswith("dQw4w9WgXcQ")
    assert validate_youtube_url("https://youtube.com/shorts/dQw4w9WgXcQ").endswith("dQw4w9WgXcQ")
    for bad in ("ftp://youtube.com/watch?v=dQw4w9WgXcQ", "https://evil.com/watch?v=dQw4w9WgXcQ", "https://youtube.com/playlist?list=x",
                "https://youtube.com/watch?v=short"):
        with pytest.raises(SecurityError):
            validate_youtube_url(bad)


def test_collapsed_whisper_word_timestamps_never_break_captions_or_save():
    from app.schemas import CaptionsUpdate
    from app.services import transcription

    raw_words = [
        {"w": "Because", "s": 113.47, "e": 113.97, "p": 0.6},
        {"w": "I've", "s": 113.97, "e": 114.29, "p": 0.6},
        {"w": "also", "s": 114.29, "e": 114.31, "p": 0.1},
        {"w": "seen", "s": 114.29, "e": 114.31, "p": 0.9},
        {"w": "it.", "s": 114.29, "e": 114.35, "p": 0.5},
        {"w": "And", "s": 117.14, "e": 117.64, "p": 0.6},
    ]
    items = captions.build_items(raw_words, 113.0, 118.0, words_per_caption=2)
    assert len(items) >= 3
    for it in items:
        assert it["end"] >= it["start"] + 0.119
    for a, b in zip(items, items[1:]):
        assert a["end"] <= b["start"] + 1e-6
    upd = CaptionsUpdate(style=captions.style_for("podcast_pro"), items=items)
    assert len(upd.items) == len(items)
    fixed = transcription._fix_monotonic([dict(w) for w in raw_words], [{"s": 113.47, "e": 114.8, "w0": 0, "w1": 5}])
    assert all(fixed[k]["e"] > fixed[k]["s"] for k in range(len(fixed)))
    assert all(fixed[k + 1]["s"] >= fixed[k]["e"] - 1e-6 for k in range(len(fixed) - 1))


def test_silence_cuts_never_cut_inside_vad_speech_or_laughter():
    words = [
        {"w": "seen", "s": 114.0, "e": 114.35},
        {"w": "And", "s": 117.14, "e": 117.64},
    ]
    # Without VAD there is a 2.79s gap; with VAD showing speech across 114.3..117.2, zero cuts may occur inside speech
    vad = [{"s": 114.2, "e": 117.25}]
    cuts = segmentation.silence_cuts(words, 114.0, 118.0, min_silence=0.7, keep_pad=0.2, vad=vad)
    assert cuts == []


def test_discovery_penalizes_ellipsis_mid_vad_and_numpy_diarization():
    from app.services import diarization

    assert not segmentation.is_sentence_end("fucking...")
    assert not segmentation.is_sentence_end("wait…")
    # With a 0.1s gap, ellipsis does NOT prematurely split the sentence; with a 1.5s pause split, ellipsis is penalized as an ending
    words_joined = make_words("Wait let me tell you... Actually this is a complete point.", gap_after={4: 0.1})
    assert len(segmentation.build_sentences(words_joined)) == 1
    words = make_words("Wait let me tell you... Actually this is a complete point.", gap_after={4: 1.5})
    sents = segmentation.build_sentences(words)
    assert len(sents) == 2
    vad = [{"s": 0.0, "e": words[-1]["e"]}]
    b = discovery.prepare(discovery.Bundle(duration=words[-1]["e"], words=words, sentences=sents, vad=vad, has_video=False))
    assert b.end_q[1] > b.end_q[0]

    # Pure-NumPy Ward clustering separates two clear speaker clusters without sklearn Cython DLLs
    rng = np.random.default_rng(42)
    X = np.vstack([rng.normal(-2.0, 0.3, (20, 8)), rng.normal(2.0, 0.3, (20, 8))])
    labels = diarization._ward_cluster(X, 2)
    assert len(set(labels[:20])) == 1 and len(set(labels[20:])) == 1 and labels[0] != labels[20]


def test_hindi_hinglish_and_english_caption_pipeline():
    from app.services import hinglish, semantic, transcription

    # 1. Hinglish transliteration preserves English tokens while converting Devanagari with schwa deletion
    mixed = "भाई ये podcast बहुत सही बात है।"
    rom = hinglish.to_hinglish(mixed)
    assert not hinglish.has_devanagari(rom)
    assert "podcast" in rom
    assert rom.lower() == "bhai ye podcast bahut sahi baat hai."

    # 2. Devanagari purna viram sentence boundary + semantic tokenization
    assert segmentation.is_sentence_end("सही बात है।")
    sents = segmentation.build_sentences(make_words("नमस्ते दोस्तों। आज हम बात करेंगे।", gap_after={1: 0.2}))
    assert len(sents) == 2
    toks_hi = semantic.tokens("नमस्ते दोस्तों entrepreneurship कहानी")
    assert "entrepreneurship" in toks_hi and any(hinglish.has_devanagari(t) for t in toks_hi)
    X, vec = semantic.tfidf_matrix([{"text": "bhai yaar startup revenue growth sahi hai startup revenue"}])
    kws_hl = semantic.global_keywords(X, vec)
    assert "startup" in kws_hl and "revenue" in kws_hl and "bhai" not in kws_hl and "hai" not in kws_hl

    # 3. Devanagari ASS subtitle rendering automatically selects Nirmala UI instead of Latin-only Impact
    hi_items = [{"id": "c1", "start": 0.0, "end": 1.8, "text": "नमस्ते दोस्तों क्या हाल है", "words": []}]
    ass = captions.build_ass(hi_items, captions.style_for("bold_viral"), 1080, 1920, [(0.0, 2.0)])
    assert "Style: Default,Nirmala UI," in ass
    assert "नमस्ते दोस्तों क्या हाल है" in ass

    # 4. Language mode resolution covers Hinglish, Hindi Devanagari, English, and English translation
    assert transcription._resolve_lang_mode("hinglish")[:3] == ("hinglish", "hi", "transcribe") and transcription._resolve_lang_mode("hinglish")[4] is True
    assert transcription._resolve_lang_mode("hi")[:3] == ("hi", "hi", "transcribe") and transcription._resolve_lang_mode("hi")[4] is False
    assert transcription._resolve_lang_mode("en")[:3] == ("en", "en", "transcribe")
    assert transcription._resolve_lang_mode("en_translate")[:3] == ("en_translate", None, "translate")
    assert transcription._resolve_lang_mode("auto")[:3] == ("auto", None, "transcribe")

