"""Configuration for the YouTube video streaming system (api-server)."""
import os
from dataclasses import dataclass


@dataclass
class Config:
    # Storage (volume-mounted at /app/data in Docker)
    db_path: str = os.getenv("DB_PATH", "data/youtube.db")
    original_dir: str = os.getenv("ORIGINAL_DIR", "data/original")
    transcoded_dir: str = os.getenv("TRANSCODED_DIR", "data/transcoded")

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Redis queues (design doc: message queue decoupling)
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    task_queue: str = "transcode:tasks"
    event_queue: str = "transcode:events"

    # Upload rules (design doc assumptions: max 1GB per video)
    presign_ttl: int = 300
    max_upload_bytes: int = 1 << 30  # 1GB
    allowed_exts: tuple = ("mp4", "mov", "avi", "mkv", "webm")


config = Config()
