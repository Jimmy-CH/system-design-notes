import json
import time
from typing import Dict

from fastapi import WebSocket
import redis.asyncio as redis

from app.config import settings


class ConnectionManager:
    """Manages WebSocket connections and Redis Pub/Sub subscriptions."""

    def __init__(self):
        # user_id -> WebSocket
        self.active_connections: Dict[str, WebSocket] = {}
        self.redis: redis.Redis | None = None
        self.pubsub: redis.client.PubSub | None = None

    async def connect(self, user_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[user_id] = websocket

        # Register in Redis
        r = await self._get_redis()
        await r.set(f"user_server:{user_id}", settings.SERVICE_NAME)
        await r.hset(f"presence:{user_id}", mapping={
            "status": "online",
            "last_heartbeat": str(int(time.time())),
        })

        # Subscribe to personal channel
        await self.pubsub.subscribe(f"channel:{user_id}")

    def disconnect(self, user_id: str):
        self.active_connections.pop(user_id, None)

    async def cleanup(self, user_id: str):
        r = await self._get_redis()
        await r.delete(f"user_server:{user_id}")
        await r.hset(f"presence:{user_id}", mapping={"status": "offline"})
        try:
            await self.pubsub.unsubscribe(f"channel:{user_id}")
        except Exception:
            pass

    async def send_personal(self, user_id: str, data: dict):
        ws = self.active_connections.get(user_id)
        if ws:
            await ws.send_json(data)

    async def listen_pubsub(self):
        """Listen for messages from Redis Pub/Sub and forward to WebSocket clients."""
        try:
            async for message in self.pubsub.listen():
                if message["type"] == "message":
                    channel = message["channel"]
                    if isinstance(channel, bytes):
                        channel = channel.decode()
                    data = json.loads(message["data"])

                    # Route message to the right user(s)
                    if channel.startswith("channel:group:"):
                        # Forward to all connected users in this group
                        target_ids = data.pop("target_user_ids", [])
                        for uid in target_ids:
                            await self.send_personal(uid, data)
                    elif channel.startswith("channel:"):
                        user_id = channel.split("channel:")[1]
                        await self.send_personal(user_id, data)
        except Exception:
            pass  # Connection closed

    async def _get_redis(self) -> redis.Redis:
        if self.redis is None:
            self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
            self.pubsub = self.redis.pubsub()
        return self.redis


manager = ConnectionManager()
