"""Integration test for full video rendering pipeline."""

import os
import tempfile
import subprocess
import pytest
from core.ffmpeg_manager import get_ffmpeg_paths
from core.tts import generate_speech_with_timings
from core.subtitles import generate_karaoke_ass
from core.title_card import generate_reddit_title_card
from core.composer import render_short_video
from core.gameplay import probe_video_metadata


def create_mock_gameplay_clip(output_path: str, duration: int = 6) -> str:
    """Create a temporary 1080p MP4 clip with test pattern and beep audio for integration testing."""
    ffmpeg_cmd, _ = get_ffmpeg_paths()
    cmd = [
        ffmpeg_cmd,
        "-y",
        "-f", "lavfi",
        "-i", f"testsrc=duration={duration}:size=1920x1080:rate=30",
        "-f", "lavfi",
        "-i", f"sine=frequency=440:duration={duration}",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-c:a", "aac",
        output_path,
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return output_path


@pytest.mark.asyncio
async def test_full_pipeline_render():
    with tempfile.TemporaryDirectory() as tmpdir:
        mock_gameplay = os.path.join(tmpdir, "mock_gameplay.mp4")
        voice_mp3 = os.path.join(tmpdir, "voice.mp3")
        subtitles_ass = os.path.join(tmpdir, "subtitles.ass")
        title_card_png = os.path.join(tmpdir, "card.png")
        final_mp4 = os.path.join(tmpdir, "final_short.mp4")

        # 1. Create mock gameplay
        create_mock_gameplay_clip(mock_gameplay, duration=8)
        assert os.path.exists(mock_gameplay)

        # 2. Generate TTS speech and timings
        tts_res = await generate_speech_with_timings(
            text="Testing video rendering pipeline with captions.",
            output_path=voice_mp3,
        )
        assert os.path.exists(tts_res.audio_path)
        assert tts_res.duration > 0.5

        # 3. Generate subtitles
        generate_karaoke_ass(tts_res.words, subtitles_ass)
        assert os.path.exists(subtitles_ass)

        # 4. Generate title card
        generate_reddit_title_card(
            subreddit="r/AmItheAsshole",
            author="IntegrationTest",
            title="Testing pipeline rendering",
            score=9999,
            num_comments=450,
            output_path=title_card_png,
        )
        assert os.path.exists(title_card_png)

        # 5. Composite video
        progress_records = []
        out = render_short_video(
            gameplay_path=mock_gameplay,
            voice_path=voice_mp3,
            subtitles_path=subtitles_ass,
            output_path=final_mp4,
            duration=tts_res.duration,
            title_card_path=title_card_png,
            title_card_duration=2.0,
            progress_callback=lambda p: progress_records.append(p),
        )

        assert os.path.exists(out)
        assert os.path.getsize(out) > 5000
        assert len(progress_records) > 0
        assert progress_records[-1] == 100.0

        # 6. Probe final video properties
        meta = probe_video_metadata(out)
        assert meta["width"] == 1080
        assert meta["height"] == 1920
        assert meta["duration"] > 0.5
