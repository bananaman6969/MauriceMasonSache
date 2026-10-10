"""Local countryball video studio. Run: python app.py."""
import asyncio
import io
import json
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from engine import Battle, COUNTRIES, FINALE_SECONDS, FPS, Renderer, Settings, export_video
from audio import KINDS, samples, wav_bytes

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / 'output'
app = FastAPI(title='Countryball Dagger Arena')
app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')
app.mount('/flags', StaticFiles(directory=ROOT / 'assets' / 'flags'), name='flags')
jobs = {}
export_lock = threading.Lock()


@app.get('/')
def index():
    return FileResponse(ROOT / 'static' / 'index.html')


@app.get('/api/countries')
def countries():
    return COUNTRIES


@app.get('/api/preview')
def preview(settings: str = Query(max_length=2000)):
    try:
        config = Settings.model_validate_json(settings)
    except ValidationError as error:
        raise HTTPException(422, 'Invalid battle settings') from error

    async def stream():
        battle, renderer = Battle(config), Renderer()
        deadline = time.monotonic()
        for frame in range(config.duration * FPS + round(FINALE_SECONDS * FPS)):
            if battle.finished or (frame >= config.duration * FPS and battle.resolved_at is None):
                break
            buffer = io.BytesIO()
            renderer.render(battle).save(buffer, format='JPEG', quality=95, subsampling=0)
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.getvalue() + b'\r\n'
            battle.advance_frame()
            deadline += 1 / FPS
            await asyncio.sleep(max(0, deadline - time.monotonic()))
        yield b'--frame--\r\n'

    return StreamingResponse(stream(), media_type='multipart/x-mixed-replace; boundary=frame',
                             headers={'Cache-Control': 'no-store'})


@app.get('/api/sounds/{kind}')
def sound_clip(kind: str):
    if kind not in KINDS:
        raise HTTPException(404, 'Unknown sound')
    return Response(wav_bytes(samples(kind)), media_type='audio/wav', headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/api/preview-events')
def preview_events(settings: str = Query(max_length=2000)):
    try:
        config = Settings.model_validate_json(settings)
    except ValidationError as error:
        raise HTTPException(422, 'Invalid battle settings') from error

    async def stream():
        battle = Battle(config)
        cursor = 0
        deadline = time.monotonic()
        for frame in range(config.duration * FPS + round(FINALE_SECONDS * FPS)):
            if battle.finished or (frame >= config.duration * FPS and battle.resolved_at is None):
                break
            battle.advance_frame()
            events = battle.sound_events[cursor:]
            cursor = len(battle.sound_events)
            if events:
                yield f'data: {json.dumps(events)}\n\n'
            deadline += 1 / FPS
            await asyncio.sleep(max(0, deadline - time.monotonic()))
        yield 'event: done\ndata: {}\n\n'

    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})


@app.post('/api/export', status_code=202)
def export(settings: Settings):
    if not export_lock.acquire(blocking=False):
        raise HTTPException(409, 'An export is already running. Please wait for it to finish.')
    job_id = uuid.uuid4().hex
    # Retain a bounded number of in-memory status records. Videos stay on disk.
    while len(jobs) >= 50:
        jobs.pop(next(iter(jobs)))
    jobs[job_id] = {'status': 'rendering', 'progress': 0}

    def worker():
        try:
            OUTPUT.mkdir(exist_ok=True)
            export_video(settings, OUTPUT / f'{job_id}.mp4',
                         lambda value: jobs[job_id].update(progress=value))
            jobs[job_id].update(status='complete', download=f'/api/download/{job_id}')
        except Exception as error:
            jobs[job_id].update(status='failed', error=str(error))
        finally:
            export_lock.release()

    threading.Thread(target=worker, daemon=True).start()
    return {'id': job_id, **jobs[job_id]}


@app.get('/api/jobs/{job_id}')
def status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, 'Unknown export')
    return jobs[job_id]


@app.get('/api/download/{job_id}')
def download(job_id: str):
    if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise HTTPException(404, 'Video not found')
    path = OUTPUT / f'{job_id}.mp4'
    if not path.is_file() or jobs.get(job_id, {}).get('status') == 'rendering':
        raise HTTPException(404, 'Video not ready')
    return FileResponse(path, media_type='video/mp4', filename=f'countryball-battle-{job_id[:8]}.mp4')


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8010)
