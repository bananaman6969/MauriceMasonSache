"""Headless Command-Line Interface for Reddit Story Shorts Generator."""

import os
import argparse
import asyncio
import logging
from core.ffmpeg_manager import get_ffmpeg_paths
from core.scraper import (
    DEFAULT_SUBREDDITS,
    fetch_subreddit_posts,
    fetch_post_by_url,
)
from core.tts import CURATED_VOICES, generate_speech_with_timings
from core.subtitles import generate_karaoke_ass
from core.title_card import generate_reddit_title_card
from core.gameplay import (
    GAMEPLAY_PRESETS,
    get_gameplay_dir,
    list_available_gameplay_videos,
    download_youtube_gameplay,
    get_random_slice,
)
from core.audio_mixer import list_available_music_tracks, get_music_dir
from core.story_splitter import split_story_into_parts
from core.composer import render_short_video

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger("cli")


async def render_from_post(post: dict, args):
    """Render a post into a short vertical video."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(base_dir, "output")
    temp_dir = os.path.join(base_dir, "temp")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(temp_dir, exist_ok=True)

    # 1. Determine Parts
    if args.split:
        parts = split_story_into_parts(
            title=post["title"],
            body=post["body"],
            max_duration_seconds=args.max_duration,
        )
    else:
        full_script = f"{post['title']}. {post['body']}".strip()
        parts = [{
            "part": 1,
            "total_parts": 1,
            "part_title": post["title"],
            "script": full_script,
        }]

    # 2. Locate Gameplay
    gameplay_dir = get_gameplay_dir()
    available = list_available_gameplay_videos()
    gameplay_path = None
    if available:
        gameplay_path = available[0]["path"]
    else:
        logger.info("No local gameplay video found in assets/gameplay/. Creating default clip...")
        fallback_path = os.path.join(gameplay_dir, "default_gameplay.mp4")
        if not os.path.exists(fallback_path):
            from tests.test_composer import create_mock_gameplay_clip
            create_mock_gameplay_clip(fallback_path, duration=300)
        gameplay_path = fallback_path

    # 3. Locate BGM
    bgm_path = None
    if args.bgm:
        tracks = list_available_music_tracks()
        if tracks:
            bgm_path = tracks[0]["path"]

    total_parts = len(parts)
    logger.info(f"Rendering {total_parts} part(s) for story: {post['title']}")

    for p in parts:
        part_num = p["part"]
        part_title = p["part_title"]
        script = p["script"]

        logger.info(f"--- Processing Part {part_num}/{total_parts} ---")
        part_id = f"cli_{part_num}"
        voice_path = os.path.join(temp_dir, f"{part_id}_voice.mp3")
        sub_path = os.path.join(temp_dir, f"{part_id}_sub.ass")
        card_path = os.path.join(temp_dir, f"{part_id}_card.png")

        # Synthesize Voice
        logger.info(f"Synthesizing voice using {args.voice}...")
        tts_res = await generate_speech_with_timings(
            text=script,
            output_path=voice_path,
            voice=args.voice,
        )

        # Generate Subtitles
        generate_karaoke_ass(tts_res.words, sub_path)

        # Generate Title Card
        if not args.no_card:
            generate_reddit_title_card(
                subreddit=post["subreddit"],
                author=post["author"],
                title=part_title,
                score=post.get("score", 10000),
                num_comments=post.get("num_comments", 500),
                output_path=card_path,
            )

        # Calculate random slice
        start_time, _ = get_random_slice(gameplay_path, tts_res.duration)

        slug = "".join(c for c in part_title if c.isalnum() or c in (" ", "_", "-")).rstrip()
        slug = slug.replace(" ", "_")[:30]
        out_name = f"{slug}_part{part_num}.mp4"
        out_file = os.path.join(output_dir, out_name)

        logger.info(f"Compositing video to: {out_file}")
        render_short_video(
            gameplay_path=gameplay_path,
            voice_path=voice_path,
            subtitles_path=sub_path,
            output_path=out_file,
            duration=tts_res.duration,
            start_time=start_time,
            title_card_path=card_path if not args.no_card else None,
            bgm_path=bgm_path,
            progress_callback=lambda pct: print(f"Progress: {pct:.1f}%\r", end=""),
        )
        print()
        logger.info(f"[SUCCESS] Part {part_num} rendered successfully: {out_file}")


def main():
    parser = argparse.ArgumentParser(description="Reddit Story Shorts Generator CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Command: list-subs
    subparsers.add_parser("list-subs", help="List default story subreddits")

    # Command: fetch
    fetch_p = subparsers.add_parser("fetch", help="Browse stories from a subreddit")
    fetch_p.add_argument("--sub", default="AmItheAsshole", help="Subreddit name")
    fetch_p.add_argument("--sort", default="hot", choices=["hot", "top", "new"], help="Sort method")
    fetch_p.add_argument("--limit", type=int, default=5, help="Number of posts")

    # Command: render
    render_p = subparsers.add_parser("render", help="Render a story into a vertical short video")
    render_p.add_argument("--url", help="Direct Reddit post URL")
    render_p.add_argument("--sub", default="AmItheAsshole", help="Subreddit name to auto-pick top post")
    render_p.add_argument("--voice", default="en-US-ChristopherNeural", help="Edge-TTS voice ID")
    render_p.add_argument("--split", action="store_true", help="Auto-split long stories into multiple parts")
    render_p.add_argument("--max-duration", type=int, default=60, help="Max duration in seconds per part")
    render_p.add_argument("--bgm", action="store_true", help="Include background music")
    render_p.add_argument("--no-card", action="store_true", help="Disable Reddit title card overlay")

    # Command: gameplay
    subparsers.add_parser("gameplay", help="List available gameplay clips and presets")

    args = parser.parse_args()

    if args.command == "list-subs":
        print("\nAvailable Story Subreddits:")
        for s in DEFAULT_SUBREDDITS:
            print(f" - r/{s}")
        print()

    elif args.command == "fetch":
        print(f"\nFetching {args.limit} posts from r/{args.sub} ({args.sort})...\n")
        posts = fetch_subreddit_posts(args.sub, sort=args.sort, limit=args.limit)
        for idx, p in enumerate(posts, 1):
            print(f"[{idx}] {p['title']}")
            print(f"    Author: u/{p['author']} | Score: {p['score']} | Est. Duration: {p['est_duration_seconds']}s")
            print(f"    URL: {p['permalink']}\n")

    elif args.command == "gameplay":
        videos = list_available_gameplay_videos()
        print("\nLocal Gameplay Videos in assets/gameplay/:")
        if not videos:
            print("  (None found - auto-download via presets or dashboard)")
        for v in videos:
            print(f" - {v['filename']} ({v['duration']:.1f}s, {v['width']}x{v['height']})")

        print("\nRecommended YouTube Presets:")
        for preset in GAMEPLAY_PRESETS:
            print(f" - [{preset['category']}] {preset['title']}: {preset['url']}")
        print()

    elif args.command == "render":
        if args.url:
            logger.info(f"Fetching story from URL: {args.url}")
            post = fetch_post_by_url(args.url)
        else:
            logger.info(f"Auto-fetching top story from r/{args.sub}...")
            posts = fetch_subreddit_posts(args.sub, sort="hot", limit=3)
            if not posts:
                print("No stories found.")
                return
            post = posts[0]

        asyncio.run(render_from_post(post, args))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
