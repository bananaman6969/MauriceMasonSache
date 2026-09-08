# Shorts Stealth Pipeline

An automated pipeline designed to search and scrape top-performing YouTube Shorts, apply bounded anti-detection perturbations to bypass automated video detectors and perceptual matchers, and deliver obfuscated videos through a web dashboard and headless CLI.

---

## Features

- **Automated Shorts Discovery**: Scrapes and ranks Shorts by view counts and engagement metrics via `yt-dlp` without requiring any YouTube API quota or credentials.
- **Anti-Detection Perturbation Engine**: Employs mathematical transformations to defeat spatial, temporal, and acoustic fingerprints:
  - **Micro-Crop & Zoom** (1-2%) to break structural and edge matchers.
  - **Dynamic Pixel Noise / Grain** to disrupt perceptual hashes (pHash / dHash).
  - **Micro-Speed & Audio Tempo Perturbation** (1.01x - 1.03x) to foil duration and spectrogram matchers.
  - **Color, Brightness, & Contrast Jitter** to alter color histogram fingerprints.
  - **Horizontal Mirroring** to flip directional feature spaces.
  - **Metadata Scrambling**: Strips all existing tags and injects randomized container UUIDs and timestamps.
- **Modern Web Dashboard**: Single-page FastAPI + Tailwind CSS UI featuring real-time SSE progress streaming, video playback previews, and 1-click downloads.
- **Batch CLI Automation**: Scriptable CLI for scheduled or headless runs.
- **Zero-Setup FFmpeg**: Automatic static Windows FFmpeg management via `static-ffmpeg`.
- **SQLite Catalog & Deduplication**: Prevents redundant downloads and tracks video lifecycles (`discovered` -> `downloaded` -> `processed`).

---

## Quickstart

### 1. Launch the Web Dashboard
```bash
python app.py
```
Open your browser at [http://127.0.0.1:8000](http://127.0.0.1:8000).

### 2. CLI Usage Examples

#### Search top Shorts by niche / hashtag
```bash
python cli.py search --query "gym motivation" --limit 10
```

#### Automated end-to-end scrape, download, and anti-detection processing
```bash
python cli.py auto --query "fitness workout" --limit 5 --preset subtle --mirror
```

#### Process a specific Short by YouTube Video ID
```bash
python cli.py process --id "VIDEO_ID" --preset subtle --mirror
```

#### List cataloged videos and their statuses
```bash
python cli.py list
```

---

## Anti-Detection Presets

| Preset | Speed Shift | Micro-Zoom | Noise Sigma | Contrast / Brightness |
| :--- | :--- | :--- | :--- | :--- |
| **Subtle** (Recommended) | 1.012x - 1.028x | 1.012x - 1.025x | 8 - 16 | Mild (1.01 - 1.03) |
| **Moderate** | 1.025x - 1.045x | 1.025x - 1.040x | 16 - 26 | Medium (1.02 - 1.05) |
| **Aggressive** | 1.035x - 1.065x | 1.035x - 1.055x | 26 - 42 | High (1.04 - 1.08) |

---

## Running the Automated Test Suite

```bash
python -m pytest tests/ --basetemp=.pytest_temp -v
```
All unit, integration, and API tests run locally with isolated temp paths.
