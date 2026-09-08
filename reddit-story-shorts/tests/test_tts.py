"""Unit tests for edge-tts generation and timing extraction."""

import os
import tempfile
import pytest
from core.tts import generate_speech_with_timings, get_available_voices


@pytest.mark.asyncio
async def test_get_available_voices():
    voices = await get_available_voices(locale_prefix="en-US")
    assert len(voices) > 0
    voice_ids = [v["id"] for v in voices]
    assert any("Christopher" in vid or "Guy" in vid for vid in voice_ids)


@pytest.mark.asyncio
async def test_generate_speech_with_timings():
    test_text = "This is an automated test story."
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
        out_path = tf.name

    try:
        result = await generate_speech_with_timings(
            text=test_text,
            output_path=out_path,
            voice="en-US-ChristopherNeural",
        )
        assert os.path.exists(result.audio_path)
        assert os.path.getsize(result.audio_path) > 1000
        assert result.duration > 0.5
        assert len(result.words) >= 5
        # Verify first word
        assert result.words[0].word.lower().startswith("this")
        assert result.words[0].start >= 0.0
        assert result.words[0].end > result.words[0].start
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)
