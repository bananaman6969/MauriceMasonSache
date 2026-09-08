# Reddit Story Shorts Generator

An automated web dashboard and CLI pipeline that scrapes viral Reddit stories, synthesizes ultra-realistic voiceovers with word-by-word timestamps via `edge-tts`, overlays animated karaoke captions and a dark-mode Reddit post title card, and composites the video in 9:16 vertical format (1080x1920) over background gameplay footage with ducked audio.

---

## Features

- **Public Reddit Scraper**: Fetches trending/top stories from `r/AmItheAsshole`, `r/AskReddit`, `r/tifu`, `r/confession`, `r/TrueOffMyChest`, and custom Reddit post URLs without requiring Reddit API keys.
- **Edge-TTS Neural Voiceovers**: High-fidelity Microsoft neural voices (`Christopher`, `Guy`, `Jenny`, `Eric`, `Ryan`, `Ava`) with zero API credentials and native word-boundary event tracking.
- **TikTok-Style Karaoke Captions**: Burned-in `.ass` high-retention subtitles styled with bold fonts, dark stroke outlines, and active word highlighting in bright yellow (`#FFE600`).
- **Authentic Reddit Title Card**: Procedurally generates an anti-aliased dark-mode Reddit post header card displaying the subreddit badge, author, upvote count, and title during the video intro (fading out smoothly after 3.5s).
- **Interactive Script Editor & Story Splitter**: In-browser editing with dynamic word counts and duration estimation. Automatically splits long stories into sequential parts (e.g. Part 1, Part 2) with "Like & follow for Part 2" hooks.
- **Dual Gameplay Sourcing**: Drop local video files into `assets/gameplay/`, upload MP4s via the web dashboard, or download no-copyright presets (Minecraft Parkour, Subway Surfers, GTA ramps) via `yt-dlp`.
- **Audio Ducking & BGM Mixer**: Balances narrator speech (125%), gameplay sound (10%), and ambient lofi/suspense background tracks (15%).
- **Hardware-Accelerated FFmpeg**: Built-in Windows binary locator with `static-ffmpeg` fallback.
- **Real-Time Progress Streaming**: SSE (Server-Sent Events) live progress bar, step descriptions, and instant 1-click video downloads.

---

## Quickstart

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Launch the Web Dashboard
```bash
python app.py
```
Open your browser at [http://127.0.0.1:8000](http://127.0.0.1:8000).

---

## CLI Usage

The pipeline can also be run headlessly from the command line:

### Browse stories from a subreddit
```bash
python cli.py fetch --sub AmItheAsshole --limit 5
```

### Render top story from a subreddit
```bash
python cli.py render --sub AmItheAsshole --split --max-duration 60 --bgm
```

### Render a specific Reddit post by URL
```bash
python cli.py render --url "https://www.reddit.com/r/AmItheAsshole/comments/xyz123/..." --voice en-US-GuyNeural
```

### List available gameplay clips and presets
```bash
python cli.py gameplay
```

---

## Project Structure

```
reddit-story-shorts/
├── app.py                     # FastAPI web server & SSE progress streaming
├── cli.py                     # Headless command-line interface
├── requirements.txt           # Python dependencies
├── core/
│   ├── scraper.py             # Reddit JSON scraper & story text cleaner
│   ├── tts.py                 # edge-tts voiceover & word boundary parser
│   ├── subtitles.py           # Karaoke ASS & SRT subtitle generator
│   ├── title_card.py          # Pillow Reddit title card image generator
│   ├── gameplay.py            # Gameplay clips library & yt-dlp downloader
│   ├── audio_mixer.py         # BGM tracks & audio ducking presets
│   ├── story_splitter.py      # Sequential story multi-part slicer
│   ├── ffmpeg_manager.py      # Binary locator & verification
│   └── composer.py            # FFmpeg 9:16 video composition engine
├── templates/
│   └── index.html             # Sleek dark-mode dashboard UI
├── static/
│   └── js/app.js              # Dashboard client logic & SSE streaming
├── assets/
│   ├── gameplay/              # Background gameplay videos
│   └── music/                 # Royalty-free BGM tracks
├── output/                    # Rendered vertical MP4 videos
└── tests/                     # Comprehensive test suite (21 passing tests)
```

---

## Running Tests

Execute the full test suite with pytest:
```bash
pytest tests/ -v
```
