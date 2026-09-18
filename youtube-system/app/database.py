"""Async SQLite storage for video metadata.

Single-writer design: only api-server touches this database. Workers
communicate state changes through Redis events consumed by
completion_consumer.py.
"""
import logging
import os
import time
import uuid

import aiosqlite

from app.config import config

logger = logging.getLogger(__name__)


async def init_db() -> None:
    os.makedirs(os.path.dirname(config.db_path), exist_ok=True)
    async with aiosqlite.connect(config.db_path) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS videos (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                original_path TEXT,
                duration_sec REAL,
                width INTEGER,
                height INTEGER,
                error_msg TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS renditions (
                id TEXT PRIMARY KEY,
                video_id TEXT NOT NULL REFERENCES videos(id),
                resolution TEXT NOT NULL,
                playlist_path TEXT,
                bitrate_kbps INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                UNIQUE(video_id, resolution)
            );
            CREATE INDEX IF NOT EXISTS idx_renditions_video ON renditions(video_id);
        """)
        await db.commit()
    logger.info("Database initialized")


async def insert_video(video_id: str, title: str, description: str,
                       original_path: str) -> None:
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO videos (id, title, description, status, original_path,
                                   created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, description=excluded.description,
                 original_path=excluded.original_path, status='pending',
                 error_msg=NULL, updated_at=excluded.updated_at""",
            (video_id, title, description, original_path, now, now),
        )
        await db.commit()


async def get_video(video_id: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_videos() -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM videos ORDER BY created_at DESC")
        return [dict(r) for r in await cursor.fetchall()]


async def set_video_status(video_id: str, status: str,
                           error_msg: str | None = None) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE videos SET status = ?, error_msg = ?, updated_at = ? WHERE id = ?",
            (status, error_msg, time.time(), video_id),
        )
        await db.commit()


async def upsert_video_info(video_id: str, duration_sec: float | None,
                            width: int | None, height: int | None) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """UPDATE videos
               SET duration_sec = ?, width = ?, height = ?, updated_at = ?
               WHERE id = ?""",
            (duration_sec, width, height, time.time(), video_id),
        )
        await db.commit()


async def replace_renditions(video_id: str, renditions: list[dict]) -> None:
    """Replace rendition rows with the set announced by the worker."""
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute("DELETE FROM renditions WHERE video_id = ?", (video_id,))
        for r in renditions:
            await db.execute(
                """INSERT INTO renditions (id, video_id, resolution, bitrate_kbps, status)
                   VALUES (?, ?, ?, ?, 'processing')""",
                (uuid.uuid4().hex, video_id, r["resolution"], r["bitrate_kbps"]),
            )
        await db.commit()


async def set_rendition_done(video_id: str, resolution: str,
                             playlist_path: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """UPDATE renditions SET status = 'done', playlist_path = ?
               WHERE video_id = ? AND resolution = ?""",
            (playlist_path, video_id, resolution),
        )
        await db.commit()


async def set_renditions_failed(video_id: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE renditions SET status = 'failed' WHERE video_id = ?", (video_id,)
        )
        await db.commit()


async def get_renditions(video_id: str) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """SELECT resolution, playlist_path, bitrate_kbps, status
               FROM renditions WHERE video_id = ?""",
            (video_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_by_status() -> dict[str, int]:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute("SELECT status, COUNT(*) FROM videos GROUP BY status")
        return {row[0]: row[1] for row in await cursor.fetchall()}
