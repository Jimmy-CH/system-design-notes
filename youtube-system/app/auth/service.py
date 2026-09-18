"""Auth + user-management business logic (spec 3).

The ONLY module that touches the users table and the refresh-token keys.
Raises domain exceptions; router.py maps them to HTTP status codes so this
layer stays HTTP-agnostic.
"""
import json
import logging
import secrets
import time

from app import database
from app.auth import security
from app.config import config

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """401 - bad credentials, or a refresh token we cannot honour."""


class PermissionError(Exception):  # noqa: A001 - name mandated by spec 3
    """403 - identified, but not allowed (banned account)."""


class ConflictError(Exception):
    """409 - username or email already taken."""


class NotFoundError(Exception):
    """404 - user does not exist."""


class ValidationError(Exception):
    """400 - invalid input Pydantic cannot express (bad role, self-target)."""


# Redis handle, injected once from the api-server lifespan. Injection (rather
# than `from app.server import redis`) keeps the dependency one-way.
_redis = None


def bind_redis(client) -> None:
    global _redis
    _redis = client


# Local-testing accounts only (spec 1.4). README must flag these as insecure.
SEED_USERS = (
    {"username": "admin", "email": "admin@mytube.local",
     "password": "Admin@123", "role": "admin"},
    {"username": "creator", "email": "creator@mytube.local",
     "password": "Creator@123", "role": "creator"},
)


async def ensure_seed_users() -> None:
    """Idempotent: skips any seed username that already exists."""
    for seed in SEED_USERS:
        if await database.get_user_by_username(seed["username"]) is not None:
            continue
        await database.insert_user(
            secrets.token_hex(12), seed["username"], seed["email"],
            security.hash_password(seed["password"]), seed["role"],
        )
        logger.info("Seeded %s account %r", seed["role"], seed["username"])


def _user_out(row: dict) -> dict:
    return {
        "id": row["id"], "username": row["username"], "email": row["email"],
        "role": row["role"], "status": row["status"],
        "created_at": row["created_at"],
    }


async def revoke_all_refresh(user_id: str) -> int:
    """Drop every session of a user (logout, ban, replay defence)."""
    prefix = security.refresh_prefix(user_id)
    deleted = 0
    async for key in _redis.scan_iter(match=f"{prefix}*", count=100):
        await _redis.delete(key)
        deleted += 1
    return deleted


async def _issue_tokens(user: dict) -> dict:
    access = security.create_access_token(
        user["id"], user["username"], user["role"])
    refresh = security.make_refresh_token(user["id"])
    await _redis.set(
        security.refresh_key(user["id"], refresh),
        json.dumps({"issued_at": int(time.time())}),
        ex=config.refresh_token_ttl,
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": config.access_token_ttl,
        "user": _user_out(user),
    }


async def register(username: str, email: str, password: str) -> dict:
    """Create a 'user'-role account. Returns no tokens (spec 4.2)."""
    if await database.get_user_by_email(email):
        raise ConflictError("email is already registered")
    if await database.get_user_by_username(username):
        raise ConflictError("username is already taken")
    user_id = secrets.token_hex(12)
    await database.insert_user(
        user_id, username, email, security.hash_password(password), "user")
    row = await database.get_user_by_id(user_id)
    logger.info("Registered user %s (%s)", username, user_id)
    return _user_out(row)


async def login(email: str, password: str) -> dict:
    user = await database.get_user_by_email(email)
    # One message for both failure modes - no account enumeration (spec 4.4).
    if user is None or not security.verify_password(password, user["password_hash"]):
        raise AuthError("invalid email or password")
    if user["status"] != "active":
        raise PermissionError("account is banned")
    return await _issue_tokens(user)


async def refresh(refresh_token: str) -> dict:
    """Rotate the refresh token; treat a replayed one as a breach (spec 2.3)."""
    user_id = security.split_refresh_token(refresh_token)
    if user_id is None:
        raise AuthError("invalid refresh token")

    key = security.refresh_key(user_id, refresh_token)
    if await _redis.get(key) is None:
        # Absent == already rotated away == probable replay: kill every session
        # this user has and force a re-login.
        revoked = await revoke_all_refresh(user_id)
        logger.warning("Refresh replay suspected for user %s; revoked %d tokens",
                       user_id, revoked)
        raise AuthError("invalid refresh token")

    user = await database.get_user_by_id(user_id)
    if user is None:
        await _redis.delete(key)
        raise AuthError("invalid refresh token")
    if user["status"] != "active":
        # Ban takes effect here at the latest (spec 2.5, layer 3).
        await revoke_all_refresh(user_id)
        raise AuthError("account is banned")

    await _redis.delete(key)
    return await _issue_tokens(user)


async def logout(user_id: str) -> None:
    await revoke_all_refresh(user_id)


async def get_me(user_id: str) -> dict:
    row = await database.get_user_by_id(user_id)
    if row is None:
        raise NotFoundError("user not found")
    return _user_out(row)


async def get_public_user(user_id: str) -> dict:
    """Public projection - never leaks email or status (spec 4.2)."""
    row = await database.get_user_by_id(user_id)
    if row is None:
        raise NotFoundError("user not found")
    return {"id": row["id"], "username": row["username"], "role": row["role"]}


async def list_users(limit: int, offset: int) -> dict:
    rows = await database.list_users(limit, offset)
    return {"users": [_user_out(r) for r in rows],
            "total": await database.count_users()}


async def set_role(actor_id: str, target_id: str, role: str) -> dict:
    if role not in security.ROLES:
        raise ValidationError(f"role must be one of: {', '.join(security.ROLES)}")
    if actor_id == target_id:
        raise ValidationError("cannot change your own role")
    if await database.get_user_by_id(target_id) is None:
        raise NotFoundError("user not found")
    await database.set_user_role(target_id, role)
    logger.info("Role of user %s set to %s by %s", target_id, role, actor_id)
    return _user_out(await database.get_user_by_id(target_id))


async def ban(actor_id: str, target_id: str, reason: str = "") -> dict:
    if actor_id == target_id:
        raise ValidationError("cannot ban yourself")
    if await database.get_user_by_id(target_id) is None:
        raise NotFoundError("user not found")
    await database.set_user_status(target_id, "banned")
    revoked = await revoke_all_refresh(target_id)
    # Immediate-revocation marker: get_current_user rejects any live access
    # token once this key exists (spec 2.5).
    await _redis.set(security.ban_key(target_id), "1", ex=config.ban_marker_ttl)
    logger.info("Banned user %s (reason=%r); revoked %d refresh tokens",
                target_id, reason, revoked)
    return _user_out(await database.get_user_by_id(target_id))


async def unban(target_id: str) -> dict:
    if await database.get_user_by_id(target_id) is None:
        raise NotFoundError("user not found")
    await database.set_user_status(target_id, "active")
    await _redis.delete(security.ban_key(target_id))
    logger.info("Unbanned user %s", target_id)
    return _user_out(await database.get_user_by_id(target_id))
