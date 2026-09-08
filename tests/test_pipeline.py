"""Tests for shorts-stealth-pipeline core modules."""

import os
import subprocess
import pytest
import pytest_asyncio
from core.ffmpeg_manager import get_ffmpeg_paths, verify_ffmpeg_binary
from core.processor import generate_random_params, build_filter_complex, process_video
from core.scraper import clean_query_term, extract_metadata_from_entry
import core.database as db


def test_ffmpeg_paths_and_verification():
    """Ensure FFmpeg is located and executable."""
    ffmpeg_path, ffprobe_path = get_ffmpeg_paths()
    assert os.path.exists(ffmpeg_path) or ffmpeg_path.lower().endswith(".exe")
    assert verify_ffmpeg_binary(ffmpeg_path) is True


def test_clean_query_term():
    """Verify query sanitization and shorts keyword inclusion."""
    assert clean_query_term("funny cats") == "#shorts funny cats"
    assert clean_query_term("tech #shorts") == "tech #shorts"
    assert clean_query_term("gaming shorts") == "gaming shorts"


def test_extract_metadata_from_entry():
    """Verify entry metadata parsing and duration filtering."""
    valid_entry = {
        "id": "abc12345",
        "title": "Amazing Trick",
        "uploader": "Trickster",
        "view_count": 500000,
        "like_count": 25000,
        "duration": 45,
    }
    parsed = extract_metadata_from_entry(valid_entry)
    assert parsed is not None
    assert parsed["id"] == "abc12345"
    assert parsed["views"] == 500000
    assert parsed["channel"] == "Trickster"

    long_entry = {
        "id": "longvideo",
        "duration": 180,
    }
    assert extract_metadata_from_entry(long_entry) is None


def test_processor_params_and_filters():
    """Verify perturbation parameters generation and filter graph construction."""
    params = generate_random_params(preset="subtle", mirror=True)
    assert 1.01 <= params["speed"] <= 1.03
    assert 1.01 <= params["zoom"] <= 1.03
    assert 4 <= params["noise_sigma"] <= 8
    assert params["mirror"] is True

    filter_str = build_filter_complex(params)
    assert "hflip" in filter_str
    assert "scale=" in filter_str
    assert "crop=" in filter_str
    assert "setsar=1" in filter_str
    assert "noise=" in filter_str
    assert "eq=" in filter_str
    assert "setpts=" in filter_str



@pytest.mark.asyncio
async def test_database_operations(tmp_path):
    """Test SQLite cataloging and deduplication."""
    db_file = str(tmp_path / "test_catalog.db")
    await db.init_db(db_file)

    video_data = {
        "id": "test_id_1",
        "title": "Test Short Video",
        "channel": "TestChannel",
        "views": 10000,
        "likes": 500,
        "comments": 20,
        "duration": 30,
        "thumbnail_url": "https://example.com/thumb.jpg",
    }

    assert await db.is_video_seen(db_file, "test_id_1") is False
    await db.upsert_discovered(db_file, video_data)
    assert await db.is_video_seen(db_file, "test_id_1") is True

    raw_path = str(tmp_path / "raw.mp4")
    await db.mark_downloaded(db_file, "test_id_1", raw_path)
    video = await db.get_video(db_file, "test_id_1")
    assert video["status"] == "downloaded"
    assert video["raw_path"] == raw_path

    processed_path = str(tmp_path / "processed.mp4")
    params = {"speed": 1.02, "preset": "subtle"}
    await db.mark_processed(db_file, "test_id_1", processed_path, params)

    video = await db.get_video(db_file, "test_id_1")
    assert video["status"] == "processed"
    assert video["processed_path"] == processed_path
    assert "1.02" in video["perturbation_params"]

    videos_list = await db.list_videos(db_file)
    assert len(videos_list) == 1


@pytest.mark.asyncio
async def test_end_to_end_video_perturbation(tmp_path):
    """Generate a synthetic video with FFmpeg and process it through obfuscation."""
    ffmpeg_bin, _ = get_ffmpeg_paths()
    input_video = str(tmp_path / "synthetic_input.mp4")
    output_video = str(tmp_path / "perturbed_output.mp4")

    # Generate a 2-second test video with audio
    gen_cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=duration=2:size=360x640:rate=30",
        "-f", "lavfi",
        "-i", "sine=frequency=1000:duration=2",
        "-c:v", "libx264",
        "-c:a", "aac",
        input_video,
    ]
    subprocess.run(gen_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    assert os.path.exists(input_video)

    # Process through our perturbation engine
    applied_params = await process_video(
        input_path=input_video,
        output_path=output_video,
        preset="subtle",
        mirror=True,
    )

    assert os.path.exists(output_video)
    assert os.path.getsize(output_video) > 0
    assert applied_params["mirror"] is True
