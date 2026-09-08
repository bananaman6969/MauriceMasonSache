"""Unit tests for story splitter and multi-part generator."""

import pytest
from core.story_splitter import split_story_into_parts, split_text_into_sentences


def test_split_text_into_sentences():
    text = "Sentence one. Sentence two! Sentence three? Final sentence."
    sentences = split_text_into_sentences(text)
    assert len(sentences) == 4
    assert sentences[0] == "Sentence one."
    assert sentences[1] == "Sentence two!"
    assert sentences[2] == "Sentence three?"
    assert sentences[3] == "Final sentence."


def test_short_story_single_part():
    title = "AITA for telling my friend no?"
    body = "My friend asked for a ride. I told him no because I was busy. End of story."
    parts = split_story_into_parts(title, body, max_duration_seconds=60)
    assert len(parts) == 1
    assert parts[0]["part"] == 1
    assert parts[0]["total_parts"] == 1
    assert "Like and follow" not in parts[0]["script"]


def test_long_story_multi_part():
    title = "My dramatic vacation story"
    # Create ~150 words of body text
    body = " ".join([f"This is sentence number {i} describing the drama." for i in range(1, 25)])
    # Set max duration to 20 seconds (~50 words)
    parts = split_story_into_parts(title, body, max_duration_seconds=20, words_per_minute=150, add_cta=True)
    assert len(parts) > 1
    assert parts[0]["part"] == 1
    assert parts[0]["total_parts"] == len(parts)
    assert "Like and follow for part 2!" in parts[0]["script"]
    assert "Part 2" in parts[1]["part_title"]
