"""Unit tests for title card generator."""

import os
import tempfile
from PIL import Image
from core.title_card import generate_reddit_title_card, format_score


def test_format_score():
    assert format_score(450) == "450"
    assert format_score(1500) == "1.5k"
    assert format_score(24500) == "24.5k"
    assert format_score(1500000) == "1.5M"


def test_generate_reddit_title_card():
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        out_path = tf.name

    try:
        card_file = generate_reddit_title_card(
            subreddit="r/AmItheAsshole",
            author="ThrowawayUser",
            title="AITA for refusing to give my sister my wedding dress?",
            score=18400,
            num_comments=2100,
            output_path=out_path,
        )
        assert os.path.exists(card_file)
        with Image.open(card_file) as img:
            assert img.format == "PNG"
            assert img.size[0] == 960
            assert img.size[1] > 100
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)
