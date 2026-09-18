"""FastAPI application exposing the upload + video management API."""
import asyncio
import logging
import os
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request

from app import database
from app import presign
from app.completion_consumer import run_consumer
from app.config import config
from app.models import UploadUrlRequest, UploadUrlResponse, VideoCreateRequest
from app.presign import PresignError, ext_of
from app.queue import create_client, push_task

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

redis = None
consumer_task = None
consumer_stop = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis, consumer_task
    os.makedirs(config.original_dir, exist_ok=True)
    os.makedirs(config.transcoded_dir, exist_ok=True)
    await database.init_db()
    redis = create_client()
    consumer_stop.clear()
    consumer_task = asyncio.create_task(run_consumer(consumer_stop))
    logger.info("API server started")
    yield
    consumer_stop.set()
    if consumer_task:
        consumer_task.cancel()
    await redis.aclose()
    logger.info("API server stopped")


app = FastAPI(title="YouTube Video Streaming System", lifespan=lifespan)


def _card(v: dict) -> dict:
    return {
        "id": v["id"],
        "title": v["title"],
        "description": v["description"],
        "status": v["status"],
        "duration_sec": v["duration_sec"],
        "thumbnail_url": f"/media/{v['id']}/thumbnail.jpg"
                         if v["status"] == "ready" else None,
        "created_at": v["created_at"],
    }


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.post("/api/upload-url", response_model=UploadUrlResponse)
async def create_upload_url(req: UploadUrlRequest):
    try:
        return presign.issue(req.filename, req.size)
    except PresignError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/upload/{token}")
async def upload_binary(token: str, request: Request):
    info = presign.consume(token)
    if info is None:
        raise HTTPException(status_code=403, detail="Invalid or expired upload token")

    video_id = info["video_id"]
    ext = ext_of(request.query_params.get("filename", "video.mp4"))
    if ext not in config.allowed_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported extension .{ext}")

    original_dir = os.path.join(config.original_dir, video_id)
    os.makedirs(original_dir, exist_ok=True)
    dest = os.path.join(original_dir, f"original.{ext}")

    written = 0
    try:
        with open(dest, "wb") as f:
            async for chunk in request.stream():
                written += len(chunk)
                if written > config.max_upload_bytes:
                    raise HTTPException(
                        status_code=413, detail="File exceeds 1GB limit")
                f.write(chunk)
    except HTTPException:
        shutil.rmtree(original_dir, ignore_errors=True)
        raise
    if written == 0:
        shutil.rmtree(original_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Empty upload")

    return {"video_id": video_id, "bytes": written, "path": dest}


@app.post("/api/videos")
async def create_video(req: VideoCreateRequest):
    video_id = req.video_id
    ext = ext_of(req.filename)
    if ext not in config.allowed_exts:
        raise HTTPException(status_code=400, detail=f"Unsupported extension .{ext}")

    original_path = os.path.join(config.original_dir, video_id, f"original.{ext}")
    if not os.path.exists(original_path):
        raise HTTPException(
            status_code=400,
            detail="Binary not found; finish the upload first",
        )

    await database.insert_video(video_id, req.title, req.description, original_path)
    await push_task(redis, {"video_id": video_id, "original_path": original_path})
    logger.info("video %s queued for transcoding", video_id)
    return {"video_id": video_id, "status": "pending"}


@app.get("/api/videos")
async def list_videos():
    rows = await database.list_videos()
    return {"videos": [_card(v) for v in rows]}


@app.get("/api/videos/{video_id}")
async def get_video(video_id: str):
    v = await database.get_video(video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")
    out = _card(v)
    out["error_msg"] = v["error_msg"]
    if v["status"] == "ready":
        out["stream_url"] = f"/media/{video_id}/master.m3u8"
        out["renditions"] = await database.get_renditions(video_id)
    return out


@app.post("/api/videos/{video_id}/retry")
async def retry_video(video_id: str):
    v = await database.get_video(video_id)
    if v is None:
        raise HTTPException(status_code=404, detail="Video not found")
    if v["status"] != "failed":
        raise HTTPException(
            status_code=400, detail=f"Only failed videos can be retried (current: {v['status']})")
    if not v["original_path"] or not os.path.exists(v["original_path"]):
        raise HTTPException(status_code=400, detail="Original binary is missing")

    await database.set_video_status(video_id, "pending")
    await push_task(redis, {"video_id": video_id, "original_path": v["original_path"]})
    logger.info("video %s re-queued for transcoding", video_id)
    return {"video_id": video_id, "status": "pending"}


@app.get("/api/stats")
async def stats():
    queued = await redis.llen(config.task_queue)
    pattern = "worker:*"
    workers = 0
    async for _ in redis.scan_iter(match=pattern, count=100):
        workers += 1
    by_status = await database.count_by_status()
    return {"workers": workers, "queued_tasks": queued, "videos_by_status": by_status}
