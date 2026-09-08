"""Database module for cataloging and deduplicating YouTube Shorts."""

import json
import sqlite3
import aiosqlite
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS shorts (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    channel TEXT,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    duration INTEGER DEFAULT 0,
    original_url TEXT NOT NULL,
    thumbnail_url TEXT,
    raw_path TEXT,
    processed_path TEXT,
    status TEXT NOT NULL DEFAULT 'discovered',
    created_at TEXT NOT NULL,
    processed_at TEXT,
    perturbation_params TEXT,
    error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_shorts_status ON shorts(status);
CREATE INDEX IF NOT EXISTS idx_shorts_views ON shorts(views DESC);
"""


def init_db_sync(db_path: str) -> None:
    """Initialize database tables synchronously."""
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        conn.commit()


async def init_db(db_path: str) -> None:
    """Initialize database tables asynchronously."""
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA_SQL)
        await db.commit()


async def is_video_seen(db_path: str, video_id: str) -> bool:
    """Check if a video ID is already tracked in catalog."""
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT 1 FROM shorts WHERE id = ?", (video_id,)) as cursor:
            row = await cursor.fetchone()
            return row is not None


async def upsert_discovered(db_path: str, video: Dict[str, Any]) -> None:
    """Insert or update a newly discovered video."""
    now_iso = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            INSERT INTO shorts (
                id, title, channel, views, likes, comments, duration,
                original_url, thumbnail_url, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'discovered', ?)
            ON CONFLICT(id) DO UPDATE SET
                views = excluded.views,
                likes = excluded.likes,
                comments = excluded.comments
            """,
            (
                video["id"],
                video.get("title", "Untitled"),
                video.get("channel", "Unknown"),
                video.get("views", 0),
                video.get("likes", 0),
                video.get("comments", 0),
                video.get("duration", 0),
                video.get("original_url", f"https://www.youtube.com/shorts/{video['id']}"),
                video.get("thumbnail_url", ""),
                now_iso,
            ),
        )
        await db.commit()


async def mark_downloaded(db_path: str, video_id: str, raw_path: str) -> None:
    """Update status to downloaded and set raw_path."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE shorts SET status = 'downloaded', raw_path = ? WHERE id = ?",
            (raw_path, video_id),
        )
        await db.commit()


async def mark_processed(
    db_path: str, video_id: str, processed_path: str, params: Dict[str, Any]
) -> None:
    """Update status to processed, record output path and applied perturbation parameters."""
    now_iso = datetime.now(timezone.utc).isoformat()
    params_json = json.dumps(params)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            UPDATE shorts
            SET status = 'processed',
                processed_path = ?,
                processed_at = ?,
                perturbation_params = ?,
                error_message = NULL
            WHERE id = ?
            """,
            (processed_path, now_iso, params_json, video_id),
        )
        await db.commit()


async def mark_failed(db_path: str, video_id: str, error_msg: str) -> None:
    """Mark video processing or download as failed with error details."""
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE shorts SET status = 'failed', error_message = ? WHERE id = ?",
            (error_msg, video_id),
        )
        await db.commit()


async def list_videos(
    db_path: str, limit: int = 50, status_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Retrieve list of videos from catalog."""
    query = "SELECT * FROM shorts"
    params = []
    if status_filter:
        query += " WHERE status = ?"
        params.append(status_filter)
    query += " ORDER BY views DESC LIMIT ?"
    params.append(limit)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(query, tuple(params)) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_video(db_path: str, video_id: str) -> Optional[Dict[str, Any]]:
    """Fetch single video by ID."""
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM shorts WHERE id = ?", (video_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def delete_video(db_path: str, video_id: str) -> bool:
    """Delete a video entry from the catalog."""
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("DELETE FROM shorts WHERE id = ?", (video_id,))
        await db.commit()
        return cursor.rowcount > 0
