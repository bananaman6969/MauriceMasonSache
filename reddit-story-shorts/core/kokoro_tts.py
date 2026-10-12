"""Optional, local Kokoro speech with its model-generated token timestamps."""
import asyncio
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import sys

MODEL_DIR = Path(__file__).resolve().parents[1] / "cache" / "kokoro"
VOICES = [
    {"id": f"kokoro:{code}", "name": name, "locale": locale, "engine": "kokoro"}
    for code, name, locale in [
        ("af_heart", "Heart · American female", "en-US"),
        ("af_bella", "Bella · American female", "en-US"),
        ("am_fenrir", "Fenrir · American male", "en-US"),
        ("am_adam", "Adam · American male", "en-US"),
        ("bf_emma", "Emma · British female", "en-GB"),
        ("bm_george", "George · British male", "en-GB"),
    ]
]
_lock = threading.Lock()
_pipelines = {}
_voice_packs = {}


def configure_runtime():
    # Optional external package directory avoids syncing thousands of runtime
    # files when the project lives in OneDrive. Normal venv installs also work.
    directory = os.environ.get("KOKORO_SITE_PACKAGES")
    if not directory and os.name == "nt":
        directory = str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RedditStoryShorts" / "kokoro-packages")
    if directory and (Path(directory) / "kokoro" / "__init__.py").is_file() and directory not in sys.path:
        sys.path.insert(0, directory)


def installed():
    configure_runtime()
    return all(importlib.util.find_spec(name) is not None for name in ("kokoro", "soundfile", "espeakng_loader"))


def model_file(filename):
    from huggingface_hub import hf_hub_download
    from huggingface_hub.errors import LocalEntryNotFoundError
    try:
        return hf_hub_download(repo_id="hexgrad/Kokoro-82M", filename=filename, local_files_only=True)
    except LocalEntryNotFoundError:
        return hf_hub_download(repo_id="hexgrad/Kokoro-82M", filename=filename)


def pipeline_for(language):
    configure_runtime()
    if language not in _pipelines:
        # Keep downloads in the application's ignored cache, portable with the app.
        os.environ.setdefault("HF_HOME", str(MODEL_DIR))
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        import espeakng_loader
        from phonemizer.backend.espeak.wrapper import EspeakWrapper
        EspeakWrapper.set_library(espeakng_loader.get_library_path())
        EspeakWrapper.set_data_path(espeakng_loader.get_data_path())
        os.environ.setdefault("ESPEAK_DATA_PATH", espeakng_loader.get_data_path())
        import torch
        from kokoro import KPipeline, KModel
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        model = next(iter(_pipelines.values())).model if _pipelines else KModel(
            repo_id="hexgrad/Kokoro-82M", config=model_file("config.json"),
            model=model_file("kokoro-v1_0.pth")).to("cpu").eval()
        _pipelines[language] = KPipeline(lang_code=language, model=model, device="cpu", repo_id="hexgrad/Kokoro-82M")
    return _pipelines[language]


def token_timings(tokens, offset, duration):
    from core.tts import WordTiming
    words = []
    text, start, end = "", None, None
    def flush():
        if text.strip() and re.search(r"\w", text):
            if start is None or end is None:
                raise RuntimeError(f"Kokoro could not time the word {text!r}. Please revise its spelling.")
            if end > start:
                words.append(WordTiming(text.strip(), round(offset + start, 3), round(offset + end, 3)))
    for token in tokens or []:
        text += token.text
        token_start = getattr(token, "start_ts", None)
        token_end = getattr(token, "end_ts", None)
        # Punctuation can have model duration representing silence. Keep its
        # spelling, but do not extend a word's highlight into that pause.
        if token_start is not None and token_end is not None and re.search(r"\w", token.text):
            start = max(0, min(duration, token_start)) if start is None else start
            end = max(0, min(duration, token_end))
        if token.whitespace:
            flush()
            text, start, end = "", None, None
    flush()
    return words


def synthesize(text, output_path, voice, rate, volume, pitch, cancelled):
    from core.tts import TTSResult
    if voice not in {v["id"] for v in VOICES}:
        raise ValueError("Unknown Kokoro voice")
    if not installed():
        raise RuntimeError("Kokoro is not installed. Install requirements-kokoro.txt to use local voices.")
    if pitch != "+0Hz":
        raise ValueError("Kokoro does not support pitch adjustment")
    if not re.fullmatch(r"[+-]\d+%", rate) or not re.fullmatch(r"[+-]\d+%", volume):
        raise ValueError("Invalid speech rate or volume")
    speed = 1 + int(rate[:-1]) / 100
    if not .5 <= speed <= 2:
        raise ValueError("Kokoro speed must be between 0.5x and 2x")
    import numpy as np
    import soundfile as sf
    from core.ffmpeg_manager import get_ffmpeg_paths
    while not _lock.acquire(timeout=.1):
        if cancelled.is_set():
            raise RuntimeError("Speech generation cancelled")
    try:
        if cancelled.is_set():
            raise RuntimeError("Speech generation cancelled")
        code = voice.split(":", 1)[1]
        pipeline = pipeline_for(code[0])
        if code not in _voice_packs:
            import torch
            _voice_packs[code] = torch.load(model_file(f"voices/{code}.pt"), map_location="cpu", weights_only=True)
        chunks, words, sample_count = [], [], 0
        for result in pipeline(text, voice=_voice_packs[code], speed=speed):
            if cancelled.is_set():
                raise RuntimeError("Speech generation cancelled")
            audio = result.audio.detach().cpu().numpy().reshape(-1)
            duration = len(audio) / 24000
            words.extend(token_timings(result.tokens, sample_count / 24000, duration))
            chunks.append(audio)
            sample_count += len(audio)
        if not chunks or not words:
            raise RuntimeError("Kokoro returned no timed speech")
        audio = np.clip(np.concatenate(chunks) * max(0, 1 + int(volume[:-1]) / 100), -1, 1)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        with tempfile.TemporaryDirectory(dir=os.path.dirname(os.path.abspath(output_path))) as temp:
            wave = os.path.join(temp, "speech.wav")
            sf.write(wave, audio, 24000)
            ffmpeg, _ = get_ffmpeg_paths()
            subprocess.run([ffmpeg, "-y", "-i", wave, "-c:a", "libmp3lame", "-b:a", "192k", output_path],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        return TTSResult(output_path, sample_count / 24000, words)
    finally:
        _lock.release()


async def generate_local_speech(text, output_path, voice, rate, volume, pitch):
    cancelled = threading.Event()
    try:
        return await asyncio.to_thread(synthesize, text, output_path, voice, rate, volume, pitch, cancelled)
    except asyncio.CancelledError:
        cancelled.set()
        raise
