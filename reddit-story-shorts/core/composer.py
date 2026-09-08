"""Composer Engine: FFmpeg composition pipeline for 9:16 vertical shorts."""

import os
import re
import json
import logging
import subprocess
from typing import Optional, Callable, Dict, Any
from core.ffmpeg_manager import get_ffmpeg_paths
from core.gameplay import probe_video_metadata

logger = logging.getLogger(__name__)


def escape_ffmpeg_filter_path(file_path: str) -> str:
    """Escape Windows file paths for FFmpeg filter arguments (subtitles filter)."""
    # Convert \ to / and escape colons (e.g. C: -> C\:)
    normalized = file_path.replace("\\", "/")
    escaped = normalized.replace(":", "\\:")
    return escaped


def has_audio_stream(video_path: str) -> bool:
    """Check if the given video file contains an audio stream."""
    _, ffprobe_cmd = get_ffmpeg_paths()
    cmd = [
        ffprobe_cmd,
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=codec_name",
        "-of", "json",
        video_path,
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)
        return len(data.get("streams", [])) > 0
    except Exception:
        return False


def build_ffmpeg_command(
    gameplay_path: str,
    voice_path: str,
    subtitles_path: str,
    output_path: str,
    duration: float,
    start_time: float = 0.0,
    title_card_path: Optional[str] = None,
    bgm_path: Optional[str] = None,
    voice_volume: float = 1.25,
    gameplay_volume: float = 0.10,
    bgm_volume: float = 0.15,
    title_card_duration: float = 3.5,
) -> list[str]:
    """Construct the FFmpeg command line arguments for 9:16 rendering."""
    ffmpeg_cmd, _ = get_ffmpeg_paths()
    escaped_sub_path = escape_ffmpeg_filter_path(subtitles_path)

    gameplay_has_audio = has_audio_stream(gameplay_path)

    inputs = []
    # Input 0: Gameplay video
    inputs.extend(["-ss", str(start_time), "-t", str(duration), "-i", gameplay_path])

    # Input 1: Voiceover
    inputs.extend(["-i", voice_path])

    input_count = 2

    title_card_idx = None
    if title_card_path and os.path.exists(title_card_path):
        inputs.extend(["-loop", "1", "-t", str(title_card_duration + 0.5), "-i", title_card_path])
        title_card_idx = input_count
        input_count += 1

    bgm_idx = None
    if bgm_path and os.path.exists(bgm_path):
        inputs.extend(["-stream_loop", "-1", "-t", str(duration), "-i", bgm_path])
        bgm_idx = input_count
        input_count += 1

    # Build Video Filters
    # 1. Scale & Crop to 1080x1920 (9:16)
    filter_chains = []
    v_base = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v_cropped]"
    filter_chains.append(v_base)
    current_v = "[v_cropped]"

    # 2. Overlay Title Card if provided
    if title_card_idx is not None:
        fade_start = max(0.0, title_card_duration - 0.5)
        # Apply smooth alpha fade out to the card
        card_filter = (
            f"[{title_card_idx}:v]format=rgba,"
            f"fade=t=out:st={fade_start:.2f}:d=0.5:alpha=1[faded_card]"
        )
        filter_chains.append(card_filter)
        overlay_filter = (
            f"{current_v}[faded_card]overlay=(W-w)/2:(H-h)/2-120:enable='lte(t,{title_card_duration:.2f})'[v_card]"
        )
        filter_chains.append(overlay_filter)
        current_v = "[v_card]"

    # 3. Burn in Subtitles
    sub_filter = f"{current_v}subtitles='{escaped_sub_path}'[v_final]"
    filter_chains.append(sub_filter)

    # Build Audio Filters
    audio_inputs = []
    a_filters = []

    # Voice (Always input 1)
    a_filters.append(f"[1:a]volume={voice_volume:.2f}[a_voice]")
    audio_inputs.append("[a_voice]")

    # Gameplay audio
    if gameplay_has_audio:
        a_filters.append(f"[0:a]volume={gameplay_volume:.2f}[a_gameplay]")
        audio_inputs.append("[a_gameplay]")

    # BGM audio
    if bgm_idx is not None:
        a_filters.append(f"[{bgm_idx}:a]volume={bgm_volume:.2f}[a_bgm]")
        audio_inputs.append("[a_bgm]")

    if len(audio_inputs) > 1:
        mix_inputs = "".join(audio_inputs)
        a_filters.append(f"{mix_inputs}amix=inputs={len(audio_inputs)}:duration=first:dropout_transition=2[a_final]")
        final_audio_label = "[a_final]"
    else:
        final_audio_label = audio_inputs[0]

    filter_chains.extend(a_filters)
    filter_complex = "; ".join(filter_chains)

    cmd = [
        ffmpeg_cmd,
        "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[v_final]",
        "-map", final_audio_label,
        "-t", str(duration),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]

    return cmd


def render_short_video(
    gameplay_path: str,
    voice_path: str,
    subtitles_path: str,
    output_path: str,
    duration: float,
    start_time: float = 0.0,
    title_card_path: Optional[str] = None,
    bgm_path: Optional[str] = None,
    voice_volume: float = 1.25,
    gameplay_volume: float = 0.10,
    bgm_volume: float = 0.15,
    title_card_duration: float = 3.5,
    progress_callback: Optional[Callable[[float], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    process_callback: Optional[Callable[[subprocess.Popen], None]] = None,
) -> str:
    """Render the final vertical short video using FFmpeg.
    
    Tracks progress via stdout/stderr parsing, invokes progress_callback, and allows cancellation.
    """
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # Pad target duration slightly (0.4s) so speech is never clipped at the tail
    render_duration = round(duration + 0.4, 2)

    cmd = build_ffmpeg_command(
        gameplay_path=gameplay_path,
        voice_path=voice_path,
        subtitles_path=subtitles_path,
        output_path=output_path,
        duration=render_duration,
        start_time=start_time,
        title_card_path=title_card_path,
        bgm_path=bgm_path,
        voice_volume=voice_volume,
        gameplay_volume=gameplay_volume,
        bgm_volume=bgm_volume,
        title_card_duration=title_card_duration,
    )

    logger.info(f"Executing FFmpeg render command: {' '.join(cmd)}")

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        bufsize=1,
    )

    if process_callback:
        process_callback(process)

    time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")

    if process.stdout:
        for line in process.stdout:
            if is_cancelled and is_cancelled():
                try:
                    process.kill()
                    process.wait()
                except Exception:
                    pass
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except Exception:
                        pass
                raise RuntimeError("Render cancelled by user.")

            match = time_pattern.search(line)
            if match and render_duration > 0:
                hours, minutes, seconds = match.groups()
                current_sec = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                pct = min(round((current_sec / render_duration) * 100, 1), 99.0)
                if progress_callback:
                    progress_callback(pct)

    process.wait()

    if is_cancelled and is_cancelled():
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        raise RuntimeError("Render cancelled by user.")

    if process.returncode != 0:
        raise RuntimeError(f"FFmpeg rendering failed with exit code {process.returncode}")

    if progress_callback:
        progress_callback(100.0)

    return os.path.abspath(output_path)
