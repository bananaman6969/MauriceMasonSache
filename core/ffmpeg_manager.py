"""FFmpeg Manager: Automatically locates or vendors FFmpeg for Windows and cross-platform runtimes."""

import os
import shutil
import subprocess
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def get_ffmpeg_paths() -> Tuple[str, str]:
    """Find or vendor ffmpeg and ffprobe binaries.
    
    Returns:
        Tuple[str, str]: (path_to_ffmpeg, path_to_ffprobe)
    """
    ffmpeg_cmd = shutil.which("ffmpeg")
    ffprobe_cmd = shutil.which("ffprobe")

    if ffmpeg_cmd and ffprobe_cmd:
        return ffmpeg_cmd, ffprobe_cmd

    # Try static_ffmpeg integration
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
        ffmpeg_cmd = shutil.which("ffmpeg")
        ffprobe_cmd = shutil.which("ffprobe")
        if ffmpeg_cmd and ffprobe_cmd:
            return ffmpeg_cmd, ffprobe_cmd
    except Exception as err:
        logger.warning(f"Could not load static_ffmpeg: {err}")

    # Fallback to local ./bin/ directory if present
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bin_dir = os.path.join(project_root, "bin")
    local_ffmpeg = os.path.join(bin_dir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    local_ffprobe = os.path.join(bin_dir, "ffprobe.exe" if os.name == "nt" else "ffprobe")

    if os.path.exists(local_ffmpeg) and os.path.exists(local_ffprobe):
        return local_ffmpeg, local_ffprobe

    raise RuntimeError(
        "FFmpeg binary not found. Please install static-ffmpeg or ensure FFmpeg is in PATH."
    )


def verify_ffmpeg_binary(ffmpeg_path: str) -> bool:
    """Verify that FFmpeg can execute correctly.
    
    Args:
        ffmpeg_path: Absolute path or executable name for ffmpeg.
        
    Returns:
        bool: True if ffmpeg responds with exit code 0.
    """
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception as err:
        logger.error(f"FFmpeg verification failed: {err}")
        return False
