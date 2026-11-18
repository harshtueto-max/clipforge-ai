"""Unit tests: timestamps, segmentation, time mapping, silence removal, duration validation."""
import pytest

from app.services import media, segmentation
from app.schemas import AnalyzeRequest, TimelineUpdate
from tests.conftest import make_words


def test_ts_and_parse_roundtrip():
    assert media.ts(0) == "00:00.000"
    assert media.ts(65.5) == "01:05.500"
    assert media.ts(3725.25) == "01:02:05.250"
    assert media.parse_ts("1:02:05.25") == pytest.approx(3725.25)
    assert media.parse_ts("02:03") == 123
    assert media.parse_ts("12.5") == 12.5
    with pytest.raises(ValueError):
        media.parse_ts("abc")


def test_sentence_end_detection():
    assert segmentation.is_sentence_end("done.")
    assert segmentation.is_sentence_end("really?")
    assert not segmentation.is_sentence_end("Dr.")
    assert not segmentation.is_sentence_end("e.g.")
    assert not segmentation.is_sentence_end("U.S.A.")
    assert not segmentation.is_sentence_end("hello,")


def test_build_sentences_punctuation_and_pause():
    words = make_words("This is the first sentence. And here is the second one without end", gap_after={})
    sents = segmentation.build_sentences(words)
    assert len(sents) == 2
    assert sents[0]["text"] == "This is the first sentence."
    assert sents[0]["w0"] == 0 and sents[0]["w1"] == 5
    # long pause forces a split
    words = make_words("one two three four five six", gap_after={2: 2.0})
    sents = segmentation.build_sentences(words)
    assert [s["text"] for s in sents] == ["one two three", "four five six"]
    assert sents[1]["pause_before"] >= 2.0


def test_build_sentences_run_on_is_capped():
    words = make_words(" ".join(["word"] * 120))
    sents = segmentation.build_sentences(words, max_words=45)
    assert all(s["w1"] - s["w0"] <= 90 for s in sents)
    assert sum(s["w1"] - s["w0"] for s in sents) == 120


def test_keep_segments_and_mapping():
    segs = segmentation.keep_segments(10.0, 20.0, [{"s": 12.0, "e": 13.0}, {"s": 15.0, "e": 16.5}])
    assert segs == [(10.0, 12.0), (13.0, 15.0), (16.5, 20.0)]
    assert segmentation.output_duration(segs) == pytest.approx(7.5)
    assert segmentation.source_to_output(10.0, segs) == 0.0
    assert segmentation.source_to_output(14.0, segs) == pytest.approx(3.0)
    assert segmentation.source_to_output(12.5, segs) is None  # inside a cut
    assert segmentation.output_to_source(3.0, segs) == pytest.approx(14.0)
    assert segmentation.output_to_source(6.0, segs) == pytest.approx(18.5)


def test_keep_segments_overlapping_and_out_of_range_cuts():
    segs = segmentation.keep_segments(0, 10, [{"s": -5, "e": 1}, {"s": 4, "e": 6}, {"s": 5, "e": 7}, {"s": 9.99, "e": 20}])
    assert segs == [(1.0, 4.0), (7.0, 9.99)]


def test_silence_cuts_preserve_speech():
    words = make_words("a b c d e f", gap_after={2: 1.5})
    cuts = segmentation.silence_cuts(words, 0.0, words[-1]["e"], min_silence=0.6, keep_pad=0.15)
    assert len(cuts) == 1
    c = cuts[0]
    # cut lies strictly between word c (index 2) and d (index 3), with padding
    assert c["s"] >= words[2]["e"] + 0.149
    assert c["e"] <= words[3]["s"] - 0.149
    segs = segmentation.keep_segments(0.0, words[-1]["e"], cuts)
    for w in words:
        assert segmentation.source_to_output((w["s"] + w["e"]) / 2, segs) is not None


def test_find_pauses():
    words = make_words("a b c", gap_after={0: 1.0})
    p = segmentation.find_pauses(words, 0.6)
    assert len(p) == 1 and p[0]["d"] >= 1.0


def test_duration_validation():
    assert AnalyzeRequest(duration_targets=[60, 30, 30]).duration_targets == [30.0, 60.0]
    with pytest.raises(ValueError):
        AnalyzeRequest(duration_targets=[2])
    with pytest.raises(ValueError):
        AnalyzeRequest(duration_targets=[10000])
    with pytest.raises(ValueError):
        TimelineUpdate(data={"start": 5, "end": 5.5})
    with pytest.raises(ValueError):
        TimelineUpdate(data={"start": 0, "end": 30, "cuts": [{"s": 5, "e": 4}]})
    with pytest.raises(ValueError):
        TimelineUpdate(data={"start": 0, "end": 30, "aspect": "2:1"})
    assert TimelineUpdate(data={"start": 0, "end": 30, "aspect": "9:16"}).data["end"] == 30
