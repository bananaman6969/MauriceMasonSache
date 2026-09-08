"""FastAPI Web Server for Reddit Story Shorts Generator."""

import os
import uuid
import json
import asyncio
import logging
import shutil
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, BackgroundTasks, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel

from core.ffmpeg_manager import get_ffmpeg_paths
from core.scraper import (
    DEFAULT_SUBREDDITS,
    fetch_subreddit_posts,
    fetch_post_by_url,
    clean_story_text,
    estimate_duration_seconds,
)
from core.tts import CURATED_VOICES, generate_speech_with_timings, get_available_voices
from core.subtitles import generate_karaoke_ass, generate_srt_subtitles
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reddit_story_shorts")

# Initialize static FFmpeg paths on startup
get_ffmpeg_paths()

app = FastAPI(title="Reddit Story Shorts Generator", version="1.0.0")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TEMP_DIR = os.path.join(BASE_DIR, "temp")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

for d in [OUTPUT_DIR, TEMP_DIR, ASSETS_DIR, STATIC_DIR, TEMPLATES_DIR]:
    os.makedirs(d, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/output", StaticFiles(directory=OUTPUT_DIR), name="output")
app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

templates = Jinja2Templates(directory=TEMPLATES_DIR)

# In-memory render job state & cancellation tracking
render_jobs: Dict[str, Dict[str, Any]] = {}
active_render_processes: Dict[str, Any] = {}
cancelled_jobs: set[str] = set()


class PostByUrlRequest(BaseModel):
    url: str


class TTSPreviewRequest(BaseModel):
    text: str
    voice: str = "en-US-ChristopherNeural"
    rate: str = "+0%"


class SplitStoryRequest(BaseModel):
    title: str
    body: str
    max_duration_seconds: int = 60
    add_cta: bool = True


class RenderJobRequest(BaseModel):
    title: str
    body: str
    subreddit: str = "r/AmItheAsshole"
    author: str = "RedditUser"
    score: int = 15000
    num_comments: int = 1200
    voice: str = "en-US-ChristopherNeural"
    voice_rate: str = "+0%"
    gameplay_filename: Optional[str] = None
    bgm_filename: Optional[str] = None
    voice_volume: float = 1.25
    gameplay_volume: float = 0.10
    bgm_volume: float = 0.15
    show_title_card: bool = True
    split_parts: bool = False
    max_part_duration: int = 60


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Render the dashboard UI."""
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "subreddits": DEFAULT_SUBREDDITS,
            "gameplay_presets": GAMEPLAY_PRESETS,
        },
    )


@app.get("/api/subreddits")
async def get_subreddits():
    return {"subreddits": DEFAULT_SUBREDDITS}


@app.get("/api/reddit/posts")
async def get_subreddit_posts(
    subreddit: str = "AmItheAsshole",
    sort: str = "hot",
    timeframe: str = "day",
    limit: int = 25,
):
    try:
        posts = fetch_subreddit_posts(subreddit, sort=sort, timeframe=timeframe, limit=limit)
        return {"success": True, "posts": posts}
    except Exception as err:
        logger.error(f"Error fetching subreddit posts: {err}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(err)})


@app.post("/api/reddit/post-by-url")
async def get_post_by_url(req: PostByUrlRequest):
    try:
        post = fetch_post_by_url(req.url)
        return {"success": True, "post": post}
    except Exception as err:
        logger.error(f"Error fetching post by URL: {err}")
        return JSONResponse(status_code=400, content={"success": False, "error": str(err)})


@app.get("/api/voices")
async def list_voices():
    voices = await get_available_voices(locale_prefix="en-")
    return {"voices": voices}


@app.post("/api/tts/preview")
async def preview_tts(req: TTSPreviewRequest):
    try:
        snippet = req.text[:150]
        preview_filename = f"preview_{uuid.uuid4().hex[:8]}.mp3"
        preview_path = os.path.join(TEMP_DIR, preview_filename)

        await generate_speech_with_timings(
            text=snippet,
            output_path=preview_path,
            voice=req.voice,
            rate=req.rate,
        )
        return {"success": True, "preview_url": f"/static/temp/{preview_filename}"}
    except Exception as err:
        return JSONResponse(status_code=500, content={"success": False, "error": str(err)})


@app.get("/api/gameplay/list")
async def get_gameplay_list():
    videos = list_available_gameplay_videos()
    return {"videos": videos, "presets": GAMEPLAY_PRESETS}


@app.post("/api/gameplay/download")
async def download_gameplay_video(background_tasks: BackgroundTasks, url: str = Form(...), name: Optional[str] = Form(None)):
    def _download():
        try:
            download_youtube_gameplay(url, custom_name=name)
        except Exception as err:
            logger.error(f"Failed to download gameplay: {err}")

    background_tasks.add_task(_download)
    return {"success": True, "message": "Download started in background."}


@app.post("/api/gameplay/upload")
async def upload_gameplay_file(file: UploadFile = File(...)):
    gameplay_dir = get_gameplay_dir()
    save_path = os.path.join(gameplay_dir, file.filename)
    with open(save_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"success": True, "filename": file.filename}


@app.get("/api/music/list")
async def get_music_list():
    tracks = list_available_music_tracks()
    return {"tracks": tracks}


@app.post("/api/split-story")
async def split_story_endpoint(req: SplitStoryRequest):
    parts = split_story_into_parts(
        title=req.title,
        body=req.body,
        max_duration_seconds=req.max_duration_seconds,
        add_cta=req.add_cta,
    )
    return {"parts": parts}


async def _process_render_job(job_id: str, req: RenderJobRequest):
    """Background rendering worker."""
    job = render_jobs[job_id]
    try:
        # Determine story parts
        if req.split_parts:
            parts = split_story_into_parts(
                title=req.title,
                body=req.body,
                max_duration_seconds=req.max_part_duration,
            )
        else:
            full_script = f"{req.title}. {req.body}".strip()
            parts = [{
                "part": 1,
                "total_parts": 1,
                "part_title": req.title,
                "script": full_script,
            }]

        total_parts = len(parts)
        job["step"] = f"Synthesizing voiceover (0/{total_parts})..."
        job["progress"] = 5.0

        gameplay_dir = get_gameplay_dir()
        available_gameplay = list_available_gameplay_videos()

        # Find or use requested gameplay
        gameplay_path = None
        if req.gameplay_filename:
            candidate = os.path.join(gameplay_dir, req.gameplay_filename)
            if os.path.exists(candidate):
                gameplay_path = candidate

        if not gameplay_path and available_gameplay:
            gameplay_path = available_gameplay[0]["path"]

        # If still no gameplay, create a fallback animated background
        if not gameplay_path:
            fallback_path = os.path.join(gameplay_dir, "default_gameplay.mp4")
            if not os.path.exists(fallback_path):
                from tests.test_composer import create_mock_gameplay_clip
                create_mock_gameplay_clip(fallback_path, duration=300)
            gameplay_path = fallback_path

        # Find BGM if requested
        bgm_path = None
        if req.bgm_filename:
            music_dir = get_music_dir()
            candidate_bgm = os.path.join(music_dir, req.bgm_filename)
            if os.path.exists(candidate_bgm):
                bgm_path = candidate_bgm

        rendered_videos: List[Dict[str, Any]] = []

        for part_info in parts:
            if job_id in cancelled_jobs or job.get("status") == "cancelled":
                job["status"] = "cancelled"
                job["step"] = "Render stopped by user."
                return

            part_num = part_info["part"]
            part_title = part_info["part_title"]
            script = part_info["script"]

            part_id = f"{job_id}_p{part_num}"
            job["step"] = f"Part {part_num}/{total_parts}: Synthesizing speech..."
            job["progress"] = round(10.0 + ((part_num - 1) / total_parts) * 80.0, 1)

            part_voice_path = os.path.join(TEMP_DIR, f"{part_id}_voice.mp3")
            part_subtitles_path = os.path.join(TEMP_DIR, f"{part_id}_subtitles.ass")
            part_card_path = os.path.join(TEMP_DIR, f"{part_id}_card.png") if req.show_title_card else None

            # 1. Generate Voiceover & Timings
            tts_res = await generate_speech_with_timings(
                text=script,
                output_path=part_voice_path,
                voice=req.voice,
                rate=req.voice_rate,
            )

            if job_id in cancelled_jobs or job.get("status") == "cancelled":
                job["status"] = "cancelled"
                job["step"] = "Render stopped by user."
                return

            # 2. Generate Karaoke Subtitles
            generate_karaoke_ass(tts_res.words, part_subtitles_path)

            # 3. Generate Title Card for Part 1 (or each part)
            if req.show_title_card and part_card_path:
                generate_reddit_title_card(
                    subreddit=req.subreddit,
                    author=req.author,
                    title=part_title,
                    score=req.score,
                    num_comments=req.num_comments,
                    output_path=part_card_path,
                )

            # 4. Determine Gameplay Random Start Slice
            start_time, duration = get_random_slice(gameplay_path, tts_res.duration)

            # 5. Composite Video
            clean_title_slug = "".join(c for c in part_title if c.isalnum() or c in (" ", "_", "-")).rstrip()
            clean_title_slug = clean_title_slug.replace(" ", "_")[:30]
            output_filename = f"{clean_title_slug}_{part_id}.mp4"
            final_output_path = os.path.join(OUTPUT_DIR, output_filename)

            def progress_cb(pct: float):
                base = 15.0 + ((part_num - 1) / total_parts) * 80.0
                slice_span = 80.0 / total_parts
                job["progress"] = min(round(base + (pct / 100.0) * slice_span, 1), 99.0)
                job["step"] = f"Part {part_num}/{total_parts}: Rendering video ({pct:.0f}%)..."

            def is_cancelled_check() -> bool:
                return job_id in cancelled_jobs or job.get("status") == "cancelled"

            def register_proc(proc):
                active_render_processes[job_id] = proc

            try:
                render_short_video(
                    gameplay_path=gameplay_path,
                    voice_path=part_voice_path,
                    subtitles_path=part_subtitles_path,
                    output_path=final_output_path,
                    duration=tts_res.duration,
                    start_time=start_time,
                    title_card_path=part_card_path if req.show_title_card else None,
                    bgm_path=bgm_path,
                    voice_volume=req.voice_volume,
                    gameplay_volume=req.gameplay_volume,
                    bgm_volume=req.bgm_volume,
                    title_card_duration=3.5 if req.show_title_card else 0.0,
                    progress_callback=progress_cb,
                    is_cancelled=is_cancelled_check,
                    process_callback=register_proc,
                )
            finally:
                active_render_processes.pop(job_id, None)

            if job_id in cancelled_jobs or job.get("status") == "cancelled":
                job["status"] = "cancelled"
                job["step"] = "Render stopped by user."
                return

            rendered_videos.append({
                "part": part_num,
                "title": part_title,
                "filename": output_filename,
                "video_url": f"/output/{output_filename}",
                "duration": round(tts_res.duration, 1),
            })

        job["progress"] = 100.0
        job["step"] = "Completed successfully!"
        job["status"] = "completed"
        job["videos"] = rendered_videos

    except Exception as err:
        if job_id in cancelled_jobs or "cancelled" in str(err).lower():
            logger.info(f"Render job {job_id} cancelled by user.")
            job["status"] = "cancelled"
            job["step"] = "Render stopped by user."
            return

        logger.error(f"Render job {job_id} failed: {err}", exc_info=True)
        job["status"] = "failed"
        job["error"] = str(err)
        job["step"] = f"Failed: {err}"


@app.post("/api/render")
async def start_render_job(req: RenderJobRequest, background_tasks: BackgroundTasks):
    job_id = uuid.uuid4().hex[:10]
    render_jobs[job_id] = {
        "id": job_id,
        "status": "processing",
        "progress": 0.0,
        "step": "Initializing pipeline...",
        "videos": [],
        "error": None,
    }
    background_tasks.add_task(_process_render_job, job_id, req)
    return {"success": True, "job_id": job_id}


@app.post("/api/render/cancel/{job_id}")
async def cancel_render_job(job_id: str):
    cancelled_jobs.add(job_id)
    if job_id in render_jobs:
        render_jobs[job_id]["status"] = "cancelled"
        render_jobs[job_id]["step"] = "Render stopped by user."

    if job_id in active_render_processes:
        proc = active_render_processes[job_id]
        try:
            proc.kill()
        except Exception as err:
            logger.warning(f"Error terminating process for job {job_id}: {err}")

    return {"success": True, "message": "Render job stopped."}


@app.get("/api/render/status/{job_id}")
async def get_render_job_status(job_id: str):
    if job_id not in render_jobs:
        return JSONResponse(status_code=404, content={"success": False, "error": "Job not found"})
    return {"success": True, "job": render_jobs[job_id]}


@app.get("/api/render/stream/{job_id}")
async def stream_render_progress(job_id: str):
    """Server-Sent Events stream for real-time render tracking."""
    async def event_generator():
        while True:
            if job_id not in render_jobs:
                yield {"event": "error", "data": json.dumps({"error": "Job not found"})}
                break

            job = render_jobs[job_id]
            data = {
                "progress": job.get("progress", 0.0),
                "step": job.get("step", ""),
                "status": job.get("status", "processing"),
                "videos": job.get("videos", []),
                "error": job.get("error"),
            }
            yield {"event": "update", "data": json.dumps(data)}

            if job.get("status") in ("completed", "failed", "cancelled"):
                break

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@app.get("/api/videos")
async def list_rendered_videos():
    videos = []
    if os.path.exists(OUTPUT_DIR):
        for f in os.listdir(OUTPUT_DIR):
            if f.endswith(".mp4"):
                full_path = os.path.join(OUTPUT_DIR, f)
                videos.append({
                    "filename": f,
                    "video_url": f"/output/{f}",
                    "size_mb": round(os.path.getsize(full_path) / (1024 * 1024), 2),
                    "created_at": os.path.getmtime(full_path),
                })
    videos.sort(key=lambda x: x["created_at"], reverse=True)
    return {"videos": videos}


@app.delete("/api/videos/{filename}")
async def delete_rendered_video(filename: str):
    safe_name = os.path.basename(filename)
    target = os.path.join(OUTPUT_DIR, safe_name)
    if os.path.exists(target):
        os.remove(target)
        return {"success": True}
    raise HTTPException(status_code=404, detail="File not found")


def find_free_port(start_port: int = 8001, max_port: int = 8100) -> int:
    """Find the first available TCP port."""
    import socket
    for p in range(start_port, max_port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="Reddit Story Shorts Web Dashboard")
    parser.add_argument("--port", type=int, default=None, help="Port to bind (auto-detects free port if omitted)")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface")
    args = parser.parse_args()

    chosen_port = args.port or find_free_port(8001)
    print(f"\n==================================================")
    print(f"  Reddit Story Shorts Generator")
    print(f"  Server running at: http://{args.host}:{chosen_port}")
    print(f"==================================================\n")
    uvicorn.run("app:app", host=args.host, port=chosen_port, reload=False)

