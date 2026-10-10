"""Unit tests for ASS and SRT subtitle generators."""

import os
import tempfile
import pytest
from core.tts import WordTiming
from core.subtitles import (
    format_ass_timestamp,
    format_srt_timestamp,
    generate_karaoke_ass,
    generate_srt_subtitles,
    group_speech_words,
)


def test_timestamp_formatting():
    # 65.45 seconds = 1 minute, 5 seconds, 45 centiseconds
    assert format_ass_timestamp(65.45) == "0:01:05.45"
    assert format_srt_timestamp(65.45) == "00:01:05,450"

    # Edge cases
    assert format_ass_timestamp(0.0) == "0:00:00.00"
    assert format_srt_timestamp(0.0) == "00:00:00,000"
    assert format_ass_timestamp(59.999) == "0:01:00.00"
    assert format_srt_timestamp(59.9999) == "00:01:00,000"


def test_generate_karaoke_ass():
    words = [
        WordTiming(word="I", start=0.0, end=0.3),
        WordTiming(word="could", start=0.3, end=0.7),
        WordTiming(word="not", start=0.7, end=1.0),
        WordTiming(word="believe", start=1.0, end=1.5),
        WordTiming(word="my", start=1.5, end=1.8),
        WordTiming(word="eyes", start=1.8, end=2.2),
    ]

    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False) as tf:
        out_path = tf.name

    try:
        ass_file = generate_karaoke_ass(words, out_path, words_per_group=3)
        assert os.path.exists(ass_file)

        with open(ass_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert "[Script Info]" in content
        assert "PlayResX: 1080" in content
        assert "PlayResY: 1920" in content
        assert "[V4+ Styles]" in content
        assert "[Events]" in content

        # Check karaoke color tags
        assert r"{\c&H0000E6FF&}" in content  # Yellow highlight
        assert r"{\c&H00FFFFFF&}" in content  # White inactive
        assert "I" in content
        assert "COULD" in content
        assert "BELIEVE" in content
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)


def test_generate_srt_subtitles():
    words = [
        WordTiming(word="Hello", start=0.0, end=0.5),
        WordTiming(word="world", start=0.5, end=1.0),
    ]
    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as tf:
        out_path = tf.name

    try:
        srt_file = generate_srt_subtitles(words, out_path)
        assert os.path.exists(srt_file)

        with open(srt_file, "r", encoding="utf-8") as f:
            content = f.read()

        assert "00:00:00,000 --> 00:00:01,000" in content
        assert "Hello world" in content
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)


def test_phrase_groups_follow_sentence_ends_and_long_pauses():
    words = [WordTiming("Hello.", 0, .3), WordTiming("He", .5, .7),
             WordTiming("left", 1.2, 1.5), WordTiming("today.", 1.55, 1.9)]
    groups = group_speech_words(words)
    assert [[w.word for w in group] for group in groups] == [["Hello."], ["He"], ["left", "today."]]


def test_highlights_end_with_speech_and_do_not_span_pauses(tmp_path):
    words = [WordTiming("He", 0, .2), WordTiming("was", .3, .5),
             WordTiming("gr*ped.", 1.2, 1.6)]
    path = tmp_path / "speech.ass"
    generate_karaoke_ass(words, str(path))
    events = [line for line in path.read_text().splitlines() if line.startswith("Dialogue:")]
    highlighted = [line for line in events if r"{\c&H0000E6FF&}" in line]
    assert [line.split(',')[1:3] for line in highlighted] == [
        ["0:00:00.00", "0:00:00.20"], ["0:00:00.30", "0:00:00.50"], ["0:00:01.20", "0:00:01.60"]]
    assert "GR*PED." not in highlighted[0]
    assert any(",0:00:00.20,0:00:00.30," in line and r"{\c" not in line for line in events)
    srt = tmp_path / "speech.srt"
    generate_srt_subtitles(words, str(srt))
    assert "00:00:00,000 --> 00:00:00,500" in srt.read_text()
    assert "00:00:01,200 --> 00:00:01,600" in srt.read_text()
