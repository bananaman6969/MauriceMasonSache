"""Composer Engine: FFmpeg composition pipeline for 9:16 vertical shorts."""

import os
import re
import json
import logging
import subprocess
from typing import Optional, Callable, Dict, Any
from core.ffmpeg_manager import get_ffmpeg_paths
from core.gameplay import probe_video_metadata
from core.performance import PROFILES, detect_encoder, encoder_args

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
    export_profile: str = "quality",
    encoder: str = "libx264",
    prepared_gameplay: bool = False,
) -> list[str]:
    """Construct the FFmpeg command line arguments for 9:16 rendering."""
    ffmpeg_cmd, _ = get_ffmpeg_paths()
    escaped_sub_path = escape_ffmpeg_filter_path(subtitles_path)

    gameplay_has_audio = has_audio_stream(gameplay_path)

    inputs = []
    # Input 0: Gameplay video
    inputs.extend(["-stream_loop", "-1", "-ss", str(start_time), "-t", str(duration), "-i", gameplay_path])

    # Input 1: Voiceover
    inputs.extend(["-i", voice_path])

    input_count = 2

    title_card_idx = None
    if title_card_path and os.path.exists(title_card_path):
        inputs.extend(["-loop", "1", "-framerate", "30", "-t", str(title_card_duration + 0.5), "-i", title_card_path])
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
    width, height, fps = PROFILES[export_profile]
    transform = "null" if prepared_gameplay else f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
    v_base = f"[0:v]{transform}[v_cropped]"
    filter_chains.append(v_base)
    current_v = "[v_cropped]"

    # 2. Overlay Title Card if provided
    if title_card_idx is not None:
        fade_start = max(0.0, title_card_duration - 0.5)
        # Apply smooth alpha fade out to the card
        card_filter = (
            f"[{title_card_idx}:v]scale=iw*{width}/1080:-1,format=rgba,"
            f"fade=t=out:st={fade_start:.2f}:d=0.5:alpha=1[faded_card]"
        )
        filter_chains.append(card_filter)
        overlay_filter = (
            f"{current_v}[faded_card]overlay=(W-w)/2:(H-h)/2-{120 * width / 1080}:enable='lte(t,{title_card_duration:.2f})'[v_card]"
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
    a_filters.append(f"[1:a]highpass=f=70,loudnorm=I=-16:TP=-2:LRA=9,aresample=48000,volume={voice_volume:.2f}[a_voice]")

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
        a_filters.append(f"{mix_inputs}amix=inputs={len(audio_inputs)}:duration=longest:normalize=0[a_bed]")
    else:
        if audio_inputs:
            a_filters.append(f"{audio_inputs[0]}anull[a_bed]")
    if audio_inputs:
        a_filters.append("[a_voice]asplit=2[a_narration][a_key]")
        a_filters.append("[a_bed][a_key]sidechaincompress=threshold=0.035:ratio=6:attack=10:release=250[a_ducked]")
        a_filters.append("[a_narration][a_ducked]amix=inputs=2:duration=first:normalize=0[a_mix]")
    else:
        a_filters.append("[a_voice]anull[a_mix]")
    a_filters.append("[a_mix]alimiter=limit=0.8913:level=0:latency=1[a_final]")
    final_audio_label = "[a_final]"

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
        *encoder_args(encoder, export_profile),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "320k" if export_profile == "quality" else "192k",
        "-ar", "48000",
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
    export_profile: str = "quality",
    encoding: str = "auto",
    prepared_gameplay: bool = False,
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
        export_profile=export_profile,
        encoder=detect_encoder() if encoding == "auto" else "libx264",
        prepared_gameplay=prepared_gameplay,
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
        if encoding == "auto" and detect_encoder() != "libx264":
            logger.warning("Hardware render failed; retrying on CPU")
            return render_short_video(
                gameplay_path, voice_path, subtitles_path, output_path, duration,
                start_time, title_card_path, bgm_path, voice_volume, gameplay_volume,
                bgm_volume, title_card_duration, progress_callback, is_cancelled,
                process_callback, export_profile, "cpu", prepared_gameplay,
            )
        raise RuntimeError(f"FFmpeg rendering failed with exit code {process.returncode}")

    if progress_callback:
        progress_callback(100.0)

    return os.path.abspath(output_path)
