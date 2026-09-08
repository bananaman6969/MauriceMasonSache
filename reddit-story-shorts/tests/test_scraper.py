"""Unit tests for Reddit scraper and story text cleaner."""

import pytest
from core.scraper import clean_story_text, parse_post_dict, estimate_duration_seconds


def test_clean_story_text_expands_acronyms():
    raw = "AITA for telling my SIL that she is acting like an entitled person? TL;DR: She threw a fit."
    cleaned = clean_story_text(raw)
    assert "Am I the asshole" in cleaned
    assert "sister in law" in cleaned
    assert "In summary" in cleaned
    assert "AITA" not in cleaned


def test_clean_story_text_strips_markdown_and_urls():
    raw = "Check this [photo](https://example.com/img.png) and visit https://google.com for more."
    cleaned = clean_story_text(raw)
    assert cleaned == "Check this photo and visit for more."


def test_estimate_duration_seconds():
    # 150 words at 150 wpm = 60 seconds
    assert estimate_duration_seconds(150, 150) == 60.0
    assert estimate_duration_seconds(0) == 0.0


def test_parse_post_dict_valid():
    raw_post = {
        "id": "abc123",
        "title": "AITA for leaving my cousin's wedding?",
        "selftext": "So my cousin invited everyone except my dog. NTA or YTA?",
        "author": "storyteller99",
        "subreddit": "AmItheAsshole",
        "score": 4500,
        "num_comments": 820,
        "permalink": "/r/AmItheAsshole/comments/abc123/aita_for_leaving/",
        "url": "https://reddit.com/r/AmItheAsshole/comments/abc123/aita_for_leaving/",
        "over_18": False,
        "stickied": False,
    }
    parsed = parse_post_dict(raw_post)
    assert parsed is not None
    assert parsed["id"] == "abc123"
    assert "Am I the asshole" in parsed["title"]
    assert "Not the asshole" in parsed["body"]
    assert parsed["score"] == 4500
    assert parsed["subreddit"] == "r/AmItheAsshole"
    assert parsed["word_count"] > 0
    assert parsed["est_duration_seconds"] > 0


def test_parse_post_dict_ignores_stickied():
    raw_post = {
        "id": "stickied1",
        "title": "Monthly Discussion",
        "selftext": "Welcome to the thread",
        "stickied": True,
    }
    assert parse_post_dict(raw_post) is None
