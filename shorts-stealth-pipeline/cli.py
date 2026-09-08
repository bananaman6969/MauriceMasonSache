"""Command-line interface for the Shorts Stealth Pipeline."""

import os
import sys
import asyncio
import argparse
import logging
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from core.database import (
    init_db_sync,
    init_db,
    is_video_seen,
    upsert_discovered,
    mark_downloaded,
    mark_processed,
    mark_failed,
    list_videos,
    get_video,
)
from core.scraper import search_top_shorts, download_short
from core.processor import process_video
from core.ffmpeg_manager import get_ffmpeg_paths

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("shorts_cli")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "catalog.db")
RAW_DIR = os.path.join(BASE_DIR, "output", "raw")
PROCESSED_DIR = os.path.join(BASE_DIR, "output", "processed")


def ensure_dirs():
    """Ensure data and output directories exist."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    init_db_sync(DB_PATH)


async def handle_search(args):
    """Search for top performing Shorts."""
    print(f"Searching top Shorts for: '{args.query}' (limit: {args.limit})...")
    shorts = await search_top_shorts(args.query, limit=args.limit)
    if not shorts:
        print("No Shorts found matching query.")
        return

    print(f"\nFound {len(shorts)} top-performing Shorts:")
    print("-" * 75)
    for idx, s in enumerate(shorts, 1):
        print(f"[{idx}] {s['title'][:50]}")
        print(f"    ID: {s['id']} | Channel: {s['channel']} | Views: {s['views']:,} | Likes: {s['likes']:,}")
        print(f"    URL: {s['original_url']}")
        await upsert_discovered(DB_PATH, s)
    print("-" * 75)


async def handle_process_single(video_id: str, preset: str, mirror: bool):
    """Download and apply anti-detection noise to a single Short."""
    print(f"\nProcessing Short ID: {video_id}")
    raw_path = os.path.join(RAW_DIR, f"{video_id}.mp4")
    processed_path = os.path.join(PROCESSED_DIR, f"{video_id}_stealth.mp4")

    if not os.path.exists(raw_path):
        print("Downloading raw Short...")
        raw_path = await download_short(video_id, RAW_DIR)
        await mark_downloaded(DB_PATH, video_id, raw_path)
        print(f"Raw video saved: {raw_path}")

    print(f"Applying '{preset}' anti-detection noise perturbation...")
    params = await process_video(
        input_path=raw_path,
        output_path=processed_path,
        preset=preset,
        mirror=mirror,
    )
    await mark_processed(DB_PATH, video_id, processed_path, params)
    print(f"[SUCCESS] Obfuscated video generated: {processed_path}")
    print(f"Perturbation parameters applied: speed={params['speed']}x, zoom={params['zoom']}x, noise={params['noise_sigma']}")
    return processed_path


async def handle_auto(args):
    """Execute end-to-end search, download, and anti-detection processing."""
    print(f"Starting automated stealth pipeline for: '{args.query}'")
    shorts = await search_top_shorts(args.query, limit=args.limit)
    if not shorts:
        print("No Shorts found.")
        return

    for idx, s in enumerate(shorts, 1):
        vid = s["id"]
        print(f"\n--- [{idx}/{len(shorts)}] {s['title']} ({vid}) ---")
        await upsert_discovered(DB_PATH, s)
        try:
            await handle_process_single(vid, preset=args.preset, mirror=args.mirror)
        except Exception as err:
            logger.error(f"Failed to process video {vid}: {err}")
            await mark_failed(DB_PATH, vid, str(err))

    print(f"\n[DONE] Finished automated batch! Processed videos are in: {PROCESSED_DIR}")


async def handle_list(args):
    """List cataloged videos."""
    videos = await list_videos(DB_PATH, limit=args.limit, status_filter=args.status)
    if not videos:
        print("No videos found in catalog.")
        return

    print(f"\nCatalog Videos ({len(videos)}):")
    print("-" * 80)
    for v in videos:
        status_str = f"[{v['status'].upper()}]"
        print(f"{status_str:<12} {v['id']} | Views: {v['views']:,} | {v['title'][:45]}")
        if v.get("processed_path"):
            print(f"             Output: {v['processed_path']}")
    print("-" * 80)


def main():
    """Main CLI entrypoint."""
    ensure_dirs()
    get_ffmpeg_paths()

    parser = argparse.ArgumentParser(description="YouTube Shorts Automated Stealth Pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # search
    p_search = subparsers.add_parser("search", help="Search top performing Shorts")
    p_search.add_argument("--query", "-q", required=True, help="Topic or keyword to search")
    p_search.add_argument("--limit", "-l", type=int, default=10, help="Number of results")

    # auto
    p_auto = subparsers.add_parser("auto", help="Automated search, download, and obfuscation")
    p_auto.add_argument("--query", "-q", required=True, help="Topic or keyword to search")
    p_auto.add_argument("--limit", "-l", type=int, default=5, help="Number of videos to process")
    p_auto.add_argument("--preset", "-p", choices=["subtle", "moderate", "aggressive"], default="subtle")
    p_auto.add_argument("--mirror", action="store_true", default=True, help="Enable horizontal flip")

    # process
    p_proc = subparsers.add_parser("process", help="Process a specific Short by ID")
    p_proc.add_argument("--id", required=True, help="YouTube Video ID")
    p_proc.add_argument("--preset", choices=["subtle", "moderate", "aggressive"], default="subtle")
    p_proc.add_argument("--mirror", action="store_true", default=True, help="Enable horizontal flip")

    # list
    p_list = subparsers.add_parser("list", help="List cataloged videos")
    p_list.add_argument("--status", choices=["discovered", "downloaded", "processed", "failed"], default=None)
    p_list.add_argument("--limit", type=int, default=50)

    args = parser.parse_args()

    if args.command == "search":
        asyncio.run(handle_search(args))
    elif args.command == "auto":
        asyncio.run(handle_auto(args))
    elif args.command == "process":
        asyncio.run(handle_process_single(args.id, args.preset, args.mirror))
    elif args.command == "list":
        asyncio.run(handle_list(args))


if __name__ == "__main__":
    main()
