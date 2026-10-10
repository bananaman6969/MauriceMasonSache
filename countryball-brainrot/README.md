# Countryball Dagger Arena

A local TikTok video studio for 1v1 country flag battles. Pick any two different
flags from 250 countries and territories, or randomize the matchup. Flag balls
have no eyes. Each has rotating daggers, HP, sparks, shockwaves, motion trails,
and collectible power-ups. Videos have no text overlays.

## Run

```powershell
cd countryball-brainrot
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python app.py
```

Open http://127.0.0.1:8010. Search countries by name or two-letter code,
configure the fight, replay the preview, and click **Generate MP4**.
Exports land in `output/` and are available through the download button.
FFmpeg is found on PATH or supplied by static-ffmpeg (which may download its
executable on first use). Flags are bundled locally; no runtime flag downloads
or API keys are needed. Flag source: [Flagpedia / FlagCDN](https://flagpedia.net/download/api).

## Battle rules

- Exactly two different flags. Dagger hits remove HP; zero HP eliminates a flag.
- Daggers reverse rotation on contact, with a 0.45 second cooldown per target.
- Body collisions bounce without damage or loss of individual speed.
- After two seconds without dagger contact, balls gently steer toward each other. Any hit resets steering, and the survivor is never steered.
- Movement gains 2.5% of starting speed each second; spin gains 4% of starting rotation each second.
- Simultaneous hits can produce a draw. The winner gets a spotlight and crown; the clip ends after a 1.6-second celebration.

Pickups spawn within 42 physics pixels of arena center, giving both flags a shared target. They first appear at 2 seconds, then every 5 seconds while both contenders live.
At most two pickups remain on screen; unused pickups expire after 10 seconds.
Each seeded cycle contains all five types:

| Pickup | Effect |
| --- | --- |
| Cyan shield | Blocks two hits; expires after 8 seconds |
| Pink rage | Double dagger damage for 6 seconds |
| Purple twin blades | Adds an opposite dagger for 6 seconds |
| Green healing cross | Restores 25% of starting HP, capped at starting HP |
| Gold overdrive | Permanent +20% movement and +25% spin; stacks up to 3× |

Preview and export share seeded physics, effects, pickups, and the Pillow renderer.
Physics uses at least 120 updates per second, with adaptive substeps for fast
movement. Videos include original synthesized blade whooshes, hits, shield breaks,
pickup sounds, escalating heartbeat pulses and a victory fanfare, muxed as AAC
into H.264 MP4, 1080 × 1920, 60 FPS. Duration is the fight limit; a knockout near
that limit can add up to 1.6 seconds for its celebration. Battles without a
knockout stop at the limit. Add music
in your editor or TikTok. This studio does not upload automatically.

## Test and refresh flags

```powershell
.venv\Scripts\python -m pytest tests -q
.venv\Scripts\python fetch_flags.py
```

Refreshing flags requires internet access. The app itself runs offline.


Opening positions and blade angles produce a clash in the first second. Impact pauses run on the presentation clock and preserve physics speeds. Brief camera shakes emphasize hits. Low HP pulses red, increases the combat pace, and offers each contender one contested center healing pickup. Healing never removes an earned speed or spin increase. Click Enable sound to hear the live preview; MP4 exports always include audio.
