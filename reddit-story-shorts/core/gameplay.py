"""Gameplay Manager: Handles gameplay clips library, video duration probing, and yt-dlp downloading."""

import os
import json
import random
import logging
import subprocess
import tempfile
import shutil
import math
import threading
from pathlib import Path
from functools import lru_cache
from typing import List, Dict, Any, Optional, Tuple
from core.ffmpeg_manager import get_ffmpeg_paths

logger = logging.getLogger(__name__)
SLICE_HISTORY_PATH = Path(__file__).resolve().parents[1] / "cache" / "background_slices.json"
_slice_lock = threading.Lock()
_last_slice_starts = {}

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
        "url": "https://www.youtube.com/watch?v=QPW3XwBoQlw",
        "category": "Mobile",
    },
    {
        "id": "gta_mega_ramp",
        "title": "GTA 5 Mega Ramp Stunts",
        "url": "https://www.youtube.com/watch?v=awJz5HaQUZA",
        "category": "GTA 5",
    },
    {
        "id": "cooking_tomato_slicing",
        "title": "Satisfying Cooking — Tomato Slicing",
        "url": "https://assets.mixkit.co/videos/40534/40534-1080.mp4",
        "source_url": "https://mixkit.co/free-stock-video/a-man-slices-a-tomato-40534/",
        "category": "Cooking", "source": "stock",
        "license": "Mixkit Stock Video Free License",
    },
    {
        "id": "cooking_dough_mixing",
        "title": "Satisfying Cooking — Dough Mixing",
        "url": "https://assets.mixkit.co/videos/42464/42464-1080.mp4",
        "source_url": "https://mixkit.co/free-stock-video/cook-mixing-flour-for-a-dough-42464/",
        "category": "Cooking", "source": "stock",
        "license": "Mixkit Stock Video Free License",
    },
    {
        "id": "cooking_simmering_sauce",
        "title": "Satisfying Cooking — Simmering Meatballs",
        "url": "https://assets.mixkit.co/videos/3806/3806-1080.mp4",
        "source_url": "https://mixkit.co/free-stock-video/cooking-meat-balls-in-sauce-3806/",
        "category": "Cooking", "source": "stock",
        "license": "Mixkit Stock Video Free License",
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
    stat = os.stat(video_path)
    return dict(_probe_video_metadata(os.path.abspath(video_path), stat.st_size, stat.st_mtime_ns))


@lru_cache(maxsize=128)
def _probe_video_metadata(video_path: str, size: int, modified: int) -> Dict[str, Any]:
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
        numerator, denominator = video_stream.get("r_frame_rate", "0/1").split("/")
        fps = float(numerator) / float(denominator) if float(denominator) else 0.0

        return {
            "path": os.path.abspath(video_path),
            "filename": os.path.basename(video_path),
            "duration": duration,
            "width": width,
            "height": height,
            "fps": fps,
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
            if meta["duration"] > 0:
                preset = next((p for p in GAMEPLAY_PRESETS if os.path.splitext(file_name)[0] == p["id"]), None)
                meta["display_name"] = preset["title"] if preset else file_name
                meta["category"] = "Cooking" if preset and preset["category"] == "Cooking" else "Gameplay" if preset else "Custom"
                videos.append(meta)

    return videos


def get_random_slice(video_path: str, required_duration: float) -> Tuple[float, float]:
    """Choose a narration-length segment, avoiding the previous segment's start."""
    if not math.isfinite(required_duration) or required_duration <= 0:
        raise ValueError("Narration duration must be positive and finite")
    meta = probe_video_metadata(video_path)
    total_duration = meta["duration"]

    if total_duration <= required_duration:
        return 0.0, required_duration

    max_start = total_duration - required_duration
    key = os.path.normcase(os.path.abspath(video_path))
    with _slice_lock:
        try:
            history = json.loads(SLICE_HISTORY_PATH.read_text(encoding="utf-8"))
            if isinstance(history, dict):
                _last_slice_starts.update(history)
        except (OSError, ValueError):
            pass
        previous = _last_slice_starts.get(key)
        if isinstance(previous, (int, float)) and math.isfinite(previous) and 0 <= previous <= max_start:
            # Use a different whole section when space allows; still vary near-fit clips.
            gap = min(required_duration, max_start / 4)
            left_end = max(0.0, previous - gap)
            right_start = min(max_start, previous + gap)
            offset = random.uniform(0.0, left_end + max_start - right_start)
            start_time = offset if left_end > 0 and offset <= left_end else right_start + offset - left_end
        else:
            start_time = random.uniform(0.0, max_start)
        _last_slice_starts.pop(key, None)
        _last_slice_starts[key] = start_time
        while len(_last_slice_starts) > 256:
            _last_slice_starts.pop(next(iter(_last_slice_starts)))
        try:
            SLICE_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=SLICE_HISTORY_PATH.parent,
                                             suffix=".tmp", delete=False) as output:
                json.dump(_last_slice_starts, output)
                pending = output.name
            os.replace(pending, SLICE_HISTORY_PATH)
        except OSError:
            logger.warning("Could not persist background segment history", exc_info=True)

    return start_time, required_duration


def download_youtube_gameplay(
    url: str,
    custom_name: Optional[str] = None,
    max_duration: Optional[float] = 300.0,
) -> str:
    """Download a curated stock background or a YouTube clip."""
    preset = next((p for p in GAMEPLAY_PRESETS if p['url'] == url and p.get('source') == 'stock'), None)
    if preset:
        return download_stock_background(preset)
    import yt_dlp

    gameplay_dir = get_gameplay_dir()
    ffmpeg_cmd, _ = get_ffmpeg_paths()

    ydl_opts = {
        "format": "bestvideo[ext=mp4][width<=1280][height<=1280]+bestaudio[ext=m4a]/best[ext=mp4][width<=1280][height<=1280]/best[width<=1280][height<=1280]",
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "ffmpeg_location": os.path.dirname(ffmpeg_cmd),
        "noplaylist": True,
        "socket_timeout": 15,
        "retries": 2,
        "extractor_retries": 1,
    }

    # Download locally before trimming: FFmpeg remote range requests can stall.
    pending_dir = os.path.join(gameplay_dir, ".downloads")
    os.makedirs(pending_dir, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=pending_dir) as staging:
        ydl_opts["outtmpl"] = os.path.join(staging, "gameplay.%(ext)s")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            mp4_filename = os.path.splitext(filename)[0] + ".mp4"
            if os.path.exists(mp4_filename):
                filename = mp4_filename
            final_name = custom_name or yt_dlp.utils.sanitize_filename(info.get("title", "gameplay"), restricted=True)
            if os.path.basename(final_name) != final_name or final_name in (".", ".."):
                raise ValueError("Invalid gameplay filename")
            final_path = os.path.join(gameplay_dir, final_name + ".mp4")
            ready_path = os.path.join(staging, "ready.mp4")
            if max_duration and max_duration > 0:
                subprocess.run([ffmpeg_cmd, "-y", "-v", "error", "-i", filename,
                    "-t", str(max_duration), "-c", "copy", "-movflags", "+faststart", ready_path],
                    check=True, capture_output=True, timeout=120)
            else:
                shutil.copyfile(filename, ready_path)
            if probe_video_metadata(ready_path)["duration"] <= 0:
                raise RuntimeError("Downloaded gameplay is not a playable video")
            os.replace(ready_path, final_path)
            return os.path.abspath(final_path)


def download_stock_background(preset: Dict[str, Any]) -> str:
    """Fetch only curated stock sources, validating before atomic installation."""
    import requests
    if preset not in GAMEPLAY_PRESETS or preset.get('source') != 'stock':
        raise ValueError('Unknown stock background')
    gameplay_dir = get_gameplay_dir()
    final_path = os.path.join(gameplay_dir, preset['id'] + '.mp4')
    if os.path.isfile(final_path) and probe_video_metadata(final_path)['duration'] > 0:
        return os.path.abspath(final_path)
    pending = os.path.join(gameplay_dir, '.downloads')
    os.makedirs(pending, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=pending) as staging:
        ready = os.path.join(staging, 'ready.mp4')
        with requests.get(preset['url'], stream=True, timeout=(10, 45)) as response:
            response.raise_for_status()
            with open(ready, 'wb') as output:
                for chunk in response.iter_content(1024 * 1024):
                    if chunk:
                        output.write(chunk)
        if probe_video_metadata(ready)['duration'] <= 0:
            raise RuntimeError('Stock download is not a playable video')
        os.replace(ready, final_path)
    return os.path.abspath(final_path)

