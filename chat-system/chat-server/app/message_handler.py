import json
import time

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import text

from app.config import settings
from app.snowflake import generator

# Database setup for chat server
engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_redis() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


async def handle_send_message(sender_id: str, receiver_id: str, content: str, channel_type: str):
    """Process an outgoing message."""
    r = await get_redis()
    msg_id = str(generator.generate())
    timestamp = int(time.time())

    message = {
        "message_id": msg_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "content": content,
        "type": "text",
        "timestamp": timestamp,
        "channel_type": channel_type,
    }

    # Store message in KV store
    await r.set(f"message:{msg_id}", json.dumps(message))

    if channel_type == "one_to_one":
        await _handle_one_to_one(r, sender_id, receiver_id, message)
    elif channel_type == "group":
        await _handle_group_message(r, sender_id, receiver_id, message)

    await r.aclose()
    return message


async def _handle_one_to_one(r: redis.Redis, sender_id: str, receiver_id: str, message: dict):
    """Handle one-to-one message delivery."""
    channel_id = "_".join(sorted([sender_id, receiver_id]))

    # Add to sender's inbox
    await r.zadd(
        f"inbox:{sender_id}:{channel_id}",
        {message["message_id"]: int(message["message_id"])},
    )

    # Add to receiver's inbox
    await r.zadd(
        f"inbox:{receiver_id}:{channel_id}",
        {message["message_id"]: int(message["message_id"])},
    )

    # Check if receiver is online
    presence = await r.hgetall(f"presence:{receiver_id}")
    if presence and presence.get("status") == "online":
        # Publish to receiver's channel
        await r.publish(f"channel:{receiver_id}", json.dumps({
            "type": "new_message",
            "message": message,
        }))
    else:
        # Queue offline notification
        await r.publish("notification:offline", json.dumps({
            "user_id": receiver_id,
            "message": message,
        }))


async def _handle_group_message(r: redis.Redis, sender_id: str, group_id: str, message: dict):
    """Handle group message with fanout-on-write."""
    # Get all group members from database
    async with async_session() as db:
        result = await db.execute(
            text("SELECT user_id FROM group_members WHERE group_id = :gid"),
            {"gid": group_id},
        )
        member_ids = [str(row[0]) for row in result.fetchall()]

    # Fanout: add to each member's inbox
    target_user_ids = []
    for member_id in member_ids:
        await r.zadd(
            f"inbox:{member_id}:{group_id}",
            {message["message_id"]: int(message["message_id"])},
        )
        if member_id != sender_id:
            # Check if member is online
            presence = await r.hgetall(f"presence:{member_id}")
            if presence and presence.get("status") == "online":
                target_user_ids.append(member_id)
            else:
                await r.publish("notification:offline", json.dumps({
                    "user_id": member_id,
                    "message": message,
                }))

    # Broadcast to online members via Pub/Sub
    if target_user_ids:
        payload = {
            "type": "new_message",
            "message": message,
            "target_user_ids": target_user_ids,
        }
        await r.publish(f"channel:group:{group_id}", json.dumps(payload))


async def handle_sync(user_id: str, channel_id: str, last_message_id: str):
    """Sync messages for a user since last_message_id."""
    r = await get_redis()
    inbox_key = f"inbox:{user_id}:{channel_id}"

    # Get all message IDs greater than last_message_id
    min_score = str(float(last_message_id) + 1) if last_message_id != "0" else "-inf"
    message_ids = await r.zrangebyscore(inbox_key, min_score, "+inf")

    messages = []
    for mid in message_ids:
        msg_data = await r.get(f"message:{mid}")
        if msg_data:
            messages.append(json.loads(msg_data))

    await r.aclose()
    return messages
