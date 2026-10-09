"""Reusable video assets and encoders verified on the current machine."""
import hashlib
import logging
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from functools import lru_cache

from core.ffmpeg_manager import get_ffmpeg_paths

CACHE_DIR = Path(__file__).resolve().parents[1] / "cache"
PROFILES = {"fast": (720, 1280, 30), "quality": (1080, 1920, 30)}
_asset_lock = threading.Lock()
logger = logging.getLogger(__name__)


def encoder_args(encoder, profile="fast"):
    quality = profile == "quality"
    quantizer = "19" if quality else "23"
    if encoder == "h264_nvenc":
        return ["-c:v", encoder, "-preset", "p5" if quality else "p1", "-rc", "vbr", "-cq", quantizer, "-b:v", "0"]
    if encoder == "h264_qsv":
        return ["-c:v", encoder, "-preset", "medium" if quality else "veryfast", "-global_quality", quantizer]
    if encoder == "h264_amf":
        return ["-c:v", encoder, "-quality", "quality" if quality else "speed", "-rc", "cqp", "-qp_i", quantizer, "-qp_p", quantizer]
    return ["-c:v", "libx264", "-preset", "fast" if quality else "veryfast", "-crf", "18" if quality else "22"]


@lru_cache(maxsize=1)
def detect_encoder():
    """Test actual encoding, since compiled-in encoders may lack working hardware."""
    ffmpeg, _ = get_ffmpeg_paths()
    for encoder in ("h264_nvenc", "h264_qsv", "h264_amf"):
        try:
            result = subprocess.run(
                [ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                 "color=size=720x1280:rate=30", "-frames:v", "2",
                 "-pix_fmt", "yuv420p", *encoder_args(encoder), "-f", "null", "-"],
                capture_output=True, timeout=12,
            )
            if result.returncode == 0:
                logger.info("Hardware encoding available: %s", encoder)
                return encoder
        except (OSError, subprocess.TimeoutExpired):
            continue
    return "libx264"


def run_asset_command(cmd, cancelled=None, process_callback=None):
    """Run preparation without filling pipes, with prompt cancellation."""
    import tempfile
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=errors)
        if process_callback:
            process_callback(proc)
        while proc.poll() is None:
            if cancelled and cancelled():
                proc.kill()
                proc.wait()
                raise RuntimeError("Render cancelled by user.")
            time.sleep(0.1)
        if cancelled and cancelled():
            raise RuntimeError("Render cancelled by user.")
        if proc.returncode:
            errors.seek(0)
            detail = errors.read().decode("utf-8", errors="replace")[-2000:]
            raise RuntimeError(f"Background preparation failed: {detail}")


def prepare_gameplay(source, profile="quality", cancelled=None, process_callback=None, encoding="auto"):
    """Cache vertical, 30 fps gameplay; a missing source uses a short looping background."""
    width, height, fps = PROFILES[profile]
    CACHE_DIR.mkdir(exist_ok=True)
    if source:
        stat = os.stat(source)
        identity = [os.path.abspath(source), stat.st_size, stat.st_mtime_ns]
    else:
        identity = ["fallback-v1"]
    key = hashlib.sha256(repr([identity, profile, "v2"]).encode()).hexdigest()
    target = CACHE_DIR / f"gameplay_{key}.mp4"
    while not _asset_lock.acquire(timeout=0.1):
        if cancelled and cancelled():
            raise RuntimeError("Render cancelled by user.")
    try:
        if cancelled and cancelled():
            raise RuntimeError("Render cancelled by user.")
        if target.exists() and target.stat().st_size:
            return str(target)
        temp = CACHE_DIR / f"{key}_{uuid.uuid4().hex}.mp4"
        ffmpeg, _ = get_ffmpeg_paths()
        inputs = (["-i", source] if source else
                  ["-f", "lavfi", "-i", f"color=c=0x172238:s={width}x{height}:r={fps}", "-t", "6"])
        filters = f"fps={fps},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1"
        encoder = detect_encoder() if encoding == "auto" else "libx264"
        try:
            for attempt in (encoder, "libx264") if encoder != "libx264" else (encoder,):
                try:
                    run_asset_command([ffmpeg, "-y", "-v", "error", *inputs,
                        "-vf", filters, "-pix_fmt", "yuv420p", *encoder_args(attempt, profile),
                        "-c:a", "aac", "-b:a", "128k", str(temp)], cancelled, process_callback)
                    break
                except RuntimeError:
                    if attempt == "libx264" or (cancelled and cancelled()):
                        raise
                    logger.warning("Hardware preparation failed; retrying on CPU")
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return str(target)
    finally:
        _asset_lock.release()
