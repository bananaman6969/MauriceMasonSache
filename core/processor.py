"""Video Obfuscation Engine: Applies randomized anti-detection perturbations using FFmpeg."""

import os
import uuid
import random
import logging
import asyncio
from datetime import datetime, timezone, timedelta
import subprocess
from typing import Dict, Any, Optional, Set
from core.ffmpeg_manager import get_ffmpeg_paths

logger = logging.getLogger(__name__)

# Track running FFmpeg subprocesses to allow instant cancellation
active_ffmpeg_processes: Set[asyncio.subprocess.Process] = set()


def terminate_all_ffmpeg_processes() -> int:
    """Terminate and kill any currently running FFmpeg subprocesses."""
    count = 0
    for proc in list(active_ffmpeg_processes):
        try:
            if proc.returncode is None:
                proc.kill()
                count += 1
        except Exception as e:
            logger.warning(f"Error terminating FFmpeg process: {e}")
    active_ffmpeg_processes.clear()
    logger.info(f"Terminated {count} running FFmpeg processes.")
    return count


def generate_random_params(
    preset: str = "subtle",
    mirror: Optional[bool] = None,
    custom_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate bounded, randomized perturbation parameters according to chosen preset."""
    ranges = {
        "subtle": {
            "speed": (1.012, 1.028),
            "zoom": (1.012, 1.025),
            "noise": (4, 8),
            "contrast": (1.01, 1.03),
            "brightness": (0.005, 0.018),
            "saturation": (1.01, 1.03),
            "default_mirror": False,
        },
        "moderate": {
            "speed": (1.025, 1.045),
            "zoom": (1.025, 1.040),
            "noise": (8, 14),
            "contrast": (1.02, 1.05),
            "brightness": (0.012, 0.030),
            "saturation": (1.02, 1.05),
            "default_mirror": False,
        },
        "aggressive": {
            "speed": (1.035, 1.065),
            "zoom": (1.035, 1.055),
            "noise": (14, 22),
            "contrast": (1.04, 1.08),
            "brightness": (0.020, 0.045),
            "saturation": (1.03, 1.07),
            "default_mirror": False,
        },
    }

    config = ranges.get(preset, ranges["subtle"])

    # Sample within safety bounds
    speed = round(random.uniform(*config["speed"]), 4)
    zoom = round(random.uniform(*config["zoom"]), 4)
    noise = int(random.randint(*config["noise"]))
    contrast = round(random.uniform(*config["contrast"]), 3)
    brightness = round(random.uniform(*config["brightness"]), 3)
    saturation = round(random.uniform(*config["saturation"]), 3)
    apply_mirror = mirror if mirror is not None else config["default_mirror"]

    # Randomized past creation timestamp within last 7 days
    random_days = random.randint(1, 7)
    random_hours = random.randint(0, 23)
    creation_date = (
        datetime.now(timezone.utc) - timedelta(days=random_days, hours=random_hours)
    ).strftime("%Y-%m-%d %H:%M:%S")

    params = {
        "preset": preset,
        "speed": speed,
        "zoom": zoom,
        "noise_sigma": noise,
        "contrast": contrast,
        "brightness": brightness,
        "saturation": saturation,
        "mirror": apply_mirror,
        "creation_time": creation_date,
        "unique_id": str(uuid.uuid4()),
    }

    # Apply any explicit user overrides
    if custom_overrides:
        for k, v in custom_overrides.items():
            if v is not None and k in params:
                params[k] = v

    return params


def build_filter_complex(params: Dict[str, Any]) -> str:
    """Construct FFmpeg video and audio filter graph string."""
    v_filters = []

    # Downscale oversized 4K inputs to standard 1080p width with proportional even height
    v_filters.append("scale='min(1080,iw)':-2")

    if params.get("mirror"):
        v_filters.append("hflip")

    # Safe Micro-zoom & Crop:
    # 1. Crop 1-2% from the center
    # 2. Rescale back to incoming standard dimensions
    # 3. Enforce 1:1 square pixel aspect ratio to prevent warping/stretching
    zoom = params["zoom"]
    v_filters.append(f"crop=trunc(iw/{zoom}/2)*2:trunc(ih/{zoom}/2)*2")
    v_filters.append("scale=iw:ih")
    v_filters.append("setsar=1")

    # Subtle luma film grain to defeat pHash / dHash without bitrate explosion
    noise = params["noise_sigma"]
    v_filters.append(f"noise=c0s={noise}:c0f=t+u")

    # Color, brightness, and contrast jitter
    contrast = params["contrast"]
    brightness = params["brightness"]
    saturation = params["saturation"]
    v_filters.append(f"eq=contrast={contrast}:brightness={brightness}:saturation={saturation}")

    # Micro playback speed adjustment (exact PTS ratio)
    speed = params["speed"]
    v_filters.append(f"setpts=PTS/{speed}")

    return ",".join(v_filters)


async def process_video(
    input_path: str,
    output_path: str,
    preset: str = "subtle",
    mirror: Optional[bool] = None,
    custom_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute FFmpeg to obfuscate input video with randomized perturbation parameters."""
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input video file not found: {input_path}")

    target_dir = os.path.dirname(os.path.abspath(output_path))
    os.makedirs(target_dir, exist_ok=True)
    ffmpeg_bin, _ = get_ffmpeg_paths()

    params = generate_random_params(preset=preset, mirror=mirror, custom_overrides=custom_overrides)
    video_filter = build_filter_complex(params)
    # Audio resampling ensures audio and video stay perfectly synchronized
    audio_filter = f"atempo={params['speed']},aresample=async=1"

    # Leave at least 2 cores free for system responsiveness
    cpu_count = os.cpu_count() or 4
    threads_to_use = max(1, min(cpu_count - 2, 4))

    # Write to a temporary file first to prevent partial/corrupted files if interrupted
    tmp_output_path = os.path.join(target_dir, f".tmp_{uuid.uuid4().hex[:8]}_{os.path.basename(output_path)}")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-threads", str(threads_to_use),
        "-i", input_path,
        "-vf", video_filter,
        "-af", audio_filter,
        "-map_metadata", "-1",
        "-metadata", f"title={params['unique_id']}",
        "-metadata", f"comment={params['unique_id']}",
        "-metadata", f"creation_time={params['creation_time']}",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-ac", "2",
        "-ar", "44100",
        "-b:a", "128k",
        "-max_muxing_queue_size", "1024",
        "-movflags", "+faststart",
        tmp_output_path,
    ]

    exec_kwargs = {}
    if os.name == "nt":
        exec_kwargs["creationflags"] = subprocess.BELOW_NORMAL_PRIORITY_CLASS

    logger.info(f"Running FFmpeg obfuscation on {input_path} -> {output_path}")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **exec_kwargs,
    )

    active_ffmpeg_processes.add(process)
    try:
        stdout, stderr = await process.communicate()
    except (asyncio.CancelledError, BaseException):
        try:
            if process.returncode is None:
                process.kill()
                await process.wait()
        except Exception:
            pass
        if os.path.exists(tmp_output_path):
            try:
                os.remove(tmp_output_path)
            except OSError:
                pass
        raise
    finally:
        active_ffmpeg_processes.discard(process)

    if process.returncode != 0:
        if os.path.exists(tmp_output_path):
            try:
                os.remove(tmp_output_path)
            except OSError:
                pass
        err_msg = stderr.decode("utf-8", errors="replace")[-600:]
        logger.error(f"FFmpeg process error: {err_msg}")
        raise RuntimeError(f"FFmpeg processing failed with code {process.returncode}: {err_msg}")

    # Atomic rename upon verified success
    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except OSError:
            pass
    os.replace(tmp_output_path, output_path)

    return params
