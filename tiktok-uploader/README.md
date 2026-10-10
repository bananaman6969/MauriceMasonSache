# Automatic TikTok uploads

Finished render → atomic `.post.json` handoff → persistent SQLite queue → Upload-Post → TikTok status polling.

This local worker supports multiple connected TikTok accounts through an Upload-Post API integration. No browser login automation is needed. An Upload-Post account, API key, and connected TikTok profiles are required for actual publishing. The implementation has offline tests; live publishing needs verification with your connected accounts. Provider plans, account capabilities, platform approval and limits still apply.

## Setup (PowerShell, from the repository root)

```powershell
python -m pip install -r tiktok-uploader/requirements.txt
Copy-Item tiktok-uploader/config.example.json tiktok-uploader/config.json
```

Edit `config.json`. For each local profile name, set `user` to its Upload-Post profile identifier and choose an explicit `privacy_level`. The sample uses `SELF_ONLY` (private). Choose `PUBLIC_TO_EVERYONE` only when you want public posts and the connected account supports it. Add more profiles to the same configuration as needed. Paths resolve relative to the configuration file.

Set `UPLOAD_POST_API_KEY` in the uploader's environment using your secret manager or a secure shell prompt. Do not put the key in configuration or commit it. The worker intentionally does not load `.env` automatically.

Before starting the Reddit Story Shorts app, set the destination profile in that app's environment:

```powershell
$env:TIKTOK_UPLOAD_PROFILE = 'stories'
python reddit-story-shorts/app.py
```

After every successful complete render job, the generator writes one handoff per video with its rendered title and AI disclosure enabled. Without `TIKTOK_UPLOAD_PROFILE`, rendering behaves as before. Changing that variable requires restarting the generator. Other sources can write handoffs to their own watched folders. The source video must be completely written before the handoff appears; write handoffs to a temporary filename, then rename atomically to `.post.json`.

Example `clip.post.json` next to a finished `clip.mp4`:

```json
{"video": "clip.mp4", "profile": "stories", "title": "Your editable caption #stories", "is_aigc": true}
```

Existing MP4s without a handoff are not automatically uploaded. Edit captions before scanning; queued metadata is frozen. Use different manifest profiles to route videos to different accounts. A given video hash is queued once per local profile, even if the file is renamed. Keep profile aliases stable and do not assign two aliases to the same TikTok account.

## Run

First verify the local queue without sending any media:

```powershell
python tiktok-uploader/uploader.py scan
python tiktok-uploader/uploader.py status
```

Then start the continuous worker with publishing enabled:

```powershell
python tiktok-uploader/uploader.py run --publish
```

Keep the worker running while the generator renders videos. `run` without `--publish` only scans; `--once` runs one scan/worker cycle. Queue state survives restarts in `tiktok-uploader/data/uploads.sqlite3`. Stop with Ctrl+C. Only one publishing worker may run against a given database; it obtains an operating-system lock. An interrupted in-flight request is recovered after its 15-minute lease expires.

The default minimum interval is one hour per profile; it controls upload submissions, not exact TikTok publication times. Provider/platform limits may require a longer interval. HTTP 429 gets backoff and retry. Every submission uses the same stored idempotency key and client request ID. A timeout or server error after submission triggers status reconciliation instead of blindly uploading again. Provider terminal failures require investigation rather than automatic reposting.

States: `queued`, `uploading`, `retry`, `checking`, `processing`, `published`, `failed`, `needs_action`. A missing request after an uncertain submission, skipped account, inbox delivery, or completed response without a TikTok result is never reported as published. For `needs_action`, inspect the provider's history before taking further action; there is deliberately no automatic force-resubmit command. Status polling continues while a request is processing. This worker reports success based on the provider's confirmed TikTok result; it does not guarantee distribution or moderation outcomes.

References: [Upload API](https://docs.upload-post.com/api/upload-video/) and [status API](https://docs.upload-post.com/api/upload-status/).

## Tests

```powershell
python -m unittest discover -s tiktok-uploader/tests -v
```
