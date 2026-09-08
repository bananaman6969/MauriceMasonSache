"""YouTube Shorts Scraper & Downloader using yt-dlp."""

import os
import re
import asyncio
import logging
from typing import List, Dict, Any, Optional
import yt_dlp

logger = logging.getLogger(__name__)


def clean_query_term(query: str) -> str:
    """Normalize query and ensure YouTube search syntax."""
    query = query.strip()
    if "#shorts" not in query.lower() and "shorts" not in query.lower():
        return f"#shorts {query}"
    return query


def extract_metadata_from_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse flat search entry into standardized Short metadata."""
    if not entry or not entry.get("id"):
        return None

    duration = entry.get("duration")
    # Shorts are strictly <= 60s (with a 5s tolerance buffer for edge-case uploads).
    # If duration is 0 or None, check title or accept candidate.
    if duration is not None and duration > 65:
        return None

    video_id = entry["id"]
    title = entry.get("title") or "Untitled Short"
    channel = entry.get("channel") or entry.get("uploader") or "Unknown"
    views = entry.get("view_count") or 0
    likes = entry.get("like_count") or 0
    comments = entry.get("comment_count") or 0
    thumbnail = entry.get("thumbnail") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

    return {
        "id": video_id,
        "title": title,
        "channel": channel,
        "views": views,
        "likes": likes,
        "comments": comments,
        "duration": duration or 0,
        "original_url": f"https://www.youtube.com/shorts/{video_id}",
        "thumbnail_url": thumbnail,
    }


def search_top_shorts_sync(query: str, limit: int = 10, search_depth: Optional[int] = None) -> List[Dict[str, Any]]:
    """Synchronously search YouTube for top performing Shorts."""
    search_query = clean_query_term(query)
    depth = search_depth or max(35, limit * 4)
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "default_search": f"ytsearch{depth}",
    }

    results: List[Dict[str, Any]] = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"ytsearch{search_depth}:{search_query}", download=False)
            entries = info.get("entries", []) if info else []
            for item in entries:
                parsed = extract_metadata_from_entry(item)
                if parsed:
                    results.append(parsed)
        except Exception as err:
            logger.error(f"Error extracting shorts info for query '{query}': {err}")

    # Rank by view count descending, secondary by likes
    results.sort(key=lambda x: (x.get("views") or 0, x.get("likes") or 0), reverse=True)
    return results[:limit]


async def search_top_shorts(query: str, limit: int = 10, search_depth: int = 40) -> List[Dict[str, Any]]:
    """Asynchronously search YouTube for top performing Shorts."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, search_top_shorts_sync, query, limit, search_depth)


def download_short_sync(video_id: str, output_dir: str) -> str:
    """Download single Short video into output directory."""
    os.makedirs(output_dir, exist_ok=True)
    output_template = os.path.join(output_dir, f"{video_id}.%(ext)s")
    video_url = f"https://www.youtube.com/shorts/{video_id}"

    ydl_opts = {
        # Prefer H.264/AVC streams to avoid ultra-slow AV1 software decoding in FFmpeg
        "format": "bestvideo[vcodec^=avc1][height<=1080]+bestaudio[ext=m4a]/bestvideo[vcodec^=avc][height<=1080]+bestaudio[ext=m4a]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

    expected_path = os.path.join(output_dir, f"{video_id}.mp4")
    if os.path.exists(expected_path):
        return expected_path

    # Check if downloaded with another extension and convert/return
    for fname in os.listdir(output_dir):
        if fname.startswith(video_id) and fname.endswith((".mp4", ".mkv", ".webm")):
            return os.path.join(output_dir, fname)

    raise FileNotFoundError(f"Downloaded video file not found for ID: {video_id}")


async def download_short(video_id: str, output_dir: str) -> str:
    """Asynchronously download single Short video."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, download_short_sync, video_id, output_dir)
