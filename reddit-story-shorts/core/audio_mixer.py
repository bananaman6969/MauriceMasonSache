"""Audio Mixer: Manages background music tracks, volumes, and audio ducking presets."""

import os
import math
import struct
import wave
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


def get_music_dir() -> str:
    """Return absolute path to assets/music directory."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    music_dir = os.path.join(project_root, "assets", "music")
    os.makedirs(music_dir, exist_ok=True)
    return music_dir


def create_ambient_lofi_track(output_path: str, duration_sec: int = 120) -> str:
    """Create a soft, royalty-free ambient lofi pad audio track if no music is provided."""
    sample_rate = 44100
    num_samples = sample_rate * duration_sec

    # Generate chord progression with gentle warm sine waves and pink noise vinyl texture
    freqs = [261.63, 329.63, 392.00, 493.88]  # C major 7 chord
    with wave.open(output_path, "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        frames = bytearray()
        for i in range(num_samples):
            t = i / sample_rate
            # LFO modulation
            lfo = 0.5 + 0.5 * math.sin(2 * math.pi * 0.2 * t)

            # Sum tones
            sample_val = 0.0
            for f_idx, f in enumerate(freqs):
                detune = 1.0 + 0.002 * math.sin(2 * math.pi * (0.1 + f_idx * 0.05) * t)
                sample_val += math.sin(2 * math.pi * f * detune * t) * (0.25 / len(freqs))

            # Apply lfo and gentle soft-knee compression
            sample_val *= lfo * 0.6
            int_val = int(max(min(sample_val, 1.0), -1.0) * 32767)

            # Stereo 16-bit PCM
            frames.extend(struct.pack("<hh", int_val, int_val))

        wav_file.writeframes(frames)

    return os.path.abspath(output_path)


def list_available_music_tracks() -> List[Dict[str, Any]]:
    """List all audio tracks available in assets/music/."""
    music_dir = get_music_dir()
    allowed_exts = {".mp3", ".wav", ".aac", ".ogg", ".m4a"}
    tracks: List[Dict[str, Any]] = []

    if not os.path.exists(music_dir):
        return tracks

    for file_name in os.listdir(music_dir):
        ext = os.path.splitext(file_name)[1].lower()
        if ext in allowed_exts:
            full_path = os.path.join(music_dir, file_name)
            name = os.path.splitext(file_name)[0].replace("_", " ").title()
            tracks.append({
                "id": file_name,
                "name": name,
                "path": os.path.abspath(full_path),
            })

    # If empty, generate default ambient lofi track
    if not tracks:
        default_track = os.path.join(music_dir, "ambient_lofi_chill.wav")
        try:
            create_ambient_lofi_track(default_track, duration_sec=90)
            tracks.append({
                "id": "ambient_lofi_chill.wav",
                "name": "Ambient Lofi Chill",
                "path": os.path.abspath(default_track),
            })
        except Exception as err:
            logger.warning(f"Could not generate default ambient track: {err}")

    return tracks
