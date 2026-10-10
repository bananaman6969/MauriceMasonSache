"""Atomically hand completed renders to the optional upload worker."""

import json
import os
from pathlib import Path


def handoff_video(output_dir: str, filename: str, title: str) -> bool:
    profile = os.environ.get("TIKTOK_UPLOAD_PROFILE", "").strip()
    if not profile:
        return False
    video = Path(output_dir) / filename
    manifest = video.with_suffix(".post.json")
    temporary = manifest.with_suffix(".json.tmp")
    temporary.write_text(json.dumps({
        "video": filename,
        "profile": profile,
        "title": title,
        "is_aigc": True,
    }, ensure_ascii=False), encoding="utf-8")
    temporary.replace(manifest)
    return True
