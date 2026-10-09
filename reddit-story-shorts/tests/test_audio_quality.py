"""Measure ducking and peak protection on actual encoded output."""
import math
import struct
import subprocess
from core.composer import render_short_video
from core import performance
from core.ffmpeg_manager import get_ffmpeg_paths
from core.subtitles import generate_karaoke_ass
from core.tts import WordTiming


def test_background_ducks_during_speech_and_peaks_are_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(performance, "CACHE_DIR", tmp_path / "cache")
    background = performance.prepare_gameplay(None, "fast", encoding="cpu")
    ffmpeg, _ = get_ffmpeg_paths()
    voice, music = tmp_path / "voice.wav", tmp_path / "music.wav"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "aevalsrc=0.25*sin(2*PI*1000*t)*between(t\\,1\\,3):s=48000:d=5", str(voice)], check=True)
    subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
        "sine=frequency=300:duration=5:sample_rate=48000", str(music)], check=True)
    subtitles, output = tmp_path / "sub.ass", tmp_path / "mixed.mp4"
    generate_karaoke_ass([WordTiming("Hello", 1, 3)], str(subtitles))
    render_short_video(background, str(voice), str(subtitles), str(output), 5,
        bgm_path=str(music), bgm_volume=1.0, export_profile="fast", encoding="cpu", prepared_gameplay=True)
    pcm = subprocess.run([ffmpeg, "-v", "error", "-i", str(output), "-vn", "-ac", "1",
        "-ar", "48000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    samples = struct.unpack(f"<{len(pcm)//4}f", pcm)
    def amplitude(start):
        window = samples[int(start * 48000):int((start + 0.4) * 48000)]
        real = sum(value * math.cos(2 * math.pi * 300 * i / 48000) for i, value in enumerate(window))
        imaginary = sum(value * math.sin(2 * math.pi * 300 * i / 48000) for i, value in enumerate(window))
        return 2 * math.hypot(real, imaginary) / len(window)
    assert amplitude(2) < amplitude(0.2) * 0.7
    assert max(abs(value) for value in samples) < 1.0
