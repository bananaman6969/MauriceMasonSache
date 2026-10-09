"""Regression coverage for caching, cancellation, and actual video output."""
import asyncio
import json
from pathlib import Path
import subprocess
import threading
import time

import httpx
import pytest

from core import performance, tts
from core.composer import render_short_video
from core.ffmpeg_manager import get_ffmpeg_paths
from core.gameplay import probe_video_metadata
from core.subtitles import generate_karaoke_ass
from core.title_card import generate_reddit_title_card


@pytest.mark.asyncio
async def test_narration_cache_and_invalidation(tmp_path, monkeypatch):
    monkeypatch.setattr(tts, "TTS_CACHE_DIR", tmp_path / "cache")
    calls = []
    class FakeSpeech:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        async def stream(self):
            yield {"type": "audio", "data": b"audio"}
            yield {"type": "WordBoundary", "offset": 0, "duration": 10000000, "text": "Hello"}
    monkeypatch.setattr(tts.edge_tts, "Communicate", FakeSpeech)
    first = await tts.generate_speech_with_timings("Hello", str(tmp_path / "one.mp3"))
    second = await tts.generate_speech_with_timings("Hello", str(tmp_path / "two.mp3"))
    assert first.words == second.words and len(calls) == 1
    assert Path(second.audio_path).read_bytes() == b"audio"
    await tts.generate_speech_with_timings("Hello", str(tmp_path / "three.mp3"), rate="+10%")
    assert len(calls) == 2
    for meta in (tmp_path / "cache").glob("*.json"):
        meta.write_text("broken")
    await tts.generate_speech_with_timings("Hello", str(tmp_path / "four.mp3"))
    assert len(calls) == 3


def test_hardware_detection_rejects_unusable_encoders(monkeypatch):
    performance.detect_encoder.cache_clear()
    monkeypatch.setattr(performance.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1))
    assert performance.detect_encoder() == "libx264"
    performance.detect_encoder.cache_clear()


@pytest.mark.parametrize("profile,dimensions", [("fast", (720, 1280)), ("quality", (1080, 1920))])
def test_real_render_loops_background_and_preserves_overlays(tmp_path, monkeypatch, profile, dimensions):
    monkeypatch.setattr(performance, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(performance, "detect_encoder", lambda: "libx264")
    background = performance.prepare_gameplay(None, profile, encoding="cpu")
    original_mtime = Path(background).stat().st_mtime_ns
    assert performance.prepare_gameplay(None, profile) == background
    assert Path(background).stat().st_mtime_ns == original_mtime
    ffmpeg, ffprobe = get_ffmpeg_paths()
    voice = tmp_path / "voice.wav"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=8", str(voice)], check=True)
    captions = tmp_path / "captions.ass"
    generate_karaoke_ass([tts.WordTiming("Hello", 0, 4), tts.WordTiming("World", 4, 8)], str(captions))
    card = tmp_path / "card.png"
    generate_reddit_title_card("r/test", "tester", "Render performance test", 100, 10, str(card))
    output = tmp_path / "output.mp4"
    progress = []
    started = time.perf_counter()
    render_short_video(background, str(voice), str(captions), str(output), 8,
        title_card_path=str(card), export_profile=profile, encoding="cpu",
        prepared_gameplay=True, progress_callback=progress.append)
    meta = probe_video_metadata(str(output))
    assert (meta["width"], meta["height"]) == dimensions
    assert meta["fps"] == 30 and meta["duration"] >= 8
    assert progress[-1] == 100
    result = subprocess.run([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(output)], capture_output=True, text=True, check=True)
    assert any(s["codec_type"] == "audio" for s in json.loads(result.stdout)["streams"])
    print(f"{profile}: 8 second CPU render took {time.perf_counter() - started:.2f}s")


def test_preparation_cancelled_never_publishes_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(performance, "CACHE_DIR", tmp_path / "cache")
    with pytest.raises(RuntimeError, match="cancelled"):
        performance.prepare_gameplay(None, cancelled=lambda: True)
    assert not list((tmp_path / "cache").glob("*.mp4"))


@pytest.mark.asyncio
async def test_dashboard_and_cancellation_respond_while_worker_is_busy(monkeypatch):
    import app as server
    started = threading.Event()
    async def slow_worker(job_id, req):
        started.set()
        deadline = time.monotonic() + 3
        while job_id not in server.cancelled_jobs and time.monotonic() < deadline:
            time.sleep(0.02)  # Deliberately blocks the worker's event loop.
    monkeypatch.setattr(server, "_run_render_job", slow_worker)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
        request = asyncio.create_task(client.post("/api/render", json={"title": "Test", "body": "Hello"}))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            job_id = next(reversed(server.render_jobs))
            status = await asyncio.wait_for(client.get(f"/api/render/status/{job_id}"), 1)
            assert status.status_code == 200
            cancelled = await asyncio.wait_for(client.post(f"/api/render/cancel/{job_id}"), 1)
            assert cancelled.status_code == 200
            assert (await asyncio.wait_for(request, 1)).status_code == 200
        finally:
            if not request.done():
                request.cancel()
