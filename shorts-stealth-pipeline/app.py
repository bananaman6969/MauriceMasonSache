"""FastAPI Application Server for Shorts Stealth Pipeline."""

import os
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List, Set
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi import Request
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from core.database import (
    init_db_sync,
    init_db,
    upsert_discovered,
    mark_downloaded,
    mark_processed,
    mark_failed,
    list_videos,
    get_video,
    delete_video,
)
from core.scraper import search_top_shorts, download_short
from core.processor import process_video, terminate_all_ffmpeg_processes
from core.ffmpeg_manager import get_ffmpeg_paths

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("shorts_server")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_RAW = os.path.join(BASE_DIR, "output", "raw")
OUTPUT_PROCESSED = os.path.join(BASE_DIR, "output", "processed")
DB_PATH = os.path.join(DATA_DIR, "catalog.db")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(OUTPUT_RAW, exist_ok=True)
os.makedirs(OUTPUT_PROCESSED, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "static", "js"), exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "templates"), exist_ok=True)

# Initialize database
init_db_sync(DB_PATH)
# Ensure ffmpeg
get_ffmpeg_paths()

app = FastAPI(title="Shorts Stealth Pipeline", version="1.0.0")

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# In-memory event queue for SSE broadcasting
event_queue: asyncio.Queue = asyncio.Queue()

# Task management & concurrency limit to protect system performance
pipeline_semaphore = asyncio.Semaphore(1)
active_pipeline_tasks: Set[asyncio.Task] = set()
stop_requested = False


def queue_pipeline_task(video: Dict[str, Any], preset: str, mirror: bool) -> asyncio.Task:
    """Queue a video processing task with active tracking."""
    global stop_requested
    stop_requested = False
    task = asyncio.create_task(run_pipeline_task(video, preset, mirror))
    active_pipeline_tasks.add(task)
    task.add_done_callback(active_pipeline_tasks.discard)
    return task


async def broadcast_event(data: Dict[str, Any]):
    """Broadcast status message to all connected SSE clients."""
    await event_queue.put(json.dumps(data))


class SearchRequest(BaseModel):
    query: str
    limit: int = 10
    auto_process: bool = False
    preset: str = "subtle"
    mirror: bool = False


class ProcessRequest(BaseModel):
    video_id: str
    preset: str = "subtle"
    mirror: bool = False


@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    """Serve single-page web dashboard."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/api/events")
async def sse_stream(request: Request):
    """Real-time SSE event stream for pipeline updates."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                # Wait for next event or send keepalive
                data = await asyncio.wait_for(event_queue.get(), timeout=15.0)
                yield {"data": data}
            except asyncio.TimeoutError:
                yield {"data": json.dumps({"status": "keepalive"})}

    return EventSourceResponse(event_generator())


@app.get("/api/videos")
async def get_videos_catalog(status: Optional[str] = None, limit: int = 50):
    """Fetch video records from database catalog."""
    videos = await list_videos(DB_PATH, limit=limit, status_filter=status)
    return {"videos": videos}


async def run_pipeline_task(video: Dict[str, Any], preset: str, mirror: bool):
    """Background task to download and apply anti-detection noise with concurrency control."""
    global stop_requested
    vid = video["id"]
    if stop_requested:
        return

    try:
        async with pipeline_semaphore:
            if stop_requested:
                return

            await broadcast_event({
                "status": "processing",
                "step": "Downloading",
                "message": f"Downloading Short: {video['title'][:30]}...",
                "details": f"ID: {vid}",
            })

            raw_path = os.path.join(OUTPUT_RAW, f"{vid}.mp4")
            if not os.path.exists(raw_path):
                raw_path = await download_short(vid, OUTPUT_RAW)

            if stop_requested:
                return

            await mark_downloaded(DB_PATH, vid, raw_path)

            await broadcast_event({
                "status": "processing",
                "step": "Obfuscating",
                "message": f"Applying anti-detection perturbations to {vid}...",
                "details": f"Preset: {preset}",
            })

            processed_path = os.path.join(OUTPUT_PROCESSED, f"{vid}_stealth.mp4")
            params = await process_video(
                input_path=raw_path,
                output_path=processed_path,
                preset=preset,
                mirror=mirror,
            )

            await mark_processed(DB_PATH, vid, processed_path, params)
            await broadcast_event({
                "status": "completed",
                "step": "Done",
                "message": f"Obfuscated video ready: {video['title'][:30]}",
                "details": f"Saved to {os.path.basename(processed_path)}",
            })

    except asyncio.CancelledError:
        logger.info(f"Pipeline task for {vid} cancelled.")
        await broadcast_event({
            "status": "stopped",
            "step": "Stopped",
            "message": f"Processing stopped for {vid}",
            "details": "Halted by user",
        })
    except Exception as err:
        if stop_requested:
            logger.info(f"Task for {vid} aborted cleanly on stop request.")
            return
        logger.error(f"Pipeline error for video {vid}: {err}")
        await mark_failed(DB_PATH, vid, str(err))
        await broadcast_event({
            "status": "error",
            "step": "Failed",
            "message": f"Error processing {vid}: {str(err)}",
            "details": str(err),
        })


@app.post("/api/search")
async def search_shorts_endpoint(payload: SearchRequest):
    """Search YouTube for top-performing Shorts and optionally auto-process."""
    await broadcast_event({
        "status": "searching",
        "step": "Searching",
        "message": f"Scraping top Shorts for query: '{payload.query}'",
        "details": f"Limit: {payload.limit}",
    })

    shorts = await search_top_shorts(payload.query, limit=payload.limit)

    for item in shorts:
        await upsert_discovered(DB_PATH, item)

    if payload.auto_process and shorts:
        for item in shorts:
            queue_pipeline_task(item, payload.preset, payload.mirror)

    return {"success": True, "count": len(shorts), "videos": shorts}


@app.post("/api/process")
async def process_video_endpoint(payload: ProcessRequest):
    """Trigger download and anti-detection processing for a specific Short."""
    video = await get_video(DB_PATH, payload.video_id)
    if not video:
        video = {
            "id": payload.video_id,
            "title": f"Short {payload.video_id}",
            "original_url": f"https://www.youtube.com/shorts/{payload.video_id}",
        }
        await upsert_discovered(DB_PATH, video)

    queue_pipeline_task(video, payload.preset, payload.mirror)
    return {"success": True, "message": "Processing queued in background"}


@app.post("/api/stop")
async def stop_all_processing_endpoint():
    """Immediately halt all active downloads, video obfuscations, and background tasks."""
    global stop_requested
    stop_requested = True

    # 1. Instantly kill all running FFmpeg processes
    terminated_procs = terminate_all_ffmpeg_processes()

    # 2. Cancel all queued/active asyncio pipeline tasks
    cancelled_tasks = 0
    for task in list(active_pipeline_tasks):
        if not task.done():
            task.cancel()
            cancelled_tasks += 1
    active_pipeline_tasks.clear()

    logger.info(f"Stop requested: cancelled {cancelled_tasks} tasks, killed {terminated_procs} FFmpeg processes.")

    # 3. Broadcast stopped event to UI
    await broadcast_event({
        "status": "stopped",
        "step": "Stopped",
        "message": "All processing was stopped by user.",
        "details": f"Terminated {cancelled_tasks} task(s) and {terminated_procs} process(es).",
    })

    return {
        "success": True,
        "message": "All processing stopped successfully",
        "cancelled_tasks": cancelled_tasks,
        "terminated_processes": terminated_procs,
    }


@app.get("/api/stream/{video_type}/{video_id}")
async def stream_video(video_type: str, video_id: str):
    """Stream raw or processed MP4 video for HTML5 playback."""
    video = await get_video(DB_PATH, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    target_path = video.get("processed_path") if video_type == "processed" else video.get("raw_path")
    if not target_path or not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    return FileResponse(target_path, media_type="video/mp4")


@app.get("/api/download/{video_id}")
async def download_video_file(video_id: str):
    """Download the obfuscated video file as an attachment."""
    video = await get_video(DB_PATH, video_id)
    if not video or not video.get("processed_path"):
        raise HTTPException(status_code=404, detail="Processed video not available")

    file_path = video["processed_path"]
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Processed file missing from disk")

    filename = f"{video_id}_stealth.mp4"
    return FileResponse(
        file_path,
        media_type="video/mp4",
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.delete("/api/videos/{video_id}")
async def delete_video_record(video_id: str):
    """Remove video from catalog and delete local files."""
    video = await get_video(DB_PATH, video_id)
    if video:
        for key in ["raw_path", "processed_path"]:
            path = video.get(key)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        await delete_video(DB_PATH, video_id)
        return {"success": True}
    raise HTTPException(status_code=404, detail="Video not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
