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
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'user',
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
        """)
        # videos.uploader_id is nullable: rows created before the user system
        # stay anonymous. SQLite has no ADD COLUMN IF NOT EXISTS, so probe first.
        cursor = await db.execute("PRAGMA table_info(videos)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "uploader_id" not in columns:
            await db.execute(
                "ALTER TABLE videos ADD COLUMN uploader_id TEXT REFERENCES users(id)")
            logger.info("Migrated videos: added uploader_id column")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_videos_uploader ON videos(uploader_id)")
        await db.commit()
    logger.info("Database initialized")


_VIDEO_SELECT = """
    SELECT v.*, u.username AS uploader_username
    FROM videos v LEFT JOIN users u ON v.uploader_id = u.id
"""


async def insert_video(video_id: str, title: str, description: str,
                       original_path: str, uploader_id: str | None = None) -> None:
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO videos (id, title, description, status, original_path,
                                   uploader_id, created_at, updated_at)
               VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title, description=excluded.description,
                 original_path=excluded.original_path,
                 uploader_id=excluded.uploader_id, status='pending',
                 error_msg=NULL, updated_at=excluded.updated_at""",
            (video_id, title, description, original_path, uploader_id, now, now),
        )
        await db.commit()


async def get_video(video_id: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _VIDEO_SELECT + " WHERE v.id = ?", (video_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_videos() -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(_VIDEO_SELECT + " ORDER BY v.created_at DESC")
        return [dict(r) for r in await cursor.fetchall()]


async def list_videos_by_uploader(uploader_id: str) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            _VIDEO_SELECT + " WHERE v.uploader_id = ? ORDER BY v.created_at DESC",
            (uploader_id,),
        )
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


async def insert_user(user_id: str, username: str, email: str,
                      password_hash: str, role: str) -> None:
    now = time.time()
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            """INSERT INTO users (id, username, email, password_hash, role,
                                  status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'active', ?, ?)""",
            (user_id, username, email, password_hash, role, now, now),
        )
        await db.commit()


async def get_user_by_email(email: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE email = ?", (email,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_username(username: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users WHERE username = ?", (username,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_user_by_id(user_id: str) -> dict | None:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def list_users(limit: int = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(config.db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [dict(r) for r in await cursor.fetchall()]


async def count_users() -> int:
    async with aiosqlite.connect(config.db_path) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        return row[0]


async def set_user_role(user_id: str, role: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE users SET role = ?, updated_at = ? WHERE id = ?",
            (role, time.time(), user_id),
        )
        await db.commit()


async def set_user_status(user_id: str, status: str) -> None:
    async with aiosqlite.connect(config.db_path) as db:
        await db.execute(
            "UPDATE users SET status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), user_id),
        )
        await db.commit()
