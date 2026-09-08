"""Gameplay Manager: Handles gameplay clips library, video duration probing, and yt-dlp downloading."""

import os
import json
import random
import logging
import subprocess
from typing import List, Dict, Any, Optional, Tuple
from core.ffmpeg_manager import get_ffmpeg_paths

logger = logging.getLogger(__name__)

GAMEPLAY_PRESETS = [
    {
        "id": "minecraft_parkour",
        "title": "Minecraft Parkour (Copyright-Free)",
        "url": "https://www.youtube.com/watch?v=n_Dv4JMiwK8",  # Standard copyright free parkour
        "category": "Minecraft",
    },
    {
        "id": "subway_surfers",
        "title": "Subway Surfers Gameplay",
        "url": "https://www.youtube.com/watch?v=u7kdmn30OGg",
        "category": "Mobile",
    },
    {
        "id": "gta_mega_ramp",
        "title": "GTA 5 Mega Ramp Stunts",
        "url": "https://www.youtube.com/watch?v=F3z394lQ59w",
        "category": "GTA 5",
    },
]


def get_gameplay_dir() -> str:
    """Return absolute path to assets/gameplay directory."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gameplay_dir = os.path.join(project_root, "assets", "gameplay")
    os.makedirs(gameplay_dir, exist_ok=True)
    return gameplay_dir


def probe_video_metadata(video_path: str) -> Dict[str, Any]:
    """Retrieve video duration, width, height, and fps using ffprobe."""
    _, ffprobe_cmd = get_ffmpeg_paths()
    cmd = [
        ffprobe_cmd,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,duration:format=duration",
        "-of", "json",
        video_path,
    ]

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        data = json.loads(res.stdout)

        streams = data.get("streams", [{}])
        video_stream = streams[0] if streams else {}
        format_info = data.get("format", {})

        duration_val = video_stream.get("duration") or format_info.get("duration") or 0.0
        duration = float(duration_val)

        width = int(video_stream.get("width", 1080))
        height = int(video_stream.get("height", 1920))

        return {
            "path": os.path.abspath(video_path),
            "filename": os.path.basename(video_path),
            "duration": duration,
            "width": width,
            "height": height,
            "size_bytes": os.path.getsize(video_path) if os.path.exists(video_path) else 0,
        }
    except Exception as err:
        logger.warning(f"Failed to probe video {video_path}: {err}")
        return {
            "path": os.path.abspath(video_path),
            "filename": os.path.basename(video_path),
            "duration": 0.0,
            "width": 1080,
            "height": 1920,
            "size_bytes": 0,
        }


def list_available_gameplay_videos() -> List[Dict[str, Any]]:
    """List all supported video files in the gameplay assets folder."""
    gameplay_dir = get_gameplay_dir()
    allowed_exts = {".mp4", ".mov", ".mkv", ".webm"}
    videos: List[Dict[str, Any]] = []

    if not os.path.exists(gameplay_dir):
        return videos

    for file_name in os.listdir(gameplay_dir):
        ext = os.path.splitext(file_name)[1].lower()
        if ext in allowed_exts:
            full_path = os.path.join(gameplay_dir, file_name)
            meta = probe_video_metadata(full_path)
            videos.append(meta)

    return videos


def get_random_slice(video_path: str, required_duration: float) -> Tuple[float, float]:
    """Calculate random start time and duration slice within the gameplay clip."""
    meta = probe_video_metadata(video_path)
    total_duration = meta["duration"]

    if total_duration <= required_duration or total_duration <= 5.0:
        return 0.0, required_duration

    # Pick random start allowing a 3-second buffer at the end
    max_start = max(0.0, total_duration - required_duration - 3.0)
    start_time = round(random.uniform(0.0, max_start), 2)

    return start_time, required_duration


def download_youtube_gameplay(
    url: str,
    custom_name: Optional[str] = None,
    max_duration: Optional[float] = 300.0,
) -> str:
    """Download gameplay video from YouTube using yt-dlp."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    gameplay_dir = get_gameplay_dir()
    output_template = (
        os.path.join(gameplay_dir, f"{custom_name}.%(ext)s")
        if custom_name
        else os.path.join(gameplay_dir, "%(title)s.%(ext)s")
    )

    ffmpeg_cmd, _ = get_ffmpeg_paths()

    ydl_opts = {
        "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "ffmpeg_location": os.path.dirname(ffmpeg_cmd),
    }

    if max_duration and max_duration > 0:
        ydl_opts["download_ranges"] = download_range_func(None, [(0, max_duration)])
        ydl_opts["force_keyframes_at_cuts"] = True

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        # In case merging produced .mp4
        mp4_filename = os.path.splitext(filename)[0] + ".mp4"
        if os.path.exists(mp4_filename):
            return os.path.abspath(mp4_filename)
        return os.path.abspath(filename)

