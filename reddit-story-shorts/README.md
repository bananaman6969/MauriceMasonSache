# Reddit Story Shorts Generator

An automated web dashboard and CLI pipeline that scrapes viral Reddit stories, synthesizes ultra-realistic voiceovers with word-by-word timestamps via `edge-tts`, overlays animated karaoke captions and a dark-mode Reddit post title card, and composites the video in 9:16 vertical format (1080x1920) over background gameplay footage with ducked audio.

---

## Features

- **Live Reddit RSS sourcing**: Dashboard load and Fetch Stories retrieve public RSS feeds without API keys. Supported subreddits are AmItheAsshole, AskReddit, tifu, confession, TrueOffMyChest, stories, pettyrevenge, and relationship_advice. Hot, Newest, Top Today, and Top This Week are supported. Duplicate posts, removed bodies, and known automated forum posts are filtered out.
- **Transparent freshness**: Feeds are cached for five minutes. If refresh fails, posts fetched within six hours may be shown with a cached label; otherwise the dashboard shows an unavailable message. Browsing never silently substitutes the bundled curated dataset. RSS does not supply votes or comment counts, so these display as unavailable. AskReddit questions usually need a story or comment added manually in the editor.
- **Rate-limit recovery**: Reddit cooldowns persist across app restarts and honor `Retry-After` seconds or dates. If no retry time is provided, repeated throttles use increasing delays. The open dashboard shows the next retry time and retries automatically. Cached posts from a different sort in the same subreddit remain available with an explicit fallback label.

- **Direct post import**: Reddit post URLs also try RSS before the older JSON and manual-title fallback.
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

### Optional local Kokoro voices

Install the free local engine with Python 3.12:

```powershell
.\.venv-app\Scripts\python.exe -m pip install --no-compile -r requirements-kokoro.txt
```

If your project is in OneDrive, an alternative is to install the optional voice packages outside the synced folder. With Python 3.12 installed, run:

```powershell
py -3.12 -m pip install --no-compile --target "$env:LOCALAPPDATA\RedditStoryShorts\kokoro-packages" -r requirements-kokoro.txt
```

The app detects this Windows directory automatically. Keep the app's Python version at 3.12 when using it. `KOKORO_SITE_PACKAGES` can point to a different optional package directory.

Restart the app, choose **Voice Engine → Kokoro**, select a voice, then click **Hear demo**. The identical demo text makes comparison with Microsoft's online voices easy. The first use downloads the model, pronunciation resources and selected voice; later inference runs locally on the CPU with no API key or per-video fee. American voices include Heart, Bella, Fenrir and Adam; British voices include Emma and George. Internet is required for initial downloads and for any voice not downloaded yet.

Kokoro supplies synthesis-token timestamps. The app joins word fragments and punctuation, offsets each segment by its actual audio length, and uses those word times for caption highlighting. It does not estimate word positions by dividing the audio evenly. Missing timestamps produce an error rather than invented timing. Models are loaded lazily and shared; local synthesis is serialized to avoid competing for memory. Audio and timestamps reuse the existing narration cache. Microsoft voices remain available when the optional dependencies are not installed.

Model downloads live under `cache/kokoro/` unless `HF_HOME` is set externally. New computers need the optional installation and their own initial downloads, or a copy of the cache. The existing text cleaner preserves “so”, “So”, and “SO” instead of expanding them into “significant other”.

### Faster rendering

The script editor includes optional **Creator-style word censoring**, enabled in the dashboard by default: raped → gr*ped, murdered → unalived, fucking → f*cking. The expanded English list covers profanity, violence, abuse, sexual terms, self-harm and drug references with common inflections. Voiceover uses pronounceable alternatives (graped, unalived, effing); captions restore the masked spellings and punctuation without changing word timings, including around contractions. Title cards, script previews and split previews use the display versions. The editable source stays unchanged. Review previews: automatic word replacements cannot interpret context. This is not a content moderation system and does not guarantee TikTok distribution or Creator Rewards eligibility.

Caption groups follow sentence endings and pauses of at least 0.35 seconds, with up to three words per group. Highlighting follows each spoken word's start and end timestamps; small gaps hold the phrase without a highlighted word, and long pauses clear captions. SRT exports use the same phrase grouping.

The editor's creator widgets show opening-hook feedback, a duration target and a speed-adjusted word budget, plus an optional closing question appended once to previews and exports. Duration is an estimate, not an automatic trim. Multipart output stays under manual control. Each multipart video narrates the full title followed by its part number; the splitter reserves words for that repeated introduction and the follow-up prompt. These are editing aids, not predictions of engagement.

For the cleanest export, choose **High Quality — 1080p, 30 fps**. This mode uses less video compression, a more thorough encoding preset, and 320 kbps AAC audio. Fast mode retains the quicker 720p settings. Higher quality generally produces larger files and can take longer to render. Prepared backgrounds use the corresponding quality settings and are cached separately.

Narration is normalized for consistent loudness, background audio automatically ducks during speech, and the final mix has peak protection. The voice selector loads the available English voices. **Hear demo** plays a fixed narration sample using your selected voice and speed, even without a story. **Preview my script** plays up to 500 characters from your editor. Both show replay controls and a manual Play option when autoplay is blocked. Voice model quality and source footage resolution still limit the final result; exporting 720p footage at 1080p cannot recover missing detail.

Choose **Fast — 720p, 30 fps** for quicker exports, or **Full HD — 1080p, 30 fps** for maximum resolution. Automatic encoding tests NVIDIA, Intel Quick Sync, and AMD encoders on the current machine and uses a working encoder when available. Failed hardware renders retry on the CPU. Captions and title cards remain proportional in either mode.

Rendering runs in a background worker so progress updates and cancellation remain responsive. Jobs are queued one at a time to avoid competing for encoding resources. With no gameplay available, the app uses a six-second looping background instead of generating a five-minute test clip.

Narration (including word timestamps) is cached by script, voice, speed, volume, and pitch. Gameplay is prepared once per export resolution and reused until the source file changes. The first render of a new gameplay file includes preparation of the full clip. Completed jobs display preparation, speech, rendering, and total times; these timings are also available from the job status endpoint.

Caches live in `reddit-story-shorts/cache/` and are ignored by Git. To reclaim disk space, stop the app and delete that directory; the next render rebuilds the required assets.

The CLI supports the same options:
```bash
python cli.py render --sub AmItheAsshole --export-profile fast --encoding auto
```

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

### Satisfying cooking backgrounds

The Background Footage selector groups ready clips into Satisfying Cooking, Gameplay, and Custom. Cooking presets include tomato slicing (portrait 1080p), dough mixing, and simmering meatballs. Use the inline player to preview a background. Short clips loop automatically for the full narration. Add Background downloads a preset, reports failures, and selects the completed clip.

Cooking footage comes from Mixkit under its Stock Video Free License: [tomato slicing](https://mixkit.co/free-stock-video/a-man-slices-a-tomato-40534/), [dough mixing](https://mixkit.co/free-stock-video/cook-mixing-flour-for-a-dough-42464/), and [simmering meatballs](https://mixkit.co/free-stock-video/cooking-meat-balls-in-sauce-3806/). Videos remain local in assets/gameplay and are ignored by Git; new checkouts can download them through Add Background.
